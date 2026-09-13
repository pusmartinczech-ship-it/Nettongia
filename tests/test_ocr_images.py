import os
import time
from io import BytesIO
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import ImagePlacement, PdfEngine, TextPlacement
from openpdf_editor.main_window import MainWindow, SignatureGraphicsItem
from openpdf_editor.ocr_worker import (
    available_ocr_languages,
    prepare_ocr_job,
    read_ocr_result,
    run_ocr_job,
)


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _scanned_pdf(text: str = "OPENPDF OCR TEST") -> bytes:
    image = Image.new("RGB", (1200, 400), "white")
    font_paths = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    )
    font_path = next((path for path in font_paths if Path(path).is_file()), None)
    if font_path is None:
        pytest.skip("a TrueType test font is unavailable")
    font = ImageFont.truetype(font_path, 80)
    ImageDraw.Draw(image).text((60, 130), text, font=font, fill="black")
    payload = BytesIO()
    image.save(payload, format="PNG")
    document = pymupdf.open()
    page = document.new_page(width=600, height=200)
    page.insert_image(page.rect, stream=payload.getvalue())
    try:
        return document.tobytes()
    finally:
        document.close()


def _image_payload() -> bytes:
    image = Image.new("RGB", (240, 100), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 70, 99), fill="red")
    payload = BytesIO()
    image.save(payload, format="PNG")
    return payload.getvalue()


def test_ocr_worker_adds_invisible_searchable_text_without_visual_change(
    tmp_path: Path,
) -> None:
    if "eng" not in available_ocr_languages():
        pytest.skip("English Tesseract data is unavailable")
    source = _scanned_pdf()
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(source)
    with pymupdf.open(stream=source, filetype="pdf") as document:
        before = bytes(document[0].get_pixmap(alpha=False).samples)
        assert not document[0].get_text().strip()
    job_path, result_path, output_path = prepare_ocr_job(
        tmp_path / "job", source, (0,), "eng", 200
    )

    assert run_ocr_job(job_path) == 0
    result, error = read_ocr_result(result_path, output_path)

    assert error is None
    assert result is not None
    assert result["processed_pages"] == 1
    assert result["words_inserted"] >= 3
    with pymupdf.open(output_path) as document:
        assert "OPENPDF" in document[0].get_text()
        after = bytes(document[0].get_pixmap(alpha=False).samples)
    assert after == before


def test_ocr_worker_handles_unicode_workspace_without_system_tesseract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path / "neexistující systémová data"))
    source = _scanned_pdf("PORTABLE OCR TEST")
    workspace = tmp_path / "Příliš žluťoučký kůň" / "OCR úloha"
    job_path, result_path, output_path = prepare_ocr_job(
        workspace, source, (0,), "eng", 200
    )

    assert run_ocr_job(job_path) == 0
    result, error = read_ocr_result(result_path, output_path)

    assert error is None
    assert result is not None and result["processed_pages"] == 1
    with pymupdf.open(output_path) as document:
        assert "PORTABLE" in document[0].get_text()


def test_ocr_skips_page_that_already_contains_text(tmp_path: Path) -> None:
    if "eng" not in available_ocr_languages():
        pytest.skip("English Tesseract data is unavailable")
    source = pymupdf.open()
    page = source.new_page(width=420, height=300)
    page.insert_text((50, 80), "Existing searchable text")
    payload = source.tobytes()
    source.close()
    job_path, result_path, output_path = prepare_ocr_job(
        tmp_path / "job", payload, (0,), "eng", 200
    )

    assert run_ocr_job(job_path) == 0
    result, error = read_ocr_result(result_path, output_path)

    assert error is None
    assert result == {
        "processed_pages": 0,
        "skipped_pages": 1,
        "words_inserted": 0,
        "output_size": 0,
    }
    assert not output_path.exists()


def test_ocr_worker_reports_unavailable_language_without_output(tmp_path: Path) -> None:
    source = _scanned_pdf()
    job_path, result_path, output_path = prepare_ocr_job(
        tmp_path / "missing-language", source, (0,), "fra", 200
    )

    assert run_ocr_job(job_path) == 1
    result, error = read_ocr_result(result_path, output_path)

    assert result is None
    assert error is not None and "Missing Tesseract language data: fra" in error
    assert not output_path.exists()


