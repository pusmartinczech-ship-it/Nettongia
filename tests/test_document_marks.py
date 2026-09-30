import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from openpdf_editor.dialogs import DocumentMarksDialog
from openpdf_editor.engine import DocumentMarksSpec, PdfEngine
from openpdf_editor.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _source_pdf(page_count: int = 3) -> bytes:
    document = pymupdf.open()
    for number in range(1, page_count + 1):
        page = document.new_page(width=420, height=300)
        page.insert_text((50, 90), f"Original page {number}", fontsize=18)
    payload = document.tobytes()
    document.close()
    return payload


def test_document_marks_expand_tokens_and_respect_page_scope() -> None:
    engine = PdfEngine()
    engine.load_bytes(_source_pdf())
    marked = engine.bytes_with_document_marks(
        DocumentMarksSpec(
            header_left="{title}",
            footer_center="{page} / {pages}",
            watermark_text="DŮVĚRNÉ",
            page_mode="odd",
            skip_first_page=True,
            document_title="Český dokument",
        )
    )
    engine.load_bytes(marked)

    assert engine.has_document_marks()
    with pymupdf.open(stream=marked, filetype="pdf") as document:
        assert document[0].get_text().strip() == "Original page 1"
        assert document[1].get_text().strip() == "Original page 2"
        page_three = document[2].get_text()
        assert "Original page 3" in page_three
        assert "Český dokument" in page_three.replace("\u00a0", " ")
        assert "3 / 3" in page_three
        assert document[2].get_images(full=True)


def test_reapplying_and_removing_document_marks_preserves_original_content() -> None:
    source = _source_pdf(1)
    engine = PdfEngine()
    engine.load_bytes(source)
    first = engine.bytes_with_document_marks(
        DocumentMarksSpec(header_center="FIRST", watermark_text="OLD")
    )
    engine.load_bytes(first)
    second = engine.bytes_with_document_marks(
        DocumentMarksSpec(header_center="SECOND", footer_right="{page}")
    )
    engine.load_bytes(second)

    with pymupdf.open(stream=second, filetype="pdf") as document:
        text = document[0].get_text()
        assert "FIRST" not in text
        assert "SECOND" in text
        assert "Original page 1" in text

    cleaned = engine.bytes_without_document_marks()
    engine.load_bytes(cleaned)
    assert not engine.has_document_marks()
    with pymupdf.open(stream=cleaned, filetype="pdf") as document:
        assert document[0].get_text().strip() == "Original page 1"
        assert not document[0].get_images(full=True)


def test_document_marks_support_rotated_pages_and_reject_empty_content() -> None:
    engine = PdfEngine()
    engine.load_bytes(_source_pdf(1))
    engine.load_bytes(engine.bytes_with_page_rotated(0, 1))
    marked = engine.bytes_with_document_marks(
        DocumentMarksSpec(header_right="ROTATED {page}", watermark_text="DRAFT")
    )
    with pymupdf.open(stream=marked, filetype="pdf") as document:
        assert document[0].rotation == 90
        assert "ROTATED 1" in document[0].get_text()
        assert document[0].get_images(full=True)

    engine.load_bytes(_source_pdf(1))
    with pytest.raises(ValueError, match="header, footer, or watermark"):
        engine.bytes_with_document_marks(DocumentMarksSpec())

    bounded = engine.bytes_with_document_marks(
        DocumentMarksSpec(watermark_text="W" * 250, watermark_font_size=240)
    )
    with pymupdf.open(stream=bounded, filetype="pdf") as document:
        assert document[0].get_images(full=True)


def test_document_marks_dialog_provides_live_preview_and_spec() -> None:
    app = _application()
    dialog = DocumentMarksDialog("Proposal", True)
    dialog.header_left.setText("{title}")
    dialog.watermark_text.setText("DRAFT")
    dialog.watermark_opacity.setValue(25)
    app.processEvents()

    spec = dialog.marks_spec()
    assert spec.header_left == "{title}"
    assert spec.document_title == "Proposal"
    assert spec.watermark_text == "DRAFT"
    assert spec.watermark_opacity == 0.25
    assert dialog.preview.spec == spec
    dialog.buttons.button(QDialogButtonBox.Apply).click()
    assert dialog.result() == QDialog.Accepted


def test_main_window_document_marks_support_undo(tmp_path: Path, monkeypatch) -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(_source_pdf(1))
    window = MainWindow()
    window._activate_document(engine, tmp_path / "proposal.pdf", already_saved=True)
    window._cancel_document_inspection()
    original = window.engine.source_bytes
    spec = DocumentMarksSpec(
        header_left="{title}", footer_center="{page} / {pages}"
    )
    monkeypatch.setattr(
        "openpdf_editor.main_window.DocumentMarksDialog.exec", lambda _dialog: 1
    )
    monkeypatch.setattr(
        "openpdf_editor.main_window.DocumentMarksDialog.marks_spec",
        lambda _dialog: spec,
    )

    window.manage_document_marks()
    assert window.engine.has_document_marks()
    assert window.has_unsaved_changes
    window.undo()
    assert window.engine.source_bytes == original
    assert not window.engine.has_document_marks()

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
