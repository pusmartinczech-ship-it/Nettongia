from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import __version__
from .diagnostics import OperationLog, build_diagnostic_bundle
from .engine import PdfEngine
from .inspection_worker import inspect_document
from .ocr_worker import available_ocr_languages
from .runtime import REQUIRED_OCR_USER_LANGUAGES, bundled_tessdata_path


def _write_result(path: str | Path, result: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def run_self_test(result_path: str | Path) -> int:
    """Exercise the installed PDF engine without opening a GUI window."""

    checks: dict[str, Any] = {}
    result: dict[str, Any] = {
        "application": "Nettongia PDF Editor",
        "version": __version__,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "checks": checks,
    }
    exit_code = 1
    try:
        payload = PdfEngine.blank_document_bytes(320, 240, 2)
        engine = PdfEngine()
        engine.load_bytes(payload)
        pixels, width, height, stride = engine.render_page(0, 0.5)
        if not pixels or width < 1 or height < 1 or stride < width * 3:
            raise RuntimeError("The PDF renderer returned invalid pixel data.")
        checks["pdf_open_render"] = "passed"

        with tempfile.TemporaryDirectory(prefix="openpdf-self-test-") as directory:
            output = Path(directory) / "verified.pdf"
            engine.save(output, ())
            report = inspect_document(output)
            if report.page_count != 2 or report.representative_pages_rendered != 2:
                raise RuntimeError("The saved PDF did not pass compatibility inspection.")
            operation_log = OperationLog(Path(directory) / "operation-log.jsonl")
            operation_log.record(
                "document_opened",
                operation="open",
                outcome="succeeded",
                page_count=2,
                file_size_bucket="under_1_mib",
            )
            diagnostics = build_diagnostic_bundle(
                Path(directory) / "diagnostics.zip",
                operation_log=operation_log,
                session_snapshot={
                    "document_open": True,
                    "page_count": 2,
                    "current_page": 1,
                    "file_size_bucket": "under_1_mib",
                    "language": "en",
                    "theme": "automatic",
                    "compatibility": "safe",
                    "unsaved_changes": False,
                },
                crash_path=Path(directory) / "missing-crash.log",
            )
            if diagnostics.operation_records != 1 or diagnostics.size_bytes < 1:
                raise RuntimeError("The anonymized diagnostic export is invalid.")
            checks["diagnostics_export"] = "passed"
        checks["pdf_save_verify"] = "passed"
        engine.close()

        languages = available_ocr_languages()
        checks["ocr_languages"] = sorted(languages)
        checks["ocr_ready"] = REQUIRED_OCR_USER_LANGUAGES.issubset(languages)
        tessdata = bundled_tessdata_path(verify=True)
        checks["ocr_assets_verified"] = tessdata is not None
        if tessdata is None or not checks["ocr_ready"]:
            raise RuntimeError("The complete bundled OCR data set is unavailable.")

        # Listing model filenames is not enough: exercise the OCR engine with
        # the bundled English model so a broken frozen Tesseract integration is
        # caught before an installer is published.
        scan = PdfEngine()
        scan_document = None
        text_document = None
        try:
            import pymupdf

            text_document = pymupdf.open()
            text_page = text_document.new_page(width=450, height=110)
            text_page.insert_text(
                (35, 72),
                "OFFLINE OCR 123",
                fontsize=34,
                fontname="helv",
            )
            image = text_page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            scan_document = pymupdf.open()
            page = scan_document.new_page(width=450, height=110)
            page.insert_image(page.rect, stream=image.tobytes("png"))
            scan.load_bytes(scan_document.tobytes())
            recognized = scan._source[0].get_textpage_ocr(
                language="eng",
                dpi=200,
                full=True,
                tessdata=str(tessdata),
            ).extractText()
            if not recognized.strip():
                raise RuntimeError("Bundled OCR returned no text.")
            checks["ocr_execution"] = "passed"
        finally:
            scan.close()
            if scan_document is not None:
                scan_document.close()
            if text_document is not None:
                text_document.close()
        result["status"] = "passed"
        exit_code = 0
    except Exception as exc:
        checks.setdefault("failure", f"{type(exc).__name__}: {exc}")
        result["status"] = "failed"
    _write_result(result_path, result)
    return exit_code
