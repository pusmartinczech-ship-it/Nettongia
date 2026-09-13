from __future__ import annotations

import json
import os
from pathlib import Path

from openpdf_editor.portable_ocr_acceptance import run_portable_ocr_acceptance


def test_portable_ocr_acceptance_without_system_tesseract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    python_directory = str(Path(os.sys.executable).parent)
    monkeypatch.setenv("PATH", python_directory)
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    result_path = tmp_path / "výsledek přenosného OCR.json"

    assert run_portable_ocr_acceptance(result_path) == 0

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    assert result["checks"] == {
        "bundle_integrity": "passed",
        "controlled_error": "passed",
        "isolated_ocr_execution": "passed",
        "no_system_tesseract": "passed",
        "process_cancellation": "passed",
        "tamper_detection": "passed",
        "unicode_paths": "passed",
    }