def test_window_applies_ocr_as_one_undoable_document_change(tmp_path: Path) -> None:
    if "eng" not in available_ocr_languages():
        pytest.skip("English Tesseract data is unavailable")
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(_scanned_pdf("SEARCHABLE OCR TEXT"))
    window = MainWindow()
    window._activate_document(engine, None, already_saved=True)
    window._cancel_document_inspection()
    original = window.engine.source_bytes

    assert window._start_ocr((0,), "eng")
    deadline = time.monotonic() + 15
    while window._ocr_process is not None and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
        time.sleep(0.005)

    assert window._ocr_process is None
    assert window.engine.source_bytes != original
    assert "SEARCHABLE" in " ".join(run.text for run in window.engine.text_runs(0))
    assert window.has_unsaved_changes
    window.undo()
    assert window.engine.source_bytes == original
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_inserted_image_can_be_moved_resized_and_rotated() -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(500, 400))
    window = MainWindow()
    window._activate_document(engine, None, already_saved=True)
    window._cancel_document_inspection()
    placement = ImagePlacement(
        "movable-image", 0, (40, 50, 220, 125), _image_payload(), "test image"
    )
    state = window._capture_state()
    state.inserted_images.append(placement)
    window._push_state(state, 0)

    image_item = next(
        item
        for item in window.page_view.scene().items()
        if isinstance(item, SignatureGraphicsItem) and item.kind == "inserted"
    )
    assert image_item.key == placement.key
    window._transform_visual("inserted", placement.key, (100, 120, 370, 260), 37.0)

    updated = window.inserted_images[0]
    assert updated.bbox == pytest.approx((100, 120, 370, 260))
    assert updated.rotation_degrees == pytest.approx(37.0)
    assert window.page_view.selected_signature_key == placement.key
    window.undo()
    assert window.inserted_images[0] == placement
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_rotated_image_is_written_using_rotated_payload() -> None:
    payload = _image_payload()
    rotated = PdfEngine._rotated_visual_payload(payload, 90)
    original_image = Image.open(BytesIO(payload))
    rotated_image = Image.open(BytesIO(rotated))

    assert rotated_image.size == (original_image.height, original_image.width)
    assert rotated != payload


def test_original_image_selection_is_non_mutating_and_transform_is_undoable() -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(_scanned_pdf("ORIGINAL IMAGE"))
    window = MainWindow()
    window._activate_document(engine, None, already_saved=True)
    window._cancel_document_inspection()
    run = window.engine.image_runs(0)[0]
    initial_history = window.history_index

    window._promote_source_image(run.key)

    assert window.history_index == initial_history
    assert window.page_view.selected_visual_ref == ("source", run.key)
    assert not window.deleted_images
    assert not window.inserted_images

    window._transform_visual("source", run.key, (80, 40, 480, 180), 28.0)
    assert len(window.deleted_images) == 1
    assert not window.deleted_images[0].fill_removed_area
    assert len(window.inserted_images) == 1
    editable = window.inserted_images[0]
    assert not editable.overlay
    assert Image.open(BytesIO(editable.image_bytes)).size == (run.width, run.height)
    assert window.inserted_images[0].bbox == pytest.approx((80, 40, 480, 180))
    assert window.inserted_images[0].rotation_degrees == pytest.approx(28.0)
    window.undo()
    assert not window.inserted_images
    assert not window.deleted_images

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_page_move_remaps_pending_objects_and_undo() -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(500, 400, 3))
    window = MainWindow()
    window._activate_document(engine, None, already_saved=True)
    window._cancel_document_inspection()
    state = window._capture_state()
    state.inserted_texts.append(
        TextPlacement("page-zero", 0, (40, 40, 200, 80), "PAGE ZERO")
    )
    state.inserted_images.append(
        ImagePlacement("page-one", 1, (40, 100, 200, 170), _image_payload())
    )
    window._push_state(state, 0)

    window.move_current_page_down()

    assert window.current_page == 1
    assert window.inserted_texts[0].page_index == 1
    assert window.inserted_images[0].page_index == 0
    assert window.has_unsaved_changes
    window.undo()
    assert window.current_page == 1
    assert window.inserted_texts[0].page_index == 0
    assert window.inserted_images[0].page_index == 1

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
