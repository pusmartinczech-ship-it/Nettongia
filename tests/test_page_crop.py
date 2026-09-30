import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from openpdf_editor.dialogs import PageCropDialog
from openpdf_editor.engine import PdfEngine
from openpdf_editor.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _source_pdf() -> bytes:
    document = pymupdf.open()
    first = document.new_page(width=420, height=300)
    first.insert_text((20, 30), "EDGE")
    first.insert_text((150, 150), "CENTER")
    second = document.new_page(width=500, height=360)
    second.insert_text((200, 180), "SECOND")
    payload = document.tobytes()
    document.close()
    return payload


def test_engine_crops_only_selected_pages_without_deleting_content() -> None:
    engine = PdfEngine()
    engine.load_bytes(_source_pdf())
    with pymupdf.open(stream=engine.source_bytes, filetype="pdf") as original:
        original_streams = [
            original.xref_stream(xref) for xref in original[0].get_contents()
        ]

    cropped = engine.bytes_with_pages_cropped([0], (20, 30, 40, 50))

    with pymupdf.open(stream=cropped, filetype="pdf") as document:
        assert document[0].rect.width == pytest.approx(360)
        assert document[0].rect.height == pytest.approx(220)
        assert document[0].mediabox == pymupdf.Rect(0, 0, 420, 300)
        assert document[0].cropbox == pymupdf.Rect(20, 30, 380, 250)
        assert document[1].rect.width == pytest.approx(500)
        # CropBox changes visibility, not the underlying content stream.
        cropped_streams = [
            document.xref_stream(xref) for xref in document[0].get_contents()
        ]
        assert cropped_streams == original_streams


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
def test_engine_crop_margins_follow_rotated_page_view(rotation: int) -> None:
    document = pymupdf.open()
    page = document.new_page(width=600, height=800)
    page.set_cropbox(pymupdf.Rect(50, 60, 550, 740))
    page.set_rotation(rotation)
    payload = document.tobytes()
    document.close()
    engine = PdfEngine()
    engine.load_bytes(payload)
    before = engine.page_rect(0)

    cropped = engine.bytes_with_pages_cropped([0], (10, 20, 30, 40))

    with pymupdf.open(stream=cropped, filetype="pdf") as result:
        assert result[0].rotation == rotation
        assert result[0].rect.width == pytest.approx(before.width - 40)
        assert result[0].rect.height == pytest.approx(before.height - 60)
        assert result[0].mediabox == pymupdf.Rect(0, 0, 600, 800)
        assert result[0].cropbox.x0 >= 50
        assert result[0].cropbox.y0 >= 60
        assert result[0].cropbox.x1 <= 550
        assert result[0].cropbox.y1 <= 740


def test_engine_rejects_empty_or_excessive_crop() -> None:
    engine = PdfEngine()
    engine.load_bytes(_source_pdf())
    with pytest.raises(ValueError, match="at least one crop margin"):
        engine.bytes_with_pages_cropped([0], (0, 0, 0, 0))
    with pytest.raises(ValueError, match="smaller than"):
        engine.bytes_with_pages_cropped([0], (200, 0, 200, 0))
    with pytest.raises(ValueError, match="cannot be negative"):
        engine.bytes_with_pages_cropped([0], (-1, 0, 0, 0))


def test_crop_dialog_validates_scope_and_result() -> None:
    app = _application()
    dialog = PageCropDialog(
        (420, 300),
        [(420, 300), (500, 360)],
        [(420, 300), (500, 360)],
    )
    assert dialog.scope == "selected"
    assert not dialog.buttons.button(QDialogButtonBox.Apply).isEnabled()

    dialog.left_box.setValue(10)
    dialog.right_box.setValue(5)
    app.processEvents()
    left, top, right, bottom = dialog.margins_points
    assert left == pytest.approx(10 * 72 / 25.4)
    assert right == pytest.approx(5 * 72 / 25.4)
    assert top == bottom == 0
    assert dialog.buttons.button(QDialogButtonBox.Apply).isEnabled()
    assert "mm" in dialog.result_label.text()
    dialog.buttons.button(QDialogButtonBox.Apply).click()
    assert dialog.result() == QDialog.Accepted


def test_main_window_crop_supports_undo(tmp_path: Path, monkeypatch) -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(_source_pdf())
    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, tmp_path / "pages.pdf", already_saved=True)
    original = window.engine.source_bytes

    class AcceptedCropDialog:
        scope = "current"
        margins_points = (20.0, 10.0, 30.0, 40.0)

        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self) -> int:
            return 1

    monkeypatch.setattr("openpdf_editor.main_window.PageCropDialog", AcceptedCropDialog)

    window.crop_pages()
    assert window.engine.page_rect(0).width == pytest.approx(370)
    assert window.engine.page_rect(0).height == pytest.approx(250)
    assert window.has_unsaved_changes
    window.undo()
    assert window.engine.source_bytes == original
    assert window.engine.page_rect(0).width == pytest.approx(420)

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
