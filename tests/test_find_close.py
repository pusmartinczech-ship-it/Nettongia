import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtCore import QEventLoop, QSettings
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import PdfEngine, TextPlacement
import openpdf_editor.main_window as main_window_module
from openpdf_editor.main_window import MainWindow


def _application() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("OpenPDF Editor Tests")
    app.setApplicationName("OpenPDF Editor Tests")
    return app


def _search_document() -> bytes:
    document = pymupdf.open()
    for text in ("Alpha beta test", "Second Alpha result"):
        page = document.new_page(width=420, height=300)
        page.insert_text((60, 80), text, fontsize=18)
    try:
        return document.tobytes()
    finally:
        document.close()


def _protected_document(password: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=420, height=300)
    page.insert_text((60, 80), "Password dialog test", fontsize=18)
    try:
        return document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw=password,
        )
    finally:
        document.close()


def test_open_pdf_reprompts_after_incorrect_password(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _application()
    source = tmp_path / "protected.pdf"
    source.write_bytes(_protected_document("correct-password"))
    answers = iter((("incorrect", True), ("correct-password", True)))
    prompts: list[str] = []

    def password_dialog(_parent, _title, prompt, _mode):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr(
        main_window_module.QInputDialog,
        "getText",
        password_dialog,
    )
    window = MainWindow()
    window._maybe_save_changes = lambda: True

    assert window.open_pdf(str(source))
    assert window.engine.was_encrypted
    assert len(prompts) == 2
    assert prompts[0] == window.trx("pdf_password_prompt")
    assert prompts[1] == window.trx("pdf_password_incorrect")
    assert "Password dialog test" in window.engine.text_runs(0)[0].text

    window.close()
    window.deleteLater()
    app.processEvents()


def _wait_for_search(app: QApplication, window: MainWindow) -> None:
    deadline = time.monotonic() + 3
    while window._search_task is not None and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 20)
    assert window._search_task is None


def _wait_for_write(app: QApplication, window: MainWindow) -> None:
    deadline = time.monotonic() + 5
    while window._write_process is not None and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 20)
        time.sleep(0.005)
    assert window._write_process is None


def test_find_navigates_pages_and_searches_unsaved_text() -> None:
    app = _application()
    window = MainWindow()
    engine = PdfEngine()
    engine.load_bytes(_search_document())
    window._activate_document(engine, Path("search-test.pdf"), already_saved=True)
    window.inserted_texts = [
        TextPlacement(
            key="unsaved-search-text",
            page_index=1,
            bbox=(60, 120, 340, 160),
            text="Alpha unsaved addition",
            font_size=16,
        )
    ]
    window.show()
    app.processEvents()

    window.show_find_bar()
    window.find_edit.setText("Alpha")
    window._search_timer.stop()
    window._run_search()
    _wait_for_search(app, window)
    app.processEvents()

    assert window.find_bar.isVisible()
    assert len(window.search_matches) == 3
    assert window.current_page == 0
    assert window.find_result_label.text() == "1 / 3"
    assert window.page_view._search_highlight_item is not None

    window.find_next()
    app.processEvents()
    assert window.current_page == 1
    assert window.find_result_label.text() == "2 / 3"
    assert window.page_view._search_highlight_item is not None

    window.find_previous()
    app.processEvents()
    assert window.current_page == 0
    assert window.find_result_label.text() == "1 / 3"

    window.hide_find_bar()
    assert not window.find_bar.isVisible()
    assert window.page_view._search_highlight_item is None

    window.close()
    window.deleteLater()
    app.processEvents()


def test_close_document_can_be_cancelled_and_clears_workspace(monkeypatch) -> None:
    app = _application()
    window = MainWindow()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300))
    window._activate_document(engine, None, already_saved=False)

    monkeypatch.setattr(window, "_maybe_save_changes", lambda: False)
    assert not window.close_document()
    assert window.engine.is_open

    monkeypatch.setattr(window, "_maybe_save_changes", lambda: True)
    assert window.close_document()
    assert not window.engine.is_open
    assert window.page_list.count() == 0
    assert not window.page_view.scene().items()
    assert not window.close_document_action.isEnabled()
    assert not window.find_action.isEnabled()
    assert window.windowTitle() == "OpenPDF Editor"

    window.close()
    window.deleteLater()
    app.processEvents()


def test_standard_save_action_writes_to_the_established_target(tmp_path: Path) -> None:
    app = _application()
    window = MainWindow(
        recovery_path=tmp_path / "save-recovery",
        settings=QSettings(str(tmp_path / "save-settings.ini"), QSettings.IniFormat),
    )
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300))
    window._activate_document(engine, None, already_saved=False)
    window._cancel_document_inspection()
    target = tmp_path / "saved-document.pdf"
    window.save_target_path = target

    assert window.save_action.shortcut() == QKeySequence(QKeySequence.Save)
    assert window.save_as_action.shortcut() == QKeySequence(QKeySequence.SaveAs)
    window.save_action.trigger()
    _wait_for_write(app, window)

    assert target.is_file()
    assert window.document_path == target.absolute()
    assert not window.has_unsaved_changes

    window.close()
    window.deleteLater()
    app.processEvents()
