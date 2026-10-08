"""End-to-end checks for page selection, import, and export."""

import pymupdf
import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog

from openpdf_editor.engine import PdfEngine, TextPlacement
from openpdf_editor.main_window import MainWindow


def _sample_pdf(count: int) -> bytes:
    document = pymupdf.open()
    try:
        for index in range(count):
            document.new_page().insert_text((40, 40), f"Original page {index + 1}")
        return document.tobytes()
    finally:
        document.close()


def test_page_ranges_import_and_invalid_ranges(tmp_path) -> None:
    source = tmp_path / "other.pdf"
    source.write_bytes(_sample_pdf(5))
    engine = PdfEngine()
    engine.load_bytes(_sample_pdf(2))
    try:
        combined, count = engine.bytes_with_pdf_inserted(0, source, page_spec="2,4-5,4")
        assert count == 3
        with pymupdf.open(stream=combined, filetype="pdf") as pdf:
            assert ["Original page " + str(n) in pdf[i].get_text() for i, n in enumerate((1, 2, 4, 5, 2))] == [True] * 5
        for invalid in ("", "0", "2-1", "6", "1,,2", "foo", "1-6"):
            with pytest.raises(ValueError):
                engine.bytes_with_pdf_inserted(0, source, page_spec=invalid)
    finally:
        engine.close()


def test_export_selected_pages_includes_unsaved_content_and_preserves_active_pdf(tmp_path) -> None:
    engine = PdfEngine()
    original = _sample_pdf(4)
    engine.load_bytes(original)
    output = tmp_path / "selected.pdf"
    try:
        engine.save_page_selection(
            output, [0, 2],
            inserted_texts=[TextPlacement("pending", 2, (40, 80, 200, 110), "UNSAVED EDIT")],
        )
        with pymupdf.open(output) as pdf:
            assert pdf.page_count == 2
            assert "Original page 1" in pdf[0].get_text()
            assert "Original page 3" in pdf[1].get_text()
            assert "UNSAVED EDIT" in pdf[1].get_text()
        assert engine.source_bytes == original
        with pytest.raises(ValueError):
            engine.save_page_selection(output, [0, 0])
        with pymupdf.open(output) as pdf:
            assert pdf.page_count == 2
    finally:
        engine.close()


def test_split_refuses_existing_output_without_writing_any_part(tmp_path) -> None:
    engine = PdfEngine()
    engine.load_bytes(_sample_pdf(3))
    occupied = tmp_path / "part_2.pdf"
    occupied.write_bytes(b"original data")
    try:
        with pytest.raises(FileExistsError):
            engine.save_page_groups([
                (tmp_path / "part_1.pdf", [0]),
                (occupied, [1, 2]),
            ])
        assert occupied.read_bytes() == b"original data"
        assert not (tmp_path / "part_1.pdf").exists()
    finally:
        engine.close()


def test_thumbnail_multiselection_exports_and_split_creates_numbered_parts(tmp_path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    engine = PdfEngine()
    engine.load_bytes(_sample_pdf(4))
    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, None, already_saved=True)
    selected = window.page_list.selectionModel()
    selected.select(window.page_list.model().index(0, 0), QItemSelectionModel.ClearAndSelect)
    selected.select(window.page_list.model().index(2, 0), QItemSelectionModel.Select)
    assert window._selected_page_indices() == [0, 2]
    assert not window.page_list.dragEnabled()
    exported = tmp_path / "selected.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kw: (str(exported), ""))
    window.extract_selected_pages()
    with pymupdf.open(exported) as pdf:
        assert pdf.page_count == 2
        assert "Original page 3" in pdf[1].get_text()
    monkeypatch.setattr(QInputDialog, "getInt", lambda *args, **kw: (2, True))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kw: str(tmp_path))
    window.split_document()
    for filename, expected in (("document_pages_1-2.pdf", 1), ("document_pages_3-4.pdf", 3)):
        with pymupdf.open(tmp_path / filename) as pdf:
            assert pdf.page_count == 2
            assert f"Original page {expected}" in pdf[0].get_text()
    assert window.engine.page_count == 4
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
