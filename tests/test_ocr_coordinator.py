import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import PdfEngine
from openpdf_editor.main_window import MainWindow
from openpdf_editor.ocr_coordinator import OcrContext, OcrCoordinator, OcrOutcome
from openpdf_editor.ocr_worker import available_ocr_languages


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(app: QApplication, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
        time.sleep(0.005)
    assert predicate()


def _searchable_pdf() -> bytes:
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300, 1))
    document = engine.build_document()
    try:
        document[0].insert_text((50, 80), "Existing searchable text")
        return document.tobytes()
    finally:
        document.close()
        engine.close()


def test_coordinator_returns_context_and_cleans_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    languages = available_ocr_languages()
    if not languages:
        pytest.skip("Tesseract language data is unavailable")
    app = _application()
    workspace = tmp_path / "ocr-workspace"
    monkeypatch.setattr(
        "openpdf_editor.ocr_coordinator.tempfile.mkdtemp",
        lambda **_kwargs: str(workspace),
    )
    context = OcrContext(document_generation=4, content_revision=9)
    outcomes: list[OcrOutcome] = []
    coordinator = OcrCoordinator()
    coordinator.completed.connect(outcomes.append)

    coordinator.start(
        _searchable_pdf(),
        (0,),
        next(iter(languages)),
        context=context,
    )

    assert coordinator.is_running
    assert coordinator.process is not None
    _wait_until(app, lambda: not coordinator.is_running)
    assert len(outcomes) == 1
    assert outcomes[0].context == context
    assert outcomes[0].error is None
    assert outcomes[0].result is not None
    assert outcomes[0].result["processed_pages"] == 0
    assert outcomes[0].output_bytes is None
    assert not workspace.exists()


def test_coordinator_cleans_workspace_when_preparation_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "failed-ocr-workspace"
    monkeypatch.setattr(
        "openpdf_editor.ocr_coordinator.tempfile.mkdtemp",
        lambda **_kwargs: str(workspace),
    )
    coordinator = OcrCoordinator()

    try:
        coordinator.start(
            PdfEngine.blank_document_bytes(200, 300, 1),
            (0,),
            "invalid-language!",
            context=OcrContext(1, 1),
        )
    except ValueError as exc:
        assert "language" in str(exc).lower()
    else:
        raise AssertionError("Invalid OCR job was accepted.")

    assert not coordinator.is_running
    assert not workspace.exists()


def test_coordinator_cancel_kills_job_and_cleans_unicode_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _application()
    workspace = tmp_path / "Zrušená OCR úloha – žluťoučký kůň"
    monkeypatch.setattr(
        "openpdf_editor.ocr_coordinator.tempfile.mkdtemp",
        lambda **_kwargs: str(workspace),
    )
    outcomes: list[OcrOutcome] = []
    coordinator = OcrCoordinator()
    coordinator.completed.connect(outcomes.append)

    coordinator.start(
        PdfEngine.blank_document_bytes(1200, 1200, 40),
        tuple(range(40)),
        "eng",
        context=OcrContext(5, 8),
        dpi=300,
    )
    assert coordinator.is_running
    assert coordinator.cancel()
    app.processEvents(QEventLoop.AllEvents, 50)

    assert not coordinator.is_running
    assert not workspace.exists()
    assert not outcomes
    assert not coordinator.cancel()


def test_window_discards_ocr_output_from_an_old_revision() -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(200, 300, 1))
    window = MainWindow()
    window._activate_document(engine, None, already_saved=True)
    window._cancel_document_inspection()
    original = window.engine.source_bytes
    stale_context = OcrContext(
        window._document_generation,
        window._content_revision - 1,
    )

    window._ocr_finished(
        OcrOutcome(
            context=stale_context,
            result={
                "processed_pages": 1,
                "skipped_pages": 0,
                "words_inserted": 1,
                "output_size": len(original),
            },
            output_bytes=original,
        )
    )

    assert window.engine.source_bytes == original
    assert window.history_index == 0
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
