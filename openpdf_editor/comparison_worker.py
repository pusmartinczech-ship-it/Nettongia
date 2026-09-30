from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .document_compare import DocumentComparison, compare_pdf_documents
from .engine import PdfEngine
from .recovery import (
    RecoverySnapshot,
    read_recovery_snapshot,
    validate_recovery_assets,
    validate_recovery_pages,
    write_recovery_snapshot,
)


COMPARISON_JOB_FORMAT = "nettongia-pdf-comparison"
COMPARISON_JOB_SCHEMA_VERSION = 1
MAX_DESCRIPTOR_BYTES = 1024 * 1024


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(encoded) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The comparison result is too large.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def prepare_comparison_job(
    workspace: str | Path,
    snapshot: RecoverySnapshot,
    comparison_pdf: bytes,
) -> tuple[Path, Path, Path]:
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    snapshot_path = root / "current.openpdf-recovery"
    comparison_path = root / "comparison.pdf"
    materialized_path = root / "current-materialized.pdf"
    result_path = root / "result.json"
    write_recovery_snapshot(snapshot_path, snapshot)
    comparison_path.write_bytes(comparison_pdf)
    descriptor = {
        "format": COMPARISON_JOB_FORMAT,
        "schema_version": COMPARISON_JOB_SCHEMA_VERSION,
        "snapshot_path": str(snapshot_path),
        "comparison_path": str(comparison_path),
        "materialized_path": str(materialized_path),
        "result_path": str(result_path),
    }
    _write_json_atomic(root / "job.json", descriptor)
    return root / "job.json", result_path, materialized_path


def _read_job(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The comparison job is too large.")
    try:
        job = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The comparison job is damaged.") from exc
    if not isinstance(job, dict) or job.get("format") != COMPARISON_JOB_FORMAT:
        raise ValueError("The comparison job format is invalid.")
    if job.get("schema_version") != COMPARISON_JOB_SCHEMA_VERSION:
        raise ValueError("The comparison job version is unsupported.")
    for name in (
        "snapshot_path",
        "comparison_path",
        "materialized_path",
        "result_path",
    ):
        value = job.get(name)
        if not isinstance(value, str) or not value or len(value) > 32_768:
            raise ValueError(f"Invalid comparison field: {name}.")
    return job


def run_comparison_job(job_path: str | Path) -> int:
    result_path: Path | None = None
    engine = PdfEngine()
    try:
        job = _read_job(job_path)
        result_path = Path(job["result_path"])
        snapshot = read_recovery_snapshot(job["snapshot_path"])
        validate_recovery_assets(snapshot)
        engine.load_bytes(snapshot.pdf_bytes)
        validate_recovery_pages(snapshot, engine.page_count)
        engine.save(
            job["materialized_path"],
            snapshot.edits,
            snapshot.signatures,
            snapshot.inserted_images,
            snapshot.deleted_images,
            snapshot.inserted_texts,
        )
        current_bytes = Path(job["materialized_path"]).read_bytes()
        comparison_bytes = Path(job["comparison_path"]).read_bytes()
        comparison = compare_pdf_documents(current_bytes, comparison_bytes)
        _write_json_atomic(
            result_path,
            {
                "format": COMPARISON_JOB_FORMAT,
                "status": "succeeded",
                "comparison": comparison.to_dict(),
            },
        )
        return 0
    except Exception as exc:
        if result_path is not None:
            try:
                _write_json_atomic(
                    result_path,
                    {
                        "format": COMPARISON_JOB_FORMAT,
                        "status": "failed",
                        "error": str(exc),
                    },
                )
            except OSError:
                pass
        return 1
    finally:
        engine.close()


def read_comparison_result(path: str | Path) -> tuple[DocumentComparison | None, str | None]:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The comparison result is too large.")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The comparison result is damaged.") from exc
    if not isinstance(result, dict) or result.get("format") != COMPARISON_JOB_FORMAT:
        raise ValueError("The comparison result is invalid.")
    if result.get("status") == "failed":
        return None, str(result.get("error") or "PDF comparison failed.")
    if result.get("status") != "succeeded":
        raise ValueError("The comparison result status is invalid.")
    return DocumentComparison.from_dict(result.get("comparison")), None


def main() -> int:
    import sys

    if len(sys.argv) != 2:
        return 2
    return run_comparison_job(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
