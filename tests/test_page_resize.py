import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from openpdf_editor.dialogs import PageResizeDialog
from openpdf_editor.engine import PdfEngine
from openpdf_editor.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _source_pdf(*, rotated: bool = False) -> bytes:
    document = pymupdf.open()
    first = document.new_page(width=400, height=300)
    first.insert_text((100, 150), "CENTER", fontsize=20)
    second = document.new_page(width=500, height=360)
    second.insert_text((60, 70), "TARGET", fontsize=16)
    first = document[0]
    first.insert_link(
        {
            "kind": pymupdf.LINK_GOTO,
            "from": pymupdf.Rect(90, 120, 210, 165),
            "page": 1,
            "to": pymupdf.Point(60, 70),
        }
    )
    first.add_text_annot((250, 100), "Resize me")
    first.add_ink_annot([[(40, 40), (70, 55), (100, 45)]])
    widget = pymupdf.Widget()
    widget.field_name = "resize_field"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(80, 200, 220, 235)
    first.add_widget(widget)
    document.set_toc(
        [[
            1,
            "Target",
            2,
            {
                "kind": pymupdf.LINK_GOTO,
                "page": 1,
                "to": pymupdf.Point(60, 70),
                "zoom": 0.0,
            },
        ]]
    )
    if rotated:
        first.set_rotation(90)
    payload = document.tobytes()
    document.close()
    return payload


def test_fit_resize_scales_content_and_preserves_interactive_geometry() -> None:
    engine = PdfEngine()
    engine.load_bytes(_source_pdf())

    resized = engine.bytes_with_pages_resized([0, 1], 600, 600, "fit")

    with pymupdf.open(stream=resized, filetype="pdf") as document:
        first = document[0]
        assert first.rect == pymupdf.Rect(0, 0, 600, 600)
        assert document[1].rect == pymupdf.Rect(0, 0, 600, 600)
        center = first.search_for("CENTER")[0]
        assert center.x0 == pytest.approx(150, abs=1)
        assert center.y0 == pytest.approx(267.75, abs=1)
        assert center.width > 120
        widget = next(first.widgets())
        assert widget.rect.x0 == pytest.approx(120, abs=1)
        assert widget.rect.y0 == pytest.approx(375, abs=1)
        annotations = list(first.annots())
        assert annotations[0].rect.x0 > 370
        assert annotations[1].vertices[0][0][0] == pytest.approx(60, abs=1)
        link = first.get_links()[0]
        assert link["from"].x0 == pytest.approx(135, abs=1)
        assert link["to"].x > 70
        toc = document.get_toc(simple=False)
        assert toc[0][3]["to"].x == pytest.approx(72, abs=1)
        assert toc[0][3]["to"].y == pytest.approx(168, abs=1)


def test_canvas_resize_preserves_visual_content_size_and_centres_it() -> None:
    engine = PdfEngine()
    engine.load_bytes(_source_pdf())
    with pymupdf.open(stream=engine.source_bytes, filetype="pdf") as original:
        original_hit = original[0].search_for("CENTER")[0]

    resized = engine.bytes_with_pages_resized([0], 600, 600, "canvas")

    with pymupdf.open(stream=resized, filetype="pdf") as document:
        hit = document[0].search_for("CENTER")[0]
        assert document[0].rect == pymupdf.Rect(0, 0, 600, 600)
        assert hit.width == pytest.approx(original_hit.width, abs=0.2)
        assert hit.height == pytest.approx(original_hit.height, abs=0.2)
        assert hit.x0 == pytest.approx(original_hit.x0 + 100, abs=0.2)
        assert hit.y0 == pytest.approx(original_hit.y0 + 150, abs=0.2)
        assert document[1].rect == pymupdf.Rect(0, 0, 500, 360)


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
def test_resize_preserves_visible_orientation_of_rotated_pages(rotation: int) -> None:
    document = pymupdf.open()
    page = document.new_page(width=400, height=300)
    page.insert_text((100, 150), "ROTATED", fontsize=20)
    page.set_rotation(rotation)
    payload = document.tobytes()
    before_pixmap = page.get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5), alpha=False)
    document.close()
    engine = PdfEngine()
    engine.load_bytes(payload)

    resized = engine.bytes_with_pages_resized([0], 600, 600, "fit")

    with pymupdf.open(stream=resized, filetype="pdf") as result:
        assert result[0].rotation == 0
        assert result[0].rect == pymupdf.Rect(0, 0, 600, 600)
        assert result[0].search_for("ROTATED")
        after_pixmap = result[0].get_pixmap(
            matrix=pymupdf.Matrix(0.5, 0.5), alpha=False
        )
        assert before_pixmap.width <= after_pixmap.width
        assert before_pixmap.height <= after_pixmap.height


