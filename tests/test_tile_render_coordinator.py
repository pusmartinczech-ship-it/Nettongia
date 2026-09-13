import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import PdfEngine
from openpdf_editor.main_window import MainWindow
from openpdf_editor.tile_render_coordinator import (
    TileRenderCoordinator,
    TileRenderOutcome,
)


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(app: QApplication, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
        time.sleep(0.005)
    assert predicate()


def test_coordinator_returns_context_and_cleans_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _application()
    source = tmp_path / "source.pdf"
    source.write_bytes(PdfEngine.blank_document_bytes(420, 300, 1))
    workspace = tmp_path / "tile-workspace"
    monkeypatch.setattr(
        "openpdf_editor.tile_render_coordinator.tempfile.mkdtemp",
        lambda **_kwargs: str(workspace),
    )
    context = (3, 7, 0, 2.0, 1.0)
    outcomes: list[TileRenderOutcome] = []
    coordinator = TileRenderCoordinator()
    coordinator.completed.connect(outcomes.append)

    coordinator.start(
        source,
        0,
        2.0,
        ((0, 0, 400, 300),),
        context=context,
    )

    assert coordinator.is_running
    assert coordinator.process is not None
    _wait_until(app, lambda: not coordinator.is_running)
    assert len(outcomes) == 1
    assert outcomes[0].context == context
    assert outcomes[0].error is None
    assert len(outcomes[0].tiles) == 1
    assert not workspace.exists()


def test_coordinator_cleans_workspace_when_preparation_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "failed-tile-workspace"
    monkeypatch.setattr(
        "openpdf_editor.tile_render_coordinator.tempfile.mkdtemp",
        lambda **_kwargs: str(workspace),
    )
    coordinator = TileRenderCoordinator()

    try:
        coordinator.start(
            tmp_path / "missing.pdf",
            0,
            2.0,
            ((0, 0, 100, 100),),
            context=(1, 1, 0, 2.0, 1.0),
        )
    except ValueError as exc:
        assert "source" in str(exc).lower()
    else:
        raise AssertionError("Invalid tile-render job was accepted.")

    assert not coordinator.is_running
    assert not workspace.exists()


def test_window_discards_tiles_from_an_old_render_context() -> None:
    app = _application()
    window = MainWindow()
    active_context = (4, 9, 0, 2.0, 1.0)
    window._tile_context = active_context

    window._tile_render_completed(
        TileRenderOutcome(context=(4, 8, 0, 2.0, 1.0))
    )

    assert window._tile_context == active_context
    assert not window._tile_cache
    window.deleteLater()
    app.processEvents()
