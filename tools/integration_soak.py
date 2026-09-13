#!/usr/bin/env python3
"""Exercise repeated GUI document lifecycles and enforce bounded RSS growth."""

from __future__ import annotations

import argparse
import gc
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from openpdf_editor import __version__  # noqa: E402
from openpdf_editor.main_window import MainWindow  # noqa: E402
from tools.golden_pdf_audit import golden_fixture_bytes  # noqa: E402
from tools.render_profile import current_rss_bytes, wait_for_tiles  # noqa: E402


STEADY_STATE_GROWTH_LIMIT = 96 * 1024 * 1024
POST_WARMUP_PEAK_GROWTH_LIMIT = 256 * 1024 * 1024


def _drain_events(app: QApplication, milliseconds: int = 40) -> None:
    deadline = time.perf_counter() + milliseconds / 1000
    while time.perf_counter() < deadline:
        app.processEvents(QEventLoop.AllEvents, 10)
    # processEvents() alone intentionally does not process every deferred-delete
    # event when no outer QApplication.exec() loop is running.  The soak is a
    # command-line harness, so emulate that part of the real GUI event loop;
    # otherwise already-replaced QGraphicsScenes accumulate in the harness and
    # produce a false linear leak that users of the running application do not
    # experience.
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents(QEventLoop.AllEvents, 10)


def _median(values: list[int]) -> int:
    return int(statistics.median(values))


def run_soak(
    *,
    cycles: int,
    timeout: float,
    output: Path | None = None,
) -> dict[str, object]:
    if not 3 <= cycles <= 1000:
        raise ValueError("cycles must be between 3 and 1000")
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("OpenPDF Editor Integration")
    app.setApplicationName("OpenPDF Editor Integration Soak")

    with tempfile.TemporaryDirectory(prefix="OpenPDFEditor-integration-soak-") as root:
        root_path = Path(root)
        pdf_path = root_path / "Integrační golden dokument.pdf"
        settings_path = root_path / "integration-soak.ini"
        pdf_path.write_bytes(golden_fixture_bytes())
        workspaces_before = set(
            Path(tempfile.gettempdir()).glob("OpenPDFEditor-*-*")
        )

        window = MainWindow(
            settings=QSettings(str(settings_path), QSettings.IniFormat)
        )
        window.resize(1000, 700)
        window.show()
        window._maybe_save_changes = lambda: True
        _drain_events(app)

        rss_before = current_rss_bytes()
        samples: list[int] = []
        durations: list[float] = []
        peak = rss_before
        pages_rendered = 0
        for cycle in range(cycles):
            started = time.perf_counter()
            if not window.open_pdf(str(pdf_path)):
                raise RuntimeError(f"document open failed in cycle {cycle + 1}")
            window._cancel_document_inspection()
            window._cancel_thumbnail_loading()
            for page_index in range(window.engine.page_count):
                window._select_and_render_page(page_index)
                window.set_zoom_percent((100, 200, 400, 125)[(cycle + page_index) % 4])
                wait_for_tiles(app, window, timeout)
                pages_rendered += 1
                peak = max(peak, current_rss_bytes())
            scroll_bar = window.page_view.verticalScrollBar()
            for fraction in (0.0, 0.5, 1.0, 0.0):
                scroll_bar.setValue(
                    round(
                        scroll_bar.minimum()
                        + fraction * (scroll_bar.maximum() - scroll_bar.minimum())
                    )
                )
                _drain_events(app, 15)
            if not window.close_document():
                raise RuntimeError(f"document close failed in cycle {cycle + 1}")
            if (cycle + 1) % 5 == 0:
                gc.collect()
            _drain_events(app)
            sample = current_rss_bytes()
            samples.append(sample)
            peak = max(peak, sample)
            durations.append(time.perf_counter() - started)

        window.close()
        window.deleteLater()
        gc.collect()
        _drain_events(app, 100)
        rss_final = current_rss_bytes()
        peak = max(peak, rss_final)

        warmup = max(1, min(10, cycles // 5))
        steady_samples = samples[warmup:]
        segment = max(1, len(steady_samples) // 3)
        early_median = _median(steady_samples[:segment])
        late_median = _median(steady_samples[-segment:])
        steady_growth = max(0, late_median - early_median)
        post_warmup_peak_growth = max(0, max(steady_samples) - early_median)
        workspaces_after = set(
            Path(tempfile.gettempdir()).glob("OpenPDFEditor-*-*")
        )
        leaked = sorted(
            str(path)
            for path in workspaces_after - workspaces_before
            if path != root_path
        )
        rss_measurement_available = all(value > 0 for value in samples)
        passed = (
            not leaked
            and rss_measurement_available
            and steady_growth <= STEADY_STATE_GROWTH_LIMIT
            and post_warmup_peak_growth <= POST_WARMUP_PEAK_GROWTH_LIMIT
        )
        report: dict[str, object] = {
            "format": "openpdf-editor-integration-soak-v1",
            "application_version": __version__,
            "status": "passed" if passed else "failed",
            "cycles": cycles,
            "pages_rendered": pages_rendered,
            "warmup_cycles": warmup,
            "duration_seconds": {
                "total": round(sum(durations), 3),
                "average_cycle": round(sum(durations) / len(durations), 3),
                "maximum_cycle": round(max(durations), 3),
            },
            "rss_before_bytes": rss_before,
            "rss_final_bytes": rss_final,
            "rss_peak_bytes": peak,
            "rss_samples_bytes": samples,
            "rss_measurement_available": rss_measurement_available,
            "steady_state_early_median_bytes": early_median,
            "steady_state_late_median_bytes": late_median,
            "steady_state_growth_bytes": steady_growth,
            "steady_state_growth_limit_bytes": STEADY_STATE_GROWTH_LIMIT,
            "post_warmup_peak_growth_bytes": post_warmup_peak_growth,
            "post_warmup_peak_growth_limit_bytes": POST_WARMUP_PEAK_GROWTH_LIMIT,
            "leaked_temporary_workspaces": leaked,
        }

    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run_soak(
            cycles=args.cycles,
            timeout=args.timeout,
            output=args.output,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