def test_resize_does_not_mutate_shared_page_content_streams() -> None:
    source = pymupdf.open()
    page = source.new_page(width=400, height=300)
    page.insert_text((100, 150), "SHARED", fontsize=20)
    source.fullcopy_page(0)
    payload = source.tobytes()
    source.close()
    engine = PdfEngine()
    engine.load_bytes(payload)

    resized = engine.bytes_with_pages_resized([0], 600, 600, "fit")

    with pymupdf.open(stream=resized, filetype="pdf") as document:
        assert document[0].search_for("SHARED")[0].x0 == pytest.approx(150, abs=1)
        assert document[1].search_for("SHARED")[0].x0 == pytest.approx(100, abs=1)
        assert document[1].rect == pymupdf.Rect(0, 0, 400, 300)


def test_resize_normalizes_nonstandard_pdf_user_unit() -> None:
    document = pymupdf.open()
    page = document.new_page(width=400, height=300)
    page.insert_text((100, 150), "USER UNIT")
    document.xref_set_key(page.xref, "UserUnit", "2")
    payload = document.tobytes()
    document.close()
    engine = PdfEngine()
    engine.load_bytes(payload)

    resized = engine.bytes_with_pages_resized([0], 600, 600, "fit")

    with pymupdf.open(stream=resized, filetype="pdf") as result:
        assert result[0].rect == pymupdf.Rect(0, 0, 600, 600)
        assert result.xref_get_key(result[0].xref, "UserUnit") == ("int", "1")
        assert result[0].search_for("USER UNIT")


def test_resize_rejects_invalid_dimensions_and_mode() -> None:
    engine = PdfEngine()
    engine.load_bytes(_source_pdf())
    with pytest.raises(ValueError, match="dimensions"):
        engine.bytes_with_pages_resized([0], 20, 300, "fit")
    with pytest.raises(ValueError, match="Unknown"):
        engine.bytes_with_pages_resized([0], 600, 600, "stretch")


def test_resize_dialog_defaults_to_fit_and_selected_pages() -> None:
    app = _application()
    dialog = PageResizeDialog((420, 300), 3, 8)
    assert dialog.resize_mode == "fit"
    assert dialog.scope == "selected"
    width, height = dialog.target_dimensions_points
    assert width == pytest.approx(420, abs=0.2)
    assert height == pytest.approx(300, abs=0.2)

    dialog.page_size_box.setCurrentIndex(1)  # A4
    app.processEvents()
    width, height = dialog.target_dimensions_points
    assert width == pytest.approx(297 * 72 / 25.4)
    assert height == pytest.approx(210 * 72 / 25.4)
    dialog.orientation_box.setCurrentIndex(0)
    width, height = dialog.target_dimensions_points
    assert width == pytest.approx(210 * 72 / 25.4)
    assert height == pytest.approx(297 * 72 / 25.4)
    assert "3" in dialog.result_label.text()
    dialog.buttons.button(QDialogButtonBox.Apply).click()
    assert dialog.result() == QDialog.Accepted


def test_main_window_resize_supports_undo(tmp_path: Path, monkeypatch) -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(_source_pdf())
    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, tmp_path / "pages.pdf", already_saved=True)
    original = window.engine.source_bytes

    class AcceptedResizeDialog:
        scope = "current"
        resize_mode = "fit"
        target_dimensions_points = (600.0, 600.0)

        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self) -> int:
            return 1

    monkeypatch.setattr(
        "openpdf_editor.main_window.PageResizeDialog", AcceptedResizeDialog
    )

    window.resize_pages()
    assert window.engine.page_rect(0) == pymupdf.Rect(0, 0, 600, 600)
    assert window.has_unsaved_changes
    window.undo()
    assert window.engine.source_bytes == original
    assert window.engine.page_rect(0) == pymupdf.Rect(0, 0, 400, 300)

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
