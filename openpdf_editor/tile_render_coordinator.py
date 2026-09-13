from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .tile_worker import RenderedTile, prepare_tile_job, read_tile_result


TileRenderContext = tuple[int, int, int, float, float]


@dataclass(frozen=True)
class TileRenderOutcome:
    context: TileRenderContext
    tiles: tuple[RenderedTile, ...] = ()
    error: str | None = None


class TileRenderCoordinator(QObject):
    """Own one isolated high-detail tile-render process at a time."""

    completed = Signal(object)

    def __init__(self, parent: QObject | None = None, *, timeout_ms: int = 20_000) -> None:
        super().__init__(parent)
        self._timeout_ms = timeout_ms
        self._request_id = 0
        self._process: QProcess | None = None
        self._workspace: Path | None = None
        self._result_path: Path | None = None
        self._context: TileRenderContext | None = None
        self._forced_error: str | None = None
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._timed_out)

    @property
    def process(self) -> QProcess | None:
        return self._process

    @property
    def is_running(self) -> bool:
        return self._process is not None

    def start(
        self,
        source_path: str | Path,
        page_index: int,
        scale: float,
        tile_rects: Iterable[tuple[int, int, int, int]],
        *,
        context: TileRenderContext,
        edits=(),
        inserted_images=(),
        deleted_images=(),
        inserted_texts=(),
    ) -> None:
        self.cancel(wait=True)
        workspace = Path(tempfile.mkdtemp(prefix="OpenPDFEditor-tile-job-"))
        try:
            job_path, result_path = prepare_tile_job(
                workspace,
                source_path,
                page_index,
                scale,
                tile_rects,
                edits=edits,
                inserted_images=inserted_images,
                deleted_images=deleted_images,
                inserted_texts=inserted_texts,
            )
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

        self._request_id += 1
        request_id = self._request_id
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        if getattr(sys, "frozen", False):
            arguments = ["--tile-render-worker", str(job_path)]
        else:
            arguments = ["-m", "openpdf_editor.tile_worker", str(job_path)]
        process.setProgram(sys.executable)
        process.setArguments(arguments)
        process.finished.connect(
            lambda exit_code, exit_status, rid=request_id: self._process_finished(
                rid, exit_code, exit_status
            )
        )
        process.errorOccurred.connect(
            lambda _error, rid=request_id: self._process_error(rid)
        )
        self._process = process
        self._workspace = workspace
        self._result_path = result_path
        self._context = context
        self._forced_error = None
        self._timeout.start(self._timeout_ms)
        process.start()

    def cancel(self, *, wait: bool = False) -> None:
        self._stop_timeout()
        self._request_id += 1
        process = self._process
        try:
            if process is not None and process.state() != QProcess.NotRunning:
                process.kill()
                process.waitForFinished(3000 if wait else 1000)
        except RuntimeError:
            pass
        self._cleanup()

    def _timed_out(self) -> None:
        process = self._process
        if process is None:
            return
        self._forced_error = "tile-render timeout"
        try:
            process.kill()
        except RuntimeError:
            self._complete(TileRenderOutcome(self._require_context(), error=self._forced_error))

    def _process_error(self, request_id: int) -> None:
        process = self._process
        if request_id != self._request_id or process is None:
            return
        if process.state() == QProcess.NotRunning:
            self._process_finished(request_id, -1, QProcess.CrashExit)

    def _process_finished(
        self,
        request_id: int,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._process
        if request_id != self._request_id or process is None:
            return
        self._request_id += 1
        rendered: list[RenderedTile] | None = None
        error = self._forced_error
        if error is None and exit_code == 0 and exit_status == QProcess.NormalExit:
            try:
                if self._result_path is None or not self._result_path.is_file():
                    raise ValueError("missing tile-render result")
                rendered, error = read_tile_result(self._result_path)
            except Exception as exc:
                error = str(exc)
        elif error is None:
            output = bytes(process.readAllStandardOutput()).decode(
                "utf-8", errors="replace"
            ).strip()
            error = output or f"tile-render process exit {exit_code}"
        self._complete(
            TileRenderOutcome(
                self._require_context(),
                tiles=tuple(rendered or ()),
                error=error,
            )
        )

    def _require_context(self) -> TileRenderContext:
        if self._context is None:
            raise RuntimeError("The tile-render context is missing.")
        return self._context

    def _complete(self, outcome: TileRenderOutcome) -> None:
        self._stop_timeout()
        self._cleanup()
        self.completed.emit(outcome)

    def _stop_timeout(self) -> None:
        try:
            self._timeout.stop()
        except RuntimeError:
            pass

    def _cleanup(self) -> None:
        process = self._process
        workspace = self._workspace
        self._process = None
        self._workspace = None
        self._result_path = None
        self._context = None
        self._forced_error = None
        if process is not None:
            try:
                process.deleteLater()
            except RuntimeError:
                pass
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)
