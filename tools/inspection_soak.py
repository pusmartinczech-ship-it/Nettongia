#!/usr/bin/env python3
"""Repeat isolated PDF inspections and report latency and memory stability."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from openpdf_editor import __version__  # noqa: E402
from openpdf_editor.engine import PdfEngine  # noqa: E402
from openpdf_editor.main_window import MainWindow  # noqa: E402
try:  # noqa: E402
    from tools.render_profile import current_rss_bytes
except ImportError:  # Direct execution puts tools/ rather than its parent on sys.path.
    from render_profile import current_rss_bytes


def process_rss_bytes(process_id: int) -> int:
    if process_id <= 0 or os.name == "nt":
        return 0
    try:
        for line in Path(f"/proc/{process_id}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def wait_for_inspection(
    app: QApplication,
    window: MainWindow,
    timeout: float,
) -> tuple[float, int, int]:
    started = time.perf_counter()
    deadline = started + timeout
    parent_peak = current_rss_bytes()
    child_peak = 0
    while window._inspection_process is not None and time.perf_counter() < deadline:
        process = window._inspection_process
        child_rss = process_rss_bytes(int(process.processId())) if process is not None else 0
        parent_peak = max(parent_peak, current_rss_bytes())
        child_peak = max(child_peak, child_rss)
        app.processEvents(QEventLoop.AllEvents, 25)
        time.sleep(0.005)
    if window._inspection_process is not None:
        raise TimeoutError("isolated inspection exceeded the configured timeout")
    if window._inspection_error is not None:
        raise RuntimeError(window._inspection_error)
    return time.perf_counter() - started, parent_peak, child_peak


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.cycles < 1 or args.cycles > 1000:
        parser.error("--cycles must be between 1 and 1000")

    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("Nettongia PDF Editor Profiling")
    app.setApplicationName("Nettongia PDF Editor Inspection Soak")
    engine = PdfEngine()
    engine.open(args.pdf.resolve())
    window = MainWindow(
        settings=QSettings(
            str(Path(tempfile.gettempdir()) / "openpdf-inspection-soak.ini"),
            QSettings.IniFormat,
        )
    )
    window.resize(1000, 700)
    window.show()
    workspaces_before = set(Path(tempfile.gettempdir()).glob("OpenPDFEditor-inspection-*"))
    parent_start = current_rss_bytes()
    window._activate_document(engine, args.pdf.resolve(), already_saved=True)
    # Isolate the inspection process measurement from the independent lazy
    # thumbnail loader and high-detail tile cache.
    window._cancel_thumbnail_loading()
    window._cancel_tile_render(wait=True, clear_cache=True)

    durations: list[float] = []
    parent_samples: list[int] = []
    parent_peak = parent_start
    child_peak = 0
    for cycle in range(args.cycles):
        duration, cycle_parent_peak, cycle_child_peak = wait_for_inspection(
            app, window, args.timeout
        )
        durations.append(duration)
        parent_peak = max(parent_peak, cycle_parent_peak)
        child_peak = max(child_peak, cycle_child_peak)
        parent_samples.append(current_rss_bytes())
        if cycle + 1 < args.cycles:
            window._start_document_inspection()

    parent_final = current_rss_bytes()
    steady_state_growth = parent_final - parent_samples[0]
    page_count = window.engine.page_count
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 25)
    workspaces_after = set(Path(tempfile.gettempdir()).glob("OpenPDFEditor-inspection-*"))
    leaked_workspaces = sorted(str(path) for path in workspaces_after - workspaces_before)
    report = {
        "application_version": __version__,
        "file": args.pdf.name,
        "pages": page_count,
        "cycles": args.cycles,
        "duration_seconds": {
            "minimum": round(min(durations), 4),
            "average": round(sum(durations) / len(durations), 4),
            "maximum": round(max(durations), 4),
        },
        "parent_rss_start_bytes": parent_start,
        "parent_rss_after_first_cycle_bytes": parent_samples[0],
        "parent_rss_final_bytes": parent_final,
        "activation_and_first_cycle_growth_bytes": parent_samples[0] - parent_start,
        "steady_state_growth_bytes": steady_state_growth,
        "parent_rss_samples_bytes": parent_samples,
        "parent_rss_peak_bytes": parent_peak,
        # Some sandboxed / containerized systems expose a host PID from Qt
        # which cannot be correlated with /proc.  Do not publish a misleading
        # combined number in that case.
        "child_rss_peak_bytes": child_peak if child_peak >= 1024 * 1024 else None,
        "child_rss_measurement_available": child_peak >= 1024 * 1024,
        "combined_parent_child_peak_bytes": (
            parent_peak + child_peak if child_peak >= 1024 * 1024 else None
        ),
        "leaked_inspection_workspaces": leaked_workspaces,
        "steady_state_growth_limit_bytes": 64 * 1024 * 1024,
        "status": (
            "passed"
            if not leaked_workspaces and steady_state_growth <= 64 * 1024 * 1024
            else "failed"
        ),
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
