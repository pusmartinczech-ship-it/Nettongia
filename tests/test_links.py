import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import PdfEngine, TextEdit
from openpdf_editor.main_window import MainWindow


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
def test_link_roundtrip_preserves_area_and_page_content(rotation: int) -> None:
    source = pymupdf.open()
    page = source.new_page(width=300, height=200)
    page.insert_text((20, 60), "Keep this text")
    page.set_rotation(rotation)
    engine = PdfEngine()
    engine.load_bytes(source.tobytes())
    source.close()
    try:
        bbox = (10, 10, 90, 35)
        engine.load_bytes(engine.bytes_with_link(0, bbox, "https://example.org/a"))
        link = engine.page_links(0)[0]
        assert tuple(link["from"]) == pytest.approx(bbox)
        assert link["uri"] == "https://example.org/a"
        engine.load_bytes(engine.bytes_with_link(0, None, "mailto:hello@example.org", xref=link["xref"]))
        updated = engine.page_links(0)[0]
        assert tuple(updated["from"]) == pytest.approx(bbox)
        assert updated["uri"] == "mailto:hello@example.org"
        engine.load_bytes(engine.bytes_without_link(0, updated["xref"]))
        assert engine.page_links(0) == []
        assert "Keep this text" in engine.text_runs(0)[0].text
    finally:
        engine.close()


def test_link_context_menu_edit_and_remove_support_undo(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("Nettongia PDF Editor Tests")
    app.setApplicationName("Nettongia PDF Editor Tests")
    window = MainWindow()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(300, 200))
    window._activate_document(engine, Path("links.pdf"), already_saved=True)
    menu_actions = []

    def capture(menu, _position):
        menu_actions[:] = [action for action in menu.actions() if not action.isSeparator()]

    monkeypatch.setattr(window, "_exec_context_menu", capture)
    monkeypatch.setattr(window, "_ask_link_uri", lambda initial="": "https://example.org")
    try:
        window._show_canvas_context_menu(QPointF(20 * window.render_scale, 20 * window.render_scale), window.pos())
        assert [action.text() for action in menu_actions] == [window.trx("add_link")]
        menu_actions[0].trigger()
        assert window.engine.page_links(0)[0]["uri"] == "https://example.org"
        assert window.has_unsaved_changes
        window._show_canvas_context_menu(QPointF(20 * window.render_scale, 20 * window.render_scale), window.pos())
        assert [action.text() for action in menu_actions] == [window.trx("edit_link"), window.trx("remove_link")]
        monkeypatch.setattr(window, "_ask_link_uri", lambda initial="": "https://example.net/new")
        menu_actions[0].trigger()
        assert window.engine.page_links(0)[0]["uri"] == "https://example.net/new"
        window.undo()
        assert window.engine.page_links(0)[0]["uri"] == "https://example.org"
        window._show_canvas_context_menu(QPointF(20 * window.render_scale, 20 * window.render_scale), window.pos())
        menu_actions[1].trigger()
        assert window.engine.page_links(0) == []
        window.undo()
        assert window.engine.page_links(0)[0]["uri"] == "https://example.org"
    finally:
        window._maybe_save_changes = lambda: True
        window.close()
        window.deleteLater()
        app.processEvents()


def test_link_edit_after_pending_text_change_uses_remapped_pdf_object(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    document = pymupdf.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((20, 40), "Original")
    page.insert_link({
        "kind": pymupdf.LINK_URI, "from": pymupdf.Rect(20, 120, 100, 145),
        "uri": "https://before.example",
    })
    engine = PdfEngine()
    engine.load_bytes(document.tobytes())
    document.close()
    window = MainWindow()
    window._activate_document(engine, Path("pending-edit.pdf"), already_saved=True)
    run = engine.text_runs(0)[0]
    window.edits[run.key] = TextEdit(run=run, new_text="Replaced", font_size=run.font_size)
    monkeypatch.setattr(window, "_ask_link_uri", lambda initial="": "https://after.example")
    try:
        original = engine.page_links(0)[0]
        window._edit_link(0, original["xref"], original["uri"], index=0)
        assert window.engine.page_links(0)[0]["uri"] == "https://after.example"
        assert "Replaced" in window.engine.text_runs(0)[0].text
    finally:
        window._maybe_save_changes = lambda: True
        window.close()
        window.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("uri", ("javascript:alert(1)", "file:///secret", "https://", "mailto:x", ""))
def test_unsafe_or_incomplete_link_destinations_are_rejected(uri: str) -> None:
    with pytest.raises(ValueError):
        MainWindow._validated_link_uri(uri)
