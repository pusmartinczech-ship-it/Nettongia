from __future__ import annotations

import ctypes
import faulthandler
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import TextIO

from .branding import APP_ID, APP_NAME, LEGACY_APP_NAME
from .crash_trace import install_crash_trace, uninstall_crash_trace
from .runtime import configure_packaged_runtime

configure_packaged_runtime()

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .inspection_worker import run_inspection_job
from .ocr_worker import run_ocr_job
from .tile_worker import run_tile_job
from .write_worker import run_write_job


def _start_local_crash_log() -> tuple[Path | None, TextIO | None, object]:
    """Capture otherwise invisible pythonw / native Qt failures locally."""

    previous_hook = sys.excepthook
    try:
        root = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / LEGACY_APP_NAME
        root.mkdir(parents=True, exist_ok=True)
        path = root / "crash.log"
        if path.is_file() and path.stat().st_size > 0:
            # Keep the most recent abnormal-run evidence available after the
            # next launch. Diagnostics exports metadata only, never this raw
            # file or its potentially sensitive traceback text.
            os.replace(path, root / "crash.previous.log")
        stream = path.open("w", encoding="utf-8", buffering=1)
        faulthandler.enable(stream, all_threads=True)
        install_crash_trace(stream, frozen=bool(getattr(sys, "frozen", False)))

        def report_exception(exception_type, value, exception_traceback) -> None:
            traceback.print_exception(
                exception_type,
                value,
                exception_traceback,
                file=stream,
            )
            stream.flush()
            previous_hook(exception_type, value, exception_traceback)

        sys.excepthook = report_exception
        return path, stream, previous_hook
    except (OSError, RuntimeError):
        return None, None, previous_hook


def _finish_local_crash_log(
    path: Path | None,
    stream: TextIO | None,
    previous_hook: object,
    *,
    clean_exit: bool = False,
) -> None:
    sys.excepthook = previous_hook
    if stream is None:
        return
    try:
        uninstall_crash_trace()
        if faulthandler.is_enabled():
            faulthandler.disable()
        stream.close()
        if path is not None and path.exists() and (
            clean_exit or path.stat().st_size == 0
        ):
            path.unlink()
    except OSError:
        pass


def _set_application_identity() -> None:
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setOrganizationName("Nettongia")
    if sys.platform == "win32":
        try:
            set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
            set_app_id.argtypes = [ctypes.c_wchar_p]
            set_app_id.restype = ctypes.c_long
            set_app_id(APP_ID)
        except (AttributeError, OSError, TypeError):
            pass


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--ocr-acceptance":
        from .portable_ocr_acceptance import run_portable_ocr_acceptance

        return run_portable_ocr_acceptance(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from .self_test import run_self_test

        return run_self_test(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--document-write-worker":
        return run_write_job(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--document-inspection-worker":
        return run_inspection_job(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--tile-render-worker":
        return run_tile_job(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--ocr-worker":
        return run_ocr_job(sys.argv[2])
    crash_path, crash_stream, previous_hook = _start_local_crash_log()
    clean_exit = False
    try:
        _set_application_identity()
        app = QApplication(sys.argv)
        _set_application_identity()
        app.setWindowIcon(
            QIcon(
                str(
                    Path(__file__).resolve().parents[1]
                    / "assets"
                    / "nettongia_mascot_pdf.png"
                )
            )
        )
        window = MainWindow()
        window.show()

        def finish_startup() -> None:
            window.offer_recovery()
            window.start_automatic_update_check()
            if len(sys.argv) > 1:
                window.open_pdf(sys.argv[1])

        QTimer.singleShot(0, finish_startup)
        result = app.exec()
        clean_exit = True
        return result
    except BaseException:
        if crash_stream is not None:
            traceback.print_exc(file=crash_stream)
            crash_stream.flush()
        raise
    finally:
        _finish_local_crash_log(
            crash_path,
            crash_stream,
            previous_hook,
            clean_exit=clean_exit,
        )


if __name__ == "__main__":
    raise SystemExit(main())
