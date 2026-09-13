from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from .ocr_worker import prepare_ocr_job, read_ocr_result


@dataclass(frozen=True)
class OcrContext:
    document_generation: int
    content_revision: int


@dataclass(frozen=True)
class OcrOutcome:
    context: OcrContext
    result: dict[str, int] | None = None
    output_bytes: bytes | None = None
    error: str | None = None


class OcrCoordinator(QObject):
    """Own one isolated OCR process and return a validated immutable result."""

    completed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request_id = 0
        self._process: QProcess | None = None
        self._workspace: Path | None = None
        self._result_path: Path | None = None
        self._output_path: Path | None = None
        self._context: OcrContext | None = None

    @property
    def process(self) -> QProcess | None:
        return self._process

    @property
    def is_running(self) -> bool:
        return self._process is not None

    def start(
        self,
        source_bytes: bytes,
        page_indices: tuple[int, ...],
        language: str,
        *,
        context: OcrContext,
        dpi: int = 200,
    ) -> None:
        if self.is_running:
            raise RuntimeError("OCR is already running.")
        workspace = Path(tempfile.mkdtemp(prefix="OpenPDFEditor-ocr-"))
        try:
            job_path, result_path, output_path = prepare_ocr_job(
                workspace,
                source_bytes,
                page_indices,
                language,
                dpi,
            )
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

        self._request_id += 1
        request_id = self._request_id
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        arguments = (
            ["--ocr-worker", str(job_path)]
            if getattr(sys, "frozen", False)
            else ["-m", "openpdf_editor.ocr_worker", str(job_path)]
        )
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
        self._output_path = output_path
        self._context = context
        process.start()

    def cancel(self) -> bool:
        self._request_id += 1
        process = self._process
        if process is None:
            return False
        try:
            if process.state() != QProcess.NotRunning:
                process.kill()
                process.waitForFinished(3000)
        except RuntimeError:
            pass
        self._cleanup()
        return True

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
        result: dict[str, int] | None = None
        output_bytes: bytes | None = None
        error: str | None = None
        if exit_code == 0 and exit_status == QProcess.NormalExit:
            try:
                if (
                    self._result_path is None
                    or self._output_path is None
                    or not self._result_path.is_file()
                ):
                    raise ValueError("missing OCR result")
                result, error = read_ocr_result(
                    self._result_path,
                    self._output_path,
                )
                if result is not None and result["processed_pages"]:
                    output_bytes = self._output_path.read_bytes()
            except Exception as exc:
                error = str(exc)
        else:
            output = bytes(process.readAllStandardOutput()).decode(
                "utf-8", errors="replace"
            ).strip()
            error = output or f"OCR process exit {exit_code}"
        self._complete(
            OcrOutcome(
                self._require_context(),
                result=result,
                output_bytes=output_bytes,
                error=error,
            )
        )

    def _require_context(self) -> OcrContext:
        if self._context is None:
            raise RuntimeError("The OCR context is missing.")
        return self._context

    def _complete(self, outcome: OcrOutcome) -> None:
        self._cleanup()
        self.completed.emit(outcome)

    def _cleanup(self) -> None:
        process = self._process
        workspace = self._workspace
        self._process = None
        self._workspace = None
        self._result_path = None
        self._output_path = None
        self._context = None
        if process is not None:
            try:
                process.deleteLater()
            except RuntimeError:
                pass
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)
