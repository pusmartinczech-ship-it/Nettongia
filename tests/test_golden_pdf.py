import os
from pathlib import Path

import pytest

from openpdf_editor.engine import PdfEngine
from openpdf_editor.visual_regression import (
    PageRaster,
    changed_pixels_outside_regions,
    compare_documents,
    compare_rasters,
)
from tools.golden_pdf_audit import run_audit


SAMPLES = Path(
    os.environ.get("OPENPDF_TEST_SAMPLES", Path(__file__).resolve().parents[2] / "upload")
)


def test_golden_pdf_noop_is_exact_and_edits_are_local(tmp_path: Path) -> None:
    report = run_audit(tmp_path / "report")

    assert report["status"] == "passed"
    assert report["noop_save"]["exact"]
    assert all(
        page["changed_pixels"] == 0
        for page in report["noop_save"]["pages"]
    )
    assert report["representative_edit"]["local_only"]
    assert report["representative_edit"]["outside_changed_pixels"] == 0
    assert report["representative_edit"]["page"]["changed_pixels"] > 0
    assert (tmp_path / "report" / "golden_pdf_audit.json").is_file()
    assert (tmp_path / "report" / "golden_pdf_audit.md").is_file()


def test_pixel_diff_reports_exact_changed_pixel_and_bbox() -> None:
    before = PageRaster(0, 2, 1, 6, b"\x00\x00\x00\xff\xff\xff")
    after = PageRaster(0, 2, 1, 6, b"\x00\x00\x00\xff\x7f\xff")

    diff = compare_rasters(before, after)

    assert diff.changed_pixels == 1
    assert diff.changed_ratio == 0.5
    assert diff.max_channel_delta == 128
    assert diff.changed_bbox == (1, 0, 2, 1)
    assert changed_pixels_outside_regions(before, after, ((1, 0, 2, 1),)) == 0
    assert changed_pixels_outside_regions(before, after, ((0, 0, 1, 1),)) == 1


def test_visual_comparison_rejects_page_geometry_changes() -> None:
    before = PdfEngine.blank_document_bytes(200, 300, 1)
    after = PdfEngine.blank_document_bytes(210, 300, 1)

    with pytest.raises(ValueError, match="geometry"):
        compare_documents(before, after, scale=1.0)


def test_visual_comparison_rejects_invalid_scale() -> None:
    source = PdfEngine.blank_document_bytes(200, 300, 1)

    with pytest.raises(ValueError, match="scale"):
        compare_documents(source, source, scale=10.0)


@pytest.mark.parametrize(
    "file_name",
    (
        "Test_Word_PDF.pdf",
        "0015_001.pdf",
        "KS_Teil_2_2_01_KS26_ROB-KUKA_Projektspezifische_Vorgaben.pdf",
        "33-E00-01EKFA2A22_2018-03-16_CZ.pdf",
    ),
)
def test_supplied_pdf_noop_save_preserves_sampled_pixels(
    tmp_path: Path,
    file_name: str,
) -> None:
    source = SAMPLES / file_name
    if not source.is_file():
        pytest.skip("Supplied visual-regression PDF is unavailable")
    engine = PdfEngine()
    engine.open(source)
    output = tmp_path / file_name
    try:
        page_indices = tuple(
            dict.fromkeys((0, engine.page_count // 2, engine.page_count - 1))
        )
        engine.save(output, [])
    finally:
        engine.close()

    diffs = compare_documents(
        source,
        output,
        scale=0.5,
        page_indices=page_indices,
    )

    assert all(diff.changed_pixels == 0 for diff in diffs)
