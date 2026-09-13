from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pymupdf

from .ocr_worker import prepare_ocr_job, read_ocr_result
from .runtime import (
    REQUIRED_OCR_USER_LANGUAGES,
    bundled_ocr_root,
    bundled_tessdata_path,
    verify_bundled_ocr,
)


def _write_result(path: str | Path, result: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _worker_command(job_path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--ocr-worker", str(job_path)]
    return [sys.executable, "-m", "openpdf_editor.ocr_worker", str(job_path)]


def _scan_bytes(text: str = "PORTABLE OCR 123", pages: int = 1) -> bytes:
    text_document = pymupdf.open()
    scan_document = pymupdf.open()
    try:
        text_page = text_document.new_page(width=450, height=110)
        text_page.insert_text((35, 72), text, fontsize=34, fontname="helv")
        image = text_page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        image_bytes = image.tobytes("png")
        for _ in range(pages):
            page = scan_document.new_page(width=450, height=110)
            page.insert_image(page.rect, stream=image_bytes)
        return scan_document.tobytes()
    finally:
        scan_document.close()
        text_document.close()


def _run_worker(job_path: Path, *, timeout: float = 60.0) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment["TESSDATA_PREFIX"] = str(job_path.parent / "neexistující systémová data")
    return subprocess.run(
        _worker_command(job_path),
        cwd=Path(__file__).resolve().parents[1] if not getattr(sys, "frozen", False) else None,
        env=environment,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def run_portable_ocr_acceptance(result_path: str | Path) -> int:
    """Exercise packaged OCR success, failure, integrity and cancellation paths."""

    checks: dict[str, Any] = {}
    result: dict[str, Any] = {
        "format": "openpdf-portable-ocr-acceptance-v1",
        "checks": checks,
        "frozen": bool(getattr(sys, "frozen", False)),
    }
    exit_code = 1
    workspace = Path(tempfile.mkdtemp(prefix="OpenPDF–žluťoučký-kůň–"))
    try:
        if shutil.which("tesseract") or shutil.which("tesseract.exe"):
            raise RuntimeError("A system Tesseract executable is visible in PATH.")
        checks["no_system_tesseract"] = "passed"

        ocr_root = bundled_ocr_root()
        tessdata = bundled_tessdata_path(verify=True)
        if ocr_root is None or tessdata is None:
            raise RuntimeError("Bundled OCR assets failed integrity validation.")
        available = {path.stem for path in tessdata.glob("*.traineddata")}
        if not REQUIRED_OCR_USER_LANGUAGES.issubset(available):
            raise RuntimeError("A required bundled OCR language is unavailable.")
        checks["bundle_integrity"] = "passed"

        success_job, success_result, success_output = prepare_ocr_job(
            workspace / "úspěšná úloha", _scan_bytes(), (0,), "eng", 200
        )
        completed = _run_worker(success_job)
        if completed.returncode != 0:
            worker_detail = "no worker result was created"
            if success_result.exists():
                try:
                    _failed_result, worker_error = read_ocr_result(
                        success_result, success_output
                    )
                    if worker_error:
                        worker_detail = worker_error
                except (OSError, TypeError, ValueError) as exc:
                    worker_detail = f"unreadable worker result ({type(exc).__name__})"
            raise RuntimeError(
                "The isolated packaged OCR worker failed "
                f"with exit code {completed.returncode}: {worker_detail}"
            )
        worker_result, worker_error = read_ocr_result(success_result, success_output)
        if worker_error or worker_result is None or worker_result["processed_pages"] != 1:
            raise RuntimeError("The isolated packaged OCR result is invalid.")
        with pymupdf.open(success_output) as document:
            if "PORTABLE" not in document[0].get_text().upper():
                raise RuntimeError("The isolated packaged OCR output is not searchable.")
        checks["isolated_ocr_execution"] = "passed"

        error_job, error_result, error_output = prepare_ocr_job(
            workspace / "chybějící jazyk", _scan_bytes(), (0,), "fra", 200
        )
        failed = _run_worker(error_job)
        failure_result, failure_message = read_ocr_result(error_result, error_output)
        if failed.returncode == 0 or failure_result is not None or not failure_message:
            raise RuntimeError("The missing-language failure was not reported safely.")
        if error_output.exists():
            raise RuntimeError("A failed OCR job left an output PDF.")
        checks["controlled_error"] = "passed"

        copied_bundle = workspace / "poškozený balíček"
        shutil.copytree(ocr_root, copied_bundle)
        (copied_bundle / "tessdata" / "ces.traineddata").write_bytes(b"damaged")
        if verify_bundled_ocr(copied_bundle):
            raise RuntimeError("A modified OCR model passed integrity validation.")
        checks["tamper_detection"] = "passed"

        cancel_job, cancel_result, cancel_output = prepare_ocr_job(
            workspace / "zrušená úloha", _scan_bytes(pages=60), tuple(range(60)), "eng", 300
        )
        process = subprocess.Popen(
            _worker_command(cancel_job),
            cwd=Path(__file__).resolve().parents[1] if not getattr(sys, "frozen", False) else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.10)
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.returncode == 0 or cancel_output.exists():
            raise RuntimeError("Cancellation allowed the OCR job to commit output.")
        if cancel_result.exists():
            payload = json.loads(cancel_result.read_text(encoding="utf-8"))
            if payload.get("status") == "succeeded":
                raise RuntimeError("A cancelled OCR job reported success.")
        checks["process_cancellation"] = "passed"
        checks["unicode_paths"] = "passed"

        result["status"] = "passed"
        exit_code = 0
    except Exception as exc:
        checks["failure"] = f"{type(exc).__name__}: {exc}"
        result["status"] = "failed"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
        _write_result(result_path, result)
    return exit_code
