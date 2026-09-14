#!/usr/bin/env python3
"""Profile interactive preview/tile rendering with reproducible JSON output."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

try:
    import resource
except ImportError:  # Windows
    resource = None

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from openpdf_editor import __version__  # noqa: E402
from openpdf_editor.engine import PdfEngine  # noqa: E402
from openpdf_editor.main_window import MainWindow  # noqa: E402


def current_rss_bytes() -> int:
    if os.name == "nt":
        return windows_rss_bytes(peak=False)
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def windows_rss_bytes(*, peak: bool) -> int:
    """Read working-set memory without adding a psutil dependency."""
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        ):
            return int(counters.PeakWorkingSetSize if peak else counters.WorkingSetSize)
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    return 0


def peak_rss_bytes() -> int:
    if resource is None:
        return windows_rss_bytes(peak=True)
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; macOS reports bytes.
    return int(value if value > 10_000_000 else value * 1024)


def wait_for_tiles(app: QApplication, window: MainWindow, timeout: float) -> float:
    started = time.perf_counter()
    deadline = started + timeout
    processed_once = False
    while time.perf_counter() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
        processed_once = True
        if (
            processed_once
            and not window._tile_timer.isActive()
            and window._tile_task is None
            and window._tile_pool.activeThreadCount() == 0
        ):
            break
    return time.perf_counter() - started


def profile_pdf(app: QApplication, path: Path, timeout: float) -> dict[str, object]:
    rss_start = current_rss_bytes()
    engine = PdfEngine()
    opened_at = time.perf_counter()
    engine.open(path)
    open_seconds = time.perf_counter() - opened_at

    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    activated_at = time.perf_counter()
    window._activate_document(engine, path, already_saved=True)
    activation_seconds = time.perf_counter() - activated_at
    window._cancel_document_inspection()
    window._cancel_thumbnail_loading()
    app.processEvents(QEventLoop.AllEvents, 25)

    page_count = window.engine.page_count
    pages = list(dict.fromkeys((0, page_count // 2, page_count - 1)))
    samples: list[dict[str, object]] = []
    observed_peak = current_rss_bytes()
    for page_index in pages:
        started = time.perf_counter()
        window._select_and_render_page(page_index)
        window.set_zoom_percent(400)
        preview_seconds = time.perf_counter() - started
        tile_seconds = wait_for_tiles(app, window, timeout)
        observed_peak = max(observed_peak, current_rss_bytes())
        samples.append(
            {
                "page": page_index + 1,
                "preview_seconds": round(preview_seconds, 4),
                "detail_seconds": round(tile_seconds, 4),
                "cache_mib": round(window._tile_cache_bytes / 1048576, 3),
            }
        )

    hits_before = getattr(window, "_tile_cache_hits", 0)
    revisit_at = time.perf_counter()
    window._select_and_render_page(pages[0])
    revisit_preview_seconds = time.perf_counter() - revisit_at
    revisit_detail_seconds = wait_for_tiles(app, window, timeout)
    revisit_hits = getattr(window, "_tile_cache_hits", 0) - hits_before
    observed_peak = max(observed_peak, current_rss_bytes())

    scroll_bar = window.page_view.verticalScrollBar()
    scroll_started = time.perf_counter()
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0, 0.5, 0.0):
        value = round(scroll_bar.minimum() + fraction * (scroll_bar.maximum() - scroll_bar.minimum()))
        scroll_bar.setValue(value)
        # Exceed the debounce interval so this also exercises cancellation and
        # queue replacement rather than merely coalescing all scroll events.
        until = time.perf_counter() + 0.085
        while time.perf_counter() < until:
            app.processEvents(QEventLoop.AllEvents, 10)
            observed_peak = max(observed_peak, current_rss_bytes())
    wait_for_tiles(app, window, timeout)
    scroll_seconds = time.perf_counter() - scroll_started
    observed_peak = max(observed_peak, current_rss_bytes())

    result = {
        "file": path.name,
        "size_bytes": path.stat().st_size,
        "pages": page_count,
        "open_seconds": round(open_seconds, 4),
        "activation_seconds": round(activation_seconds, 4),
        "page_samples": samples,
        "revisit": {
            "preview_seconds": round(revisit_preview_seconds, 4),
            "detail_seconds": round(revisit_detail_seconds, 4),
            "cache_hits": revisit_hits,
        },
        "scroll_stress_seconds": round(scroll_seconds, 4),
        "cache": {
            "bytes": window._tile_cache_bytes,
            "hits": getattr(window, "_tile_cache_hits", None),
            "misses": getattr(window, "_tile_cache_misses", None),
            "evictions": getattr(window, "_tile_cache_evictions", None),
        },
        "rss_start_bytes": rss_start,
        "rss_observed_peak_bytes": observed_peak,
        "rss_final_bytes": current_rss_bytes(),
    }
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 25)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("Nettongia PDF Editor Profiling")
    app.setApplicationName("Nettongia PDF Editor Profiling")
    report = {
        "application_version": __version__,
        "platform": os.name,
        "profiles": [profile_pdf(app, path.resolve(), args.timeout) for path in args.pdf],
        "process_peak_rss_bytes": peak_rss_bytes(),
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
