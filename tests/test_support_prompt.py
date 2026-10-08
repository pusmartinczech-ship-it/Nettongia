import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import PdfEngine, TextPlacement
from openpdf_editor.main_window import MainWindow
from openpdf_editor.support_prompt import (
    FIRST_PROMPT_SAVE_COUNT,
    REMINDER_SAVE_INTERVAL,
    SUPPORT_URL,
    disable_support_prompt,
    read_support_prompt_state,
    record_successful_save,
)


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _settings(path: Path) -> QSettings:
    return QSettings(str(path), QSettings.IniFormat)


def test_support_prompt_is_due_after_five_saves_then_waits_ten_more(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "support.ini")

    for _ in range(FIRST_PROMPT_SAVE_COUNT - 1):
        state, due = record_successful_save(settings)
        assert not due
    state, due = record_successful_save(settings)
    assert due
    assert state.successful_saves == FIRST_PROMPT_SAVE_COUNT
    assert state.next_prompt_at == FIRST_PROMPT_SAVE_COUNT + REMINDER_SAVE_INTERVAL

    for _ in range(REMINDER_SAVE_INTERVAL - 1):
        _state, due = record_successful_save(settings)
        assert not due
    _state, due = record_successful_save(settings)
    assert due


def test_support_prompt_can_be_disabled_without_stopping_local_save_count(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "disabled.ini")
    settings.setValue("support/successful_saves", FIRST_PROMPT_SAVE_COUNT - 1)
    disable_support_prompt(settings)

    state, due = record_successful_save(settings)

    assert not due
    assert state.disabled
    assert state.successful_saves == FIRST_PROMPT_SAVE_COUNT
    assert read_support_prompt_state(settings).disabled


def test_only_changed_normal_document_saves_count_toward_prompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _application()
    settings = _settings(tmp_path / "window.ini")
    window = MainWindow(settings=settings)
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300, 1))
    window._activate_document(
        engine, tmp_path / "source.pdf", already_saved=True
    )
    window._cancel_document_inspection()
    recorded = []
    monkeypatch.setattr(
        window,
        "_record_successful_save_for_support",
        lambda: recorded.append(True),
    )

    state = window._capture_state()
    state.inserted_texts.append(
        TextPlacement("new", 0, (40, 40, 250, 90), "Useful edit")
    )
    window._push_state(state, 0)
    assert window._save_to_path(tmp_path / "saved.pdf", show_confirmation=False)
    assert recorded == [True]

    assert window._save_to_path(tmp_path / "saved-again.pdf", show_confirmation=False)
    assert recorded == [True]

    window.close()
    window.deleteLater()


def test_support_choice_is_permanent_and_opens_only_approved_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _application()
    settings = _settings(tmp_path / "choice.ini")
    window = MainWindow(settings=settings)
    opened = []
    monkeypatch.setattr(
        "openpdf_editor.main_window.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()) or True,
    )

    window._handle_support_prompt_choice("support")

    assert opened == [SUPPORT_URL]
    assert read_support_prompt_state(settings).disabled
    window.close()
    window.deleteLater()


def test_due_prompt_is_queued_but_never_shown_at_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _application()
    settings = _settings(tmp_path / "queue.ini")
    settings.setValue("support/successful_saves", FIRST_PROMPT_SAVE_COUNT - 1)
    window = MainWindow(settings=settings)
    callbacks = []
    monkeypatch.setattr(
        "openpdf_editor.main_window.QTimer.singleShot",
        lambda _delay, callback: callbacks.append(callback),
    )

    assert not window._support_prompt_pending
    window._record_successful_save_for_support()

    assert window._support_prompt_pending
    assert callbacks == [window._show_support_prompt_if_available]
    window.close()
    window.deleteLater()


def test_application_uses_the_same_approved_support_url_as_website() -> None:
    root = Path(__file__).resolve().parents[1]
    assert SUPPORT_URL in (root / "website" / "check_site.py").read_text(
        encoding="utf-8"
    )
    assert SUPPORT_URL in (root / "website" / "index.html").read_text(
        encoding="utf-8"
    )
