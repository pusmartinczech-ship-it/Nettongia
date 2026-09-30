import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QFileDialog

from openpdf_editor.comparison_coordinator import (
    ComparisonContext,
    ComparisonCoordinator,
)
from openpdf_editor.comparison_worker import (
    prepare_comparison_job,
    read_comparison_result,
    run_comparison_job,
)
from openpdf_editor.dialogs import ComparisonDialog
from openpdf_editor.document_compare import (
    DocumentComparison,
    compare_pdf_documents,
)
from openpdf_editor.engine import PdfEngine, TextPlacement
from openpdf_editor.main_window import MainWindow
from openpdf_editor.recovery import RecoverySnapshot


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pdf(*texts: str, width: float = 420, height: float = 300) -> bytes:
    document = pymupdf.open()
    for text in texts:
        page = document.new_page(width=width, height=height)
        if text:
            page.insert_text((50, 80), text, fontsize=18)
    payload = document.tobytes()
    document.close()
    return payload


def _snapshot(pdf_bytes: bytes, inserted_text: str = "") -> RecoverySnapshot:
    inserted = (
        TextPlacement(
            key="pending-comparison-text",
            page_index=0,
            bbox=(50, 120, 350, 175),
            text=inserted_text,
            font_size=18,
        ),
    ) if inserted_text else ()
    return RecoverySnapshot(
        pdf_bytes=pdf_bytes,
        edits=(),
        inserted_texts=inserted,
        signatures=(),
        inserted_images=(),
        deleted_images=(),
        document_path=None,
        save_target_path=None,
        current_page=0,
        render_scale=1.0,
    )


def _wait_until(app: QApplication, predicate, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
        time.sleep(0.005)
    assert predicate()


def test_document_comparison_reports_visual_and_page_structure_changes() -> None:
    current = _pdf("Same", "Current only")
    other = _pdf("Changed")

    result = compare_pdf_documents(current, other)

    assert result.current_page_count == 2
    assert result.comparison_page_count == 1
    assert result.changed_page_count == 2
    assert result.pages[0].status == "changed"
    assert result.pages[0].changed_ratio > 0
    assert result.pages[0].changed_bbox is not None
    assert result.pages[1].status == "current_only"
    assert DocumentComparison.from_dict(result.to_dict()) == result


def test_document_comparison_detects_identical_and_different_geometry() -> None:
    source = _pdf("Identical")
    assert compare_pdf_documents(source, source).pages[0].status == "identical"

    geometry = compare_pdf_documents(source, _pdf("Identical", width=500))
    assert geometry.pages[0].status == "geometry"


def test_comparison_worker_includes_pending_editor_objects(tmp_path: Path) -> None:
    source = _pdf("Base")
    job, result_path, materialized_path = prepare_comparison_job(
        tmp_path / "job",
        _snapshot(source, inserted_text="Pending edit"),
        source,
    )

    assert run_comparison_job(job) == 0
    result, error = read_comparison_result(result_path)

    assert error is None
    assert result is not None and result.pages[0].status == "changed"
    with pymupdf.open(materialized_path) as materialized:
        assert "Pending edit" in materialized[0].get_text()


def test_comparison_coordinator_runs_isolated_and_returns_both_documents(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _application()
    workspace = tmp_path / "comparison-workspace"
    monkeypatch.setattr(
        "openpdf_editor.comparison_coordinator.tempfile.mkdtemp",
        lambda **_kwargs: str(workspace),
    )
    source = _pdf("Current")
    other = _pdf("Other")
    context = ComparisonContext(3, 7, "other.pdf")
    outcomes = []
    coordinator = ComparisonCoordinator()
    coordinator.completed.connect(outcomes.append)

    coordinator.start(_snapshot(source), other, context)
    _wait_until(app, lambda: not coordinator.is_running)

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.error is None
    assert outcome.context == context
    assert outcome.comparison is not None
    assert outcome.comparison.pages[0].status == "changed"
    assert outcome.current_pdf
    assert outcome.comparison_pdf == other
    assert not workspace.exists()


def test_comparison_dialog_shows_results_and_difference_preview() -> None:
    app = _application()
    current = _pdf("Current")
    other = _pdf("Other")
    result = compare_pdf_documents(current, other)

    dialog = ComparisonDialog(current, other, result, "other.pdf")
    dialog.show()
    app.processEvents()

    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 1).text() == "Changed"
    assert not dialog.current_preview.pixmap().isNull()
    assert not dialog.other_preview.pixmap().isNull()
    assert not dialog.diff_preview.pixmap().isNull()
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_main_window_comparison_includes_unsaved_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _application()
    target = tmp_path / "target.pdf"
    target.write_bytes(_pdf("Base"))
    engine = PdfEngine()
    engine.load_bytes(_pdf("Base"))
    window = MainWindow()
    window._activate_document(engine, tmp_path / "current.pdf", already_saved=True)
    window._cancel_document_inspection()
    state = window._capture_state()
    state.inserted_texts.append(
        TextPlacement(
            key="unsaved",
            page_index=0,
            bbox=(50, 120, 350, 175),
            text="Unsaved comparison text",
            font_size=18,
        )
    )
    window._push_state(state, 0)
    opened_results = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(target), "PDF"),
    )

    def capture_dialog(dialog: ComparisonDialog) -> int:
        opened_results.append(dialog._result)
        dialog.done(0)
        return 0

    monkeypatch.setattr(
        "openpdf_editor.main_window.ComparisonDialog.exec",
        capture_dialog,
    )

    assert window.compare_with_pdf()
    _wait_until(app, lambda: window._comparison_process is None)

    assert len(opened_results) == 1
    assert opened_results[0].pages[0].status == "changed"
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
