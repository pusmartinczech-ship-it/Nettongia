import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import CompressionResult, PdfEngine, TextPlacement
from openpdf_editor.main_window import MainWindow


def _application() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("OpenPDF Editor Tests")
    app.setApplicationName("OpenPDF Editor Tests")
    return app


def _wait_until(app: QApplication, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
        time.sleep(0.005)
    assert predicate()


def _window_with_text(text: str) -> MainWindow:
    window = MainWindow()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(595, 842, 1))
    window._activate_document(engine, Path("background-source.pdf"), already_saved=True)
    window._cancel_document_inspection()
    state = window._capture_state()
    state.inserted_texts.append(
        TextPlacement(
            key="first",
            page_index=0,
            bbox=(72, 72, 360, 130),
            text=text,
            font_size=20,
        )
    )
    window._push_state(state, 0)
    return window


def test_background_save_keeps_ui_responsive_and_preserves_newer_edits(
    tmp_path: Path,
) -> None:
    app = _application()
    window = _window_with_text("Snapshot before background save")
    output = tmp_path / "background-saved.pdf"
    assert window._start_document_write(output)
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    assert window._write_process is not None
    assert not window.save_action.isEnabled()
    assert window.add_text_action.isEnabled()
    assert not window.close_document()

    newer = window._capture_state()
    newer.inserted_texts.append(
        TextPlacement(
            key="second",
            page_index=0,
            bbox=(72, 160, 360, 220),
            text="Newer edit while saving",
            font_size=20,
        )
    )
    window._push_state(newer, 0)
    _wait_until(app, lambda: window._write_process is None)

    assert heartbeat == [True]
    assert output.is_file()
    with pymupdf.open(output) as saved:
        text = "".join(page.get_text() for page in saved)
    normalized_text = " ".join(text.split())
    assert "Snapshot before background save" in normalized_text
    assert "Newer edit while saving" not in text
    assert window.has_unsaved_changes
    assert window.saved_history_index is None
    assert window.save_target_path == output.absolute()
    assert window.save_action.isEnabled()

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_background_save_marks_unchanged_snapshot_as_saved(tmp_path: Path) -> None:
    app = _application()
    window = _window_with_text("Completed snapshot")
    output = tmp_path / "completed.pdf"

    assert window._start_document_write(output)
    _wait_until(app, lambda: window._write_process is None)

    assert output.is_file()
    assert not window.has_unsaved_changes
    assert window.saved_history_index == window.history_index
    assert window.document_path == output.absolute()
    assert window._write_progress is None

    window.close()
    window.deleteLater()
    app.processEvents()


def test_save_copy_preserves_active_identity_and_unsaved_marker(tmp_path: Path) -> None:
    app = _application()
    window = _window_with_text("Independent safety copy")
    output = tmp_path / "safety-copy.pdf"
    original_path = window.document_path
    original_target = window.save_target_path
    original_saved_index = window.saved_history_index

    assert window.has_unsaved_changes
    assert window._start_document_write(output, update_document_identity=False)
    _wait_until(app, lambda: window._write_process is None)

    assert output.is_file()
    with pymupdf.open(output) as saved:
        assert "Independent safety copy" in " ".join(saved[0].get_text().split())
    assert window.document_path == original_path
    assert window.save_target_path == original_target
    assert window.saved_history_index == original_saved_index
    assert window.has_unsaved_changes

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_background_lossless_compression_returns_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _application()
    window = _window_with_text("Compressed snapshot")
    output = tmp_path / "compressed.pdf"
    results: list[tuple[Path, CompressionResult]] = []
    monkeypatch.setattr(
        window,
        "_show_compression_result",
        lambda path, result: results.append((path, result)),
    )

    assert window._start_document_write(output, compression_profile="lossless")
    _wait_until(app, lambda: window._write_process is None)

    assert output.is_file()
    assert len(results) == 1
    assert results[0][0] == output.absolute()
    assert results[0][1].output_size == output.stat().st_size
    assert window.has_unsaved_changes

    monkeypatch.setattr(window, "_maybe_save_changes", lambda: True)
    window.close()
    window.deleteLater()
    app.processEvents()


def test_background_write_can_be_cancelled_safely(tmp_path: Path) -> None:
    app = _application()
    window = _window_with_text("Cancelled snapshot")
    output = tmp_path / "cancelled.pdf"

    assert window._start_document_write(output)
    assert window._write_process is not None
    window._cancel_document_write()
    _wait_until(app, lambda: window._write_process is None)

    assert window.has_unsaved_changes
    assert window.document_path == Path("background-source.pdf")
    assert window.save_target_path is None
    assert window._write_progress is None
    assert window.save_action.isEnabled()

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
