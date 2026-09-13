from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .document_session import DocumentWriteContext
from .engine import CompressionResult
from .recovery import RecoverySnapshot
from .write_worker import prepare_write_job, read_write_result


@dataclass(frozen=True)
class DocumentWriteOutcome:
    """Terminal result of one isolated document-write request."""

    context: DocumentWriteContext
    result: CompressionResult | None = None
    error: str | None = None
    cancelled: bool = False


class DocumentWriteCoordinator(QObject):
    """Own the child-process lifecycle for one document write at a time."""

    completed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request_id = 0
        self._process: QProcess | None = None
        self._workspace: Path | None = None
        self._result_path: Path | None = None
        self._context: DocumentWriteContext | None = None
        self._cancelled = False

    @property
    def process(self) -> QProcess | None:
        return self._process

    @property
    def is_running(self) -> bool:
        return self._process is not None

    def start(
        self,
        snapshot: RecoverySnapshot,
        context: DocumentWriteContext,
    ) -> None:
        if self.is_running:
            raise RuntimeError("A document write is already running.")

        workspace = Path(tempfile.mkdtemp(prefix="OpenPDFEditor-write-"))
        try:
            job_path, result_path = prepare_write_job(
                workspace,
                snapshot,
                context.path,
                context.compression_profile,
            )
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

        self._request_id += 1
        request_id = self._request_id
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        if getattr(sys, "frozen", False):
            arguments = ["--document-write-worker", str(job_path)]
        else:
            launcher = Path(__file__).resolve().parents[1] / "run_editor.py"
            arguments = [str(launcher), "--document-write-worker", str(job_path)]
        process.setProgram(sys.executable)
        process.setArguments(arguments)
        process.finished.connect(
            lambda exit_code, exit_status, rid=request_id: self._process_finished(
                rid, exit_code, exit_status
            )
        )
        process.errorOccurred.connect(
            lambda process_error, rid=request_id: self._process_error(
                rid, process_error
            )
        )

        self._process = process
        self._workspace = workspace
        self._result_path = result_path
        self._context = context
        self._cancelled = False
        process.start()

    def cancel(self) -> bool:
        process = self._process
        if process is None or process.state() == QProcess.NotRunning:
            return False
        self._cancelled = True
        if process.state() == QProcess.Starting:
            process.kill()
        else:
            process.terminate()
            request_id = self._request_id
            QTimer.singleShot(1500, lambda rid=request_id: self._kill(rid))
        return True

    def _kill(self, request_id: int) -> None:
        process = self._process
        if (
            process is not None
            and request_id == self._request_id
            and process.state() != QProcess.NotRunning
        ):
            process.kill()

    def _process_finished(
        self,
        request_id: int,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        process = self._process
        if process is None or request_id != self._request_id:
            return
        if self._cancelled:
            self._complete(DocumentWriteOutcome(self._require_context(), cancelled=True))
            return

        result: CompressionResult | None = None
        error: str | None = None
        try:
            if self._result_path is None or not self._result_path.is_file():
                raise RuntimeError("The document write process did not return a result.")
            result, error = read_write_result(self._result_path)
            if exit_status == QProcess.CrashExit:
                error = error or "The document write process stopped unexpectedly."
            elif exit_code != 0:
                error = error or f"The document write process returned code {exit_code}."
        except Exception as exc:
            process_output = bytes(process.readAllStandardOutput()).decode(
                "utf-8", errors="replace"
            ).strip()
            error = str(exc)
            if process_output:
                error = f"{error}\n\n{process_output[-4000:]}"
        self._complete(
            DocumentWriteOutcome(self._require_context(), result=result, error=error)
        )

    def _process_error(
        self,
        request_id: int,
        _process_error: QProcess.ProcessError,
    ) -> None:
        process = self._process
        if process is None or request_id != self._request_id:
            return
        if self._cancelled:
            self._complete(DocumentWriteOutcome(self._require_context(), cancelled=True))
            return
        error = process.errorString() or "The document write process failed."
        if process.state() != QProcess.NotRunning:
            process.kill()
            process.waitForFinished(1000)
        self._complete(DocumentWriteOutcome(self._require_context(), error=error))

    def _require_context(self) -> DocumentWriteContext:
        if self._context is None:
            raise RuntimeError("The document write context is missing.")
        return self._context

    def _complete(self, outcome: DocumentWriteOutcome) -> None:
        process = self._process
        if process is None:
            return
        workspace = self._workspace
        self._process = None
        self._workspace = None
        self._result_path = None
        self._context = None
        self._cancelled = False
        process.deleteLater()
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)
        self.completed.emit(outcome)
