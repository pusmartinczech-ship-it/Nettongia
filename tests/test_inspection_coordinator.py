import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import PdfEngine
from openpdf_editor.inspection_coordinator import (
    InspectionContext,
    InspectionCoordinator,
    InspectionOutcome,
)
from openpdf_editor.inspection_worker import DocumentInspectionReport
from openpdf_editor.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(app: QApplication, predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
        time.sleep(0.005)
    assert predicate()


def _report() -> DocumentInspectionReport:
    return DocumentInspectionReport(
        page_count=1,
        pdf_format="PDF 1.7",
        encrypted_source=False,
        digital_signature_fields=0,
        signed_digital_signatures=0,
        other_form_fields=0,
        xfa_forms=False,
        annotations=0,
        embedded_files=0,
        optional_content_groups=0,
        javascript=False,
        portfolio=False,
        tagged_pdf=False,
        oversized_pages=0,
        representative_pages_rendered=1,
    )


def test_coordinator_returns_context_and_cleans_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _application()
    workspace = tmp_path / "inspection-workspace"
    monkeypatch.setattr(
        "openpdf_editor.inspection_coordinator.tempfile.mkdtemp",
        lambda **_kwargs: str(workspace),
    )
    context = InspectionContext(document_generation=8)
    outcomes: list[InspectionOutcome] = []
    coordinator = InspectionCoordinator()
    coordinator.completed.connect(outcomes.append)

    coordinator.start(
        PdfEngine.blank_document_bytes(200, 300, 1),
        encrypted_source=False,
        context=context,
    )

    assert coordinator.is_running
    assert coordinator.process is not None
    _wait_until(app, lambda: not coordinator.is_running)
    assert len(outcomes) == 1
    assert outcomes[0].context == context
    assert outcomes[0].error is None
    assert outcomes[0].report is not None
    assert outcomes[0].report.page_count == 1
    assert not workspace.exists()


def test_coordinator_cleans_workspace_when_preparation_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "failed-inspection"
    monkeypatch.setattr(
        "openpdf_editor.inspection_coordinator.tempfile.mkdtemp",
        lambda **_kwargs: str(workspace),
    )
    monkeypatch.setattr(
        "openpdf_editor.inspection_coordinator.prepare_inspection_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("invalid PDF")),
    )
    coordinator = InspectionCoordinator()

    try:
        coordinator.start(
            b"invalid",
            encrypted_source=False,
            context=InspectionContext(document_generation=1),
        )
    except ValueError as exc:
        assert str(exc) == "invalid PDF"
    else:
        raise AssertionError("Invalid inspection job was accepted.")

    assert not coordinator.is_running
    assert not workspace.exists()


def test_window_discards_inspection_result_for_an_old_document() -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(200, 300, 1))
    window = MainWindow()
    window._activate_document(engine, None, already_saved=True)
    window._cancel_document_inspection()
    old_generation = window._document_generation
    window._document_session.document_generation += 1

    window._inspection_finished(
        InspectionOutcome(
            context=InspectionContext(old_generation),
            report=_report(),
        )
    )

    assert window._inspection_report is None
    assert window._inspection_error is None
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
