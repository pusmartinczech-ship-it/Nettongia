import json
from pathlib import Path

from openpdf_editor.self_test import run_self_test


def test_self_test_opens_renders_saves_and_inspects_pdf(tmp_path: Path) -> None:
    result_path = tmp_path / "self-test.json"

    assert run_self_test(result_path) == 0

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    assert result["checks"]["pdf_open_render"] == "passed"
    assert result["checks"]["pdf_save_verify"] == "passed"
    assert result["checks"]["diagnostics_export"] == "passed"
    assert result["checks"]["ocr_assets_verified"] is True
    assert result["checks"]["ocr_execution"] == "passed"
    assert isinstance(result["checks"]["ocr_languages"], list)
