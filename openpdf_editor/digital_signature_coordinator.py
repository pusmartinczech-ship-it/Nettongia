from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .digital_signature_worker import (
    CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE,
    SignatureWriteResult,
    prepare_signature_job,
    read_signature_result,
)
from .recovery import RecoverySnapshot


@dataclass(frozen=True)
class SignatureContext:
    output_path: Path
    document_generation: int
    content_revision: int


@dataclass(frozen=True)
class SignatureOutcome:
    context: SignatureContext
    result: SignatureWriteResult | None = None
    error: str | None = None
    cancelled: bool = False


class DigitalSignatureCoordinator(QObject):
    """Run certificate signing outside the GUI process."""

    completed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._request_id = 0
        self._process: QProcess | None = None
        self._workspace: Path | None = None
        self._result_path: Path | None = None
        self._context: SignatureContext | None = None
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
        context: SignatureContext,
        certificate_path: str | Path,
        certificate_password: str,
        *,
        field_name: str,
        create_field: bool,
        visible: bool = False,
        page_index: int = 0,
        reason: str = "",
        location: str = "",
        contact_info: str = "",
        timestamp_url: str = "",
        embed_revocation_info: bool = False,
    ) -> None:
        if self.is_running:
            raise RuntimeError("A digital-signature operation is already running.")
        if not certificate_password:
            raise ValueError("The certificate password is missing.")
        workspace = Path(tempfile.mkdtemp(prefix="Nettongia-signature-"))
        try:
            job_path, result_path = prepare_signature_job(
                workspace,
                snapshot,
                context.output_path,
                certificate_path,
                field_name=field_name,
                create_field=create_field,
                visible=visible,
                page_index=page_index,
                reason=reason,
                location=location,
                contact_info=contact_info,
                timestamp_url=timestamp_url,
                embed_revocation_info=embed_revocation_info,
            )
        except Exception:
            shutil.rmtree(workspace, ignore_errors=True)
            raise

        self._request_id += 1
        request_id = self._request_id
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert(
            CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, certificate_password
        )
        process.setProcessEnvironment(environment)
        if getattr(sys, "frozen", False):
            arguments = ["--digital-signature-worker", str(job_path)]
        else:
            launcher = Path(__file__).resolve().parents[1] / "run_editor.py"
            arguments = [str(launcher), "--digital-signature-worker", str(job_path)]
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
            self._complete(SignatureOutcome(self._require_context(), cancelled=True))
            return
        result: SignatureWriteResult | None = None
        error: str | None = None
        try:
            if self._result_path is None or not self._result_path.is_file():
                raise RuntimeError("The signing process did not return a result.")
            result, error = read_signature_result(self._result_path)
            if exit_status == QProcess.CrashExit:
                error = error or "The signing process stopped unexpectedly."
            elif exit_code != 0:
                error = error or f"The signing process returned code {exit_code}."
        except Exception as exc:
            output = bytes(process.readAllStandardOutput()).decode(
                "utf-8", errors="replace"
            ).strip()
            error = str(exc)
            if output:
                error = f"{error}\n\n{output[-4000:]}"
        self._complete(
            SignatureOutcome(self._require_context(), result=result, error=error)
        )

    def _process_error(
        self, request_id: int, _process_error: QProcess.ProcessError
    ) -> None:
        process = self._process
        if process is None or request_id != self._request_id:
            return
        if self._cancelled:
            self._complete(SignatureOutcome(self._require_context(), cancelled=True))
            return
        error = process.errorString() or "The signing process failed."
        if process.state() != QProcess.NotRunning:
            process.kill()
            process.waitForFinished(1000)
        self._complete(SignatureOutcome(self._require_context(), error=error))

    def _require_context(self) -> SignatureContext:
        if self._context is None:
            raise RuntimeError("The digital-signature context is missing.")
        return self._context

    def _complete(self, outcome: SignatureOutcome) -> None:
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
