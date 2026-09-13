import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from openpdf_editor.document_session import DocumentWriteContext
from openpdf_editor.document_write_coordinator import (
    DocumentWriteCoordinator,
    DocumentWriteOutcome,
)
from openpdf_editor.engine import PdfEngine
from openpdf_editor.recovery import RecoverySnapshot


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _snapshot() -> RecoverySnapshot:
    return RecoverySnapshot(
        pdf_bytes=PdfEngine.blank_document_bytes(200, 300, 1),
        edits=(),
        inserted_texts=(),
        signatures=(),
        inserted_images=(),
        deleted_images=(),
        document_path=None,
        save_target_path=None,
        current_page=0,
        render_scale=1.0,
    )


def _wait_until(app: QApplication, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
        time.sleep(0.005)
    assert predicate()


def test_coordinator_owns_process_and_cleans_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _application()
    workspace = tmp_path / "write-workspace"
    monkeypatch.setattr(
        "openpdf_editor.document_write_coordinator.tempfile.mkdtemp",
        lambda **_kwargs: str(workspace),
    )
    output = tmp_path / "coordinated.pdf"
    context = DocumentWriteContext(
        path=output,
        document_generation=3,
        content_revision=7,
    )
    outcomes: list[DocumentWriteOutcome] = []
    coordinator = DocumentWriteCoordinator()
    coordinator.completed.connect(outcomes.append)

    coordinator.start(_snapshot(), context)

    assert coordinator.is_running
    assert coordinator.process is not None
    _wait_until(app, lambda: not coordinator.is_running)
    assert output.is_file()
    assert outcomes == [DocumentWriteOutcome(context)]
    assert not workspace.exists()


def test_coordinator_cleans_workspace_when_job_preparation_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "failed-workspace"
    monkeypatch.setattr(
        "openpdf_editor.document_write_coordinator.tempfile.mkdtemp",
        lambda **_kwargs: str(workspace),
    )
    coordinator = DocumentWriteCoordinator()
    context = DocumentWriteContext(
        path=tmp_path / "output.pdf",
        document_generation=1,
        content_revision=1,
        compression_profile="invalid",
    )

    try:
        coordinator.start(_snapshot(), context)
    except ValueError as exc:
        assert "profile" in str(exc).lower()
    else:
        raise AssertionError("Invalid write job was accepted.")

    assert not coordinator.is_running
    assert not workspace.exists()
