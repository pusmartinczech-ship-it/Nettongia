#!/usr/bin/env python3
"""Run OpenPDF Editor compatibility checks in one process per PDF.

The process boundary is intentional: malformed PDF files can trigger failures
inside native libraries that Python cannot catch.  The coordinator records a
crash or timeout and continues with the rest of the corpus.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # Windows
    resource = None  # type: ignore[assignment]

try:
    import pymupdf
except ImportError:  # PyMuPDF before 1.24
    import fitz as pymupdf

from openpdf_editor import __version__
from openpdf_editor.engine import PdfEngine


def _sample_pages(page_count: int) -> list[int]:
    if page_count <= 0:
        return []
    return sorted({0, page_count // 2, page_count - 1})


def _outline_count(engine: PdfEngine, limit: int = 100) -> int:
    first = engine.first_outline()
    if first is None:
        return 0
    pending = [first]
    visited: set[int] = set()
    count = 0
    while pending and count < limit:
        entry = pending.pop()
        identity = id(entry._cursor)
        if identity in visited:
            continue
        visited.add(identity)
        count += 1
        sibling = engine.next_outline(entry)
        child = engine.child_outline(entry)
        if sibling is not None:
            pending.append(sibling)
        if child is not None:
            pending.append(child)
    return count


def _worker(path: Path) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "status": "failed",
    }
    engine = PdfEngine()
    try:
        try:
            password = os.environ.pop("OPENPDF_AUDIT_PASSWORD", None)
            engine.open(path, password=password)
        except (pymupdf.FileDataError, ValueError) as exc:
            result.update(
                status="rejected",
                stage="open",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return result

        page_count = engine.page_count
        if page_count <= 0:
            result.update(status="rejected", stage="open", error="PDF has no pages")
            return result

        rendered_pages = []
        text_runs = 0
        image_runs = 0
        total_pixels = 0
        for page_index in _sample_pages(page_count):
            scale = min(1.0, engine.max_render_scale(page_index))
            samples, width, height, stride = engine.render_page(page_index, scale)
            if not samples or width <= 0 or height <= 0 or stride < width * 3:
                raise RuntimeError(f"Empty render on page {page_index + 1}")
            total_pixels += width * height
            text_runs += len(engine.text_runs(page_index))
            image_runs += len(engine.image_runs(page_index))
            rendered_pages.append(page_index)

        outline_entries = _outline_count(engine)
        composed = engine.compose_bytes()
        with pymupdf.open(stream=composed, filetype="pdf") as rebuilt:
            if rebuilt.page_count != page_count:
                raise RuntimeError(
                    f"Page count changed from {page_count} to {rebuilt.page_count}"
                )
            probe = rebuilt[rendered_pages[0]].get_pixmap(
                matrix=pymupdf.Matrix(0.25, 0.25),
                alpha=False,
            )
            if not probe.samples:
                raise RuntimeError("Rebuilt PDF produced an empty render")

        result.update(
            status="passed",
            stage="complete",
            pages=page_count,
            rendered_pages=rendered_pages,
            rendered_pixels=total_pixels,
            sampled_text_runs=text_runs,
            sampled_image_runs=image_runs,
            sampled_outline_entries=outline_entries,
            composed_size_bytes=len(composed),
        )
        return result
    except Exception as exc:
        result.update(
            status="failed",
            stage=result.get("stage", "exercise"),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return result
    finally:
        engine.close()
        result["duration_seconds"] = round(time.monotonic() - started, 4)
        if resource is not None:
            result["max_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def _worker_main(path: Path) -> int:
    print(json.dumps(_worker(path), ensure_ascii=False, sort_keys=True))
    return 0


def _repository_details(path: Path, corpus_root: Path) -> dict[str, str] | None:
    for parent in (path.parent, *path.parents):
        if parent == corpus_root.parent:
            break
        if (parent / ".git").exists():
            try:
                commit = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"],
                    cwd=parent,
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
                remote = subprocess.check_output(
                    ["git", "remote", "get-url", "origin"],
                    cwd=parent,
                    text=True,
                    stderr=subprocess.DEVNULL,
                ).strip()
            except (OSError, subprocess.CalledProcessError):
                return None
            return {
                "repository": parent.name,
                "remote": remote,
                "commit": commit,
                "relative_path": path.relative_to(parent).as_posix(),
            }
    return None


def _coordinator(args: argparse.Namespace) -> int:
    corpus_root = args.corpus_root.resolve()
    passwords: dict[str, str] = {}
    if args.password_map is not None:
        raw_passwords = json.loads(args.password_map.read_text(encoding="utf-8"))
        if not isinstance(raw_passwords, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw_passwords.items()
        ):
            raise SystemExit("--password-map must contain a JSON object of string values.")
        passwords = raw_passwords
    paths = sorted(
        path
        for path in corpus_root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )
    if len(paths) < args.limit:
        raise SystemExit(
            f"Corpus contains {len(paths)} PDFs, but --limit requests {args.limit}."
        )
    selected = random.Random(args.seed).sample(paths, args.limit)
    selected.sort(key=lambda item: item.as_posix().lower())

    results: list[dict[str, Any]] = []
    for index, path in enumerate(selected, start=1):
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(path)]
        worker_env = dict(os.environ)
        project_root = str(Path(__file__).resolve().parents[1])
        worker_env["PYTHONPATH"] = os.pathsep.join(
            part
            for part in (project_root, worker_env.get("PYTHONPATH", ""))
            if part
        )
        relative_path = path.relative_to(corpus_root).as_posix()
        worker_env.pop("OPENPDF_AUDIT_PASSWORD", None)
        if relative_path in passwords:
            worker_env["OPENPDF_AUDIT_PASSWORD"] = passwords[relative_path]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                env=worker_env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            result = {
                "path": str(path),
                "status": "timeout",
                "duration_seconds": args.timeout,
                "error": f"Worker exceeded {args.timeout:g} seconds",
                "stderr": (exc.stderr or "")[-2000:],
            }
        else:
            output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
            if completed.returncode != 0 or not output_lines:
                result = {
                    "path": str(path),
                    "status": "crashed" if completed.returncode < 0 else "worker_error",
                    "returncode": completed.returncode,
                    "stdout": completed.stdout[-2000:],
                    "stderr": completed.stderr[-2000:],
                }
            else:
                try:
                    result = json.loads(output_lines[-1])
                except json.JSONDecodeError as exc:
                    result = {
                        "path": str(path),
                        "status": "worker_error",
                        "returncode": completed.returncode,
                        "error": f"Invalid worker JSON: {exc}",
                        "stdout": completed.stdout[-2000:],
                        "stderr": completed.stderr[-2000:],
                    }
                else:
                    if completed.stderr.strip():
                        result["stderr"] = completed.stderr[-2000:]
        source = _repository_details(path, corpus_root)
        result["path"] = path.relative_to(corpus_root).as_posix()
        if source is not None:
            result["source"] = source
        results.append(result)
        print(
            f"[{index:03d}/{len(selected):03d}] {result['status']:<12} "
            f"{path.name}",
            flush=True,
        )

    statuses = Counter(str(result.get("status", "unknown")) for result in results)
    durations = [
        float(result["duration_seconds"])
        for result in results
        if isinstance(result.get("duration_seconds"), (int, float))
    ]
    report = {
        "format": "openpdf-editor-corpus-audit",
        "application_version": __version__,
        "seed": args.seed,
        "requested_files": args.limit,
        "timeout_seconds": args.timeout,
        "password_entries_used": sum(
            path.relative_to(corpus_root).as_posix() in passwords for path in selected
        ),
        "summary": {
            "statuses": dict(sorted(statuses.items())),
            "robustness_passed": not any(
                statuses.get(status, 0)
                for status in ("crashed", "timeout", "worker_error")
            ),
            "functional_passed": statuses.get("failed", 0) == 0,
            "accepted_files": statuses.get("passed", 0),
            "safely_rejected_files": statuses.get("rejected", 0),
            "total_duration_seconds": round(sum(durations), 3),
            "slowest_seconds": round(max(durations, default=0.0), 3),
            "largest_max_rss_kib": max(
                (int(result.get("max_rss_kib", 0)) for result in results),
                default=0,
            ),
        },
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if report["summary"]["robustness_passed"] and report["summary"]["functional_passed"] else 1


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260908)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--password-map", type=Path)
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    if args.worker is None and (args.corpus_root is None or args.output is None):
        parser.error("--corpus-root and --output are required in coordinator mode")
    return args


def main() -> int:
    args = _arguments()
    if args.worker is not None:
        return _worker_main(args.worker.resolve())
    return _coordinator(args)


if __name__ == "__main__":
    raise SystemExit(main())
