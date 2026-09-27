from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .comparison_worker import prepare_comparison_job, read_comparison_result
from .document_compare import DocumentComparison
from .recovery import RecoverySnapshot


@dataclass(frozen=True)
class ComparisonContext:
    document_generation: int
    content_revision: int
    comparison_name: str


@dataclass(frozen=True)
class ComparisonOutcome:
    context: ComparisonContext
    comparison: DocumentComparison | None = None
    current_pdf: bytes | None = None
    comparison_pdf: bytes | None = None
    error: str | None = None
    cancelled: bool = False


class ComparisonCoordinator(QObject):
    completed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request_id = 0
        self._process: QProcess | None = None
        self._workspace: Path | None = None
        self._result_path: Path | None = None
        self._materialized_path: Path | None = None
        self._comparison_pdf: bytes | None = None
        self._context: ComparisonContext | None = None
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
        comparison_pdf: bytes,
        context: ComparisonContext,
    ) -> None:
        if self.is_running:
            raise RuntimeError("A document comparison is already running.")
        workspace = Path(tempfile.mkdtemp(prefix="Nettongia-compare-"))
        try:
            job_path, result_path, materialized_path = prepare_comparison_job(
                workspace, snapshot, comparison_pdf
            )
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

        self._request_id += 1
        request_id = self._request_id
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        if getattr(sys, "frozen", False):
            arguments = ["--document-comparison-worker", str(job_path)]
        else:
            launcher = Path(__file__).resolve().parents[1] / "run_editor.py"
            arguments = [str(launcher), "--document-comparison-worker", str(job_path)]
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
        self._materialized_path = materialized_path
        self._comparison_pdf = comparison_pdf
        self._context = context
        self._cancelled = False
        process.start()

    def cancel(self) -> bool:
        process = self._process
        if process is None or process.state() == QProcess.NotRunning:
            return False
        self._cancelled = True
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
            self._complete(ComparisonOutcome(self._require_context(), cancelled=True))
            return
        comparison = None
        current_pdf = None
        error = None
        try:
            if self._result_path is None or not self._result_path.is_file():
                raise RuntimeError("The comparison process did not return a result.")
            comparison, error = read_comparison_result(self._result_path)
            if error is None:
                if self._materialized_path is None:
                    raise RuntimeError("The materialized current PDF is missing.")
                current_pdf = self._materialized_path.read_bytes()
            if exit_status == QProcess.CrashExit:
                error = error or "The comparison process stopped unexpectedly."
            elif exit_code != 0:
                error = error or f"The comparison process returned code {exit_code}."
        except Exception as exc:
            error = str(exc)
        self._complete(
            ComparisonOutcome(
                self._require_context(),
                comparison=comparison,
                current_pdf=current_pdf,
                comparison_pdf=self._comparison_pdf if error is None else None,
                error=error,
            )
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
            self._complete(ComparisonOutcome(self._require_context(), cancelled=True))
            return
        error = process.errorString() or "The comparison process failed."
        if process.state() != QProcess.NotRunning:
            process.kill()
            process.waitForFinished(1000)
        self._complete(ComparisonOutcome(self._require_context(), error=error))

    def _require_context(self) -> ComparisonContext:
        if self._context is None:
            raise RuntimeError("The comparison context is missing.")
        return self._context

    def _complete(self, outcome: ComparisonOutcome) -> None:
        process = self._process
        if process is None:
            return
        workspace = self._workspace
        self._process = None
        self._workspace = None
        self._result_path = None
        self._materialized_path = None
        self._comparison_pdf = None
        self._context = None
        self._cancelled = False
        process.deleteLater()
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)
        self.completed.emit(outcome)
