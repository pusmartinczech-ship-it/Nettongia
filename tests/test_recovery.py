import os
import time
import zipfile
from pathlib import Path
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import pymupdf
from PySide6.QtCore import QEventLoop, QSettings
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import (
    ImageDeletion,
    ImagePlacement,
    ImageRun,
    PdfEngine,
    SignaturePlacement,
    TextEdit,
    TextPlacement,
    TextRun,
)
from openpdf_editor.main_window import MAX_RECENT_FILES, MainWindow
from openpdf_editor.recovery import (
    RecoveryCancelled,
    RecoverySnapshot,
    read_recovery_snapshot,
    validate_recovery_assets,
    validate_recovery_pages,
    write_recovery_snapshot,
)


SAMPLES = Path(
    os.environ.get("OPENPDF_TEST_SAMPLES", Path(__file__).resolve().parents[2] / "upload")
)


def _application() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("OpenPDF Editor Recovery Tests")
    app.setApplicationName("OpenPDF Editor Recovery Tests")
    return app


def _snapshot(text: str = "Changed") -> RecoverySnapshot:
    pdf_bytes = PdfEngine.blank_document_bytes(420, 300, 2)
    run = TextRun(
        key="0:0:0:0",
        page_index=0,
        block_index=0,
        line_index=0,
        span_index=0,
        text="Original",
        bbox=(20.0, 30.0, 120.0, 50.0),
        origin=(20.0, 45.0),
        font_name="Arial-BoldMT",
        font_size=12.0,
        color=0x102030,
        flags=16,
        direction=(0.0, -1.0),
    )
    return RecoverySnapshot(
        pdf_bytes=pdf_bytes,
        edits=(
            TextEdit(
                run=run,
                new_text=text,
                font_size=14.0,
                fit_to_width=False,
                font_family="Arial",
                bold=True,
                italic=False,
                underline=True,
                color=0x405060,
                bbox=(20.0, 30.0, 150.0, 55.0),
            ),
        ),
        inserted_texts=(
            TextPlacement(
                key="text-1",
                page_index=1,
                bbox=(30.0, 60.0, 210.0, 100.0),
                text="Recovered text",
                font_family="Calibri",
                font_size=18.0,
                bold=True,
                italic=True,
                underline=False,
                color=0x112233,
            ),
        ),
        signatures=(
            SignaturePlacement(
                page_index=1,
                bbox=(40.0, 120.0, 180.0, 180.0),
                png_bytes=b"signature-png-payload",
                description="Test signature",
                key="signature-1",
                rotation_degrees=17.5,
            ),
        ),
        inserted_images=(
            ImagePlacement(
                key="image-1",
                page_index=0,
                bbox=(200.0, 40.0, 300.0, 140.0),
                image_bytes=b"image-payload",
                description="Test image",
                rotation_degrees=-28.5,
            ),
        ),
        deleted_images=(
            ImageDeletion(
                ImageRun(
                    key="0:12:0",
                    page_index=0,
                    bbox=(10.0, 10.0, 50.0, 50.0),
                    xref=12,
                    width=64,
                    height=64,
                )
            ),
        ),
        document_path="C:/Documents/source.pdf",
        save_target_path="C:/Documents/edited.pdf",
        current_page=1,
        render_scale=1.25,
    )


def _restorable_snapshot(text: str = "Startup recovery") -> RecoverySnapshot:
    return RecoverySnapshot(
        pdf_bytes=PdfEngine.blank_document_bytes(420, 300, 2),
        edits=(),
        inserted_texts=(
            TextPlacement(
                key="startup-text",
                page_index=0,
                bbox=(40.0, 50.0, 300.0, 90.0),
                text=text,
            ),
        ),
        signatures=(),
        inserted_images=(),
        deleted_images=(),
        document_path=None,
        save_target_path=None,
        current_page=0,
        render_scale=1.0,
    )


def test_recovery_archive_round_trips_every_editor_object(tmp_path: Path) -> None:
    path = tmp_path / "session.openpdf-recovery"
    expected = _snapshot()

    write_recovery_snapshot(path, expected)
    actual = read_recovery_snapshot(path)

    assert actual == expected
    validate_recovery_pages(actual, 2)
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "source.pdf" in names
        assert any(name.startswith("assets/signature-") for name in names)
        assert any(name.startswith("assets/image-") for name in names)


def test_cancelled_recovery_write_preserves_previous_complete_archive(tmp_path: Path) -> None:
    path = tmp_path / "session.openpdf-recovery"
    write_recovery_snapshot(path, _snapshot("First version"))
    cancelled = Event()
    cancelled.set()

    with pytest.raises(RecoveryCancelled):
        write_recovery_snapshot(path, _snapshot("Second version"), cancelled)

    assert read_recovery_snapshot(path).edits[0].new_text == "First version"
    assert not list(tmp_path.glob(".*.tmp"))


def test_recovery_reader_rejects_unexpected_archive_entries(tmp_path: Path) -> None:
    path = tmp_path / "session.openpdf-recovery"
    write_recovery_snapshot(path, _snapshot())
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("../unexpected.txt", "unsafe")

    with pytest.raises(ValueError, match="unexpected"):
        read_recovery_snapshot(path)


def test_recovery_page_references_are_validated() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValueError, match="does not exist"):
        validate_recovery_pages(snapshot, 1)


def test_invalid_recovered_image_payload_is_rejected_before_rendering() -> None:
    with pytest.raises(ValueError, match="valid image"):
        validate_recovery_assets(_snapshot())


def test_main_window_writes_and_restores_unsaved_state(tmp_path: Path) -> None:
    app = _application()
    recovery_path = tmp_path / "session.openpdf-recovery"
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    window = MainWindow(recovery_path=recovery_path, settings=settings)
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300, 2))
    window._activate_document(engine, None, already_saved=False)
    window.inserted_texts = [
        TextPlacement(
            key="recovered-text",
            page_index=1,
            bbox=(40.0, 50.0, 260.0, 90.0),
            text="Work survives a crash",
        )
    ]
    window.current_page = 1
    window.render_scale = 1.5
    window._recovery_timer.stop()
    window._start_recovery_write()

    deadline = time.monotonic() + 5
    while window._recovery_task is not None and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 20)
    assert window._recovery_task is None
    assert recovery_path.is_file()

    restored = MainWindow(recovery_path=recovery_path, settings=settings)
    snapshot = read_recovery_snapshot(recovery_path)
    restored._recovery_protected = False
    assert restored._restore_recovery_snapshot(snapshot)
    assert restored.has_unsaved_changes
    assert restored.current_page == 1
    assert restored.render_scale == 1.5
    assert restored.inserted_texts[0].text == "Work survives a crash"
    assert restored.windowTitle().endswith("Untitled.pdf *")

    window._maybe_save_changes = lambda: True
    restored._maybe_save_changes = lambda: True
    window.close()
    restored.close()
    window.deleteLater()
    restored.deleteLater()
    app.processEvents()


def test_startup_offer_restores_a_valid_snapshot(tmp_path: Path, monkeypatch) -> None:
    app = _application()
    recovery_path = tmp_path / "startup.openpdf-recovery"
    write_recovery_snapshot(recovery_path, _restorable_snapshot())
    window = MainWindow(
        recovery_path=recovery_path,
        settings=QSettings(str(tmp_path / "startup.ini"), QSettings.IniFormat),
    )
    monkeypatch.setattr(window, "_ask_recovery_action", lambda name: "restore")

    assert window.offer_recovery()
    assert window.has_unsaved_changes
    assert window.inserted_texts[0].text == "Startup recovery"
    assert recovery_path.exists()

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_startup_offer_discards_only_after_explicit_choice(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _application()
    recovery_path = tmp_path / "discard.openpdf-recovery"
    write_recovery_snapshot(recovery_path, _snapshot())
    window = MainWindow(
        recovery_path=recovery_path,
        settings=QSettings(str(tmp_path / "discard.ini"), QSettings.IniFormat),
    )
    monkeypatch.setattr(window, "_ask_recovery_action", lambda name: "discard")

    assert not window.offer_recovery()
    assert not recovery_path.exists()
    assert not window.engine.is_open

    window.close()
    window.deleteLater()
    app.processEvents()


def test_recent_files_are_persisted_deduplicated_and_bounded(tmp_path: Path) -> None:
    app = _application()
    settings_path = tmp_path / "settings.ini"
    settings = QSettings(str(settings_path), QSettings.IniFormat)
    window = MainWindow(
        recovery_path=tmp_path / "recovery.openpdf-recovery",
        settings=settings,
    )
    paths = [tmp_path / f"document-{index}.pdf" for index in range(12)]
    for path in paths:
        window._add_recent_file(path)
    window._add_recent_file(paths[5])

    assert len(window.recent_files) == MAX_RECENT_FILES
    assert window.recent_files[0] == paths[5].absolute()
    assert len({str(path) for path in window.recent_files}) == MAX_RECENT_FILES
    assert window.recent_menu.actions()[-1].text() == window.trx("clear_recent_files")

    reloaded = MainWindow(
        recovery_path=tmp_path / "other-recovery.openpdf-recovery",
        settings=QSettings(str(settings_path), QSettings.IniFormat),
    )
    assert reloaded.recent_files == window.recent_files

    window.close()
    reloaded.close()
    window.deleteLater()
    reloaded.deleteLater()
    app.processEvents()


def test_recovered_source_text_edit_can_be_saved_to_a_real_pdf(tmp_path: Path) -> None:
    source = SAMPLES / "KS_Teil_2_2_01_KS26_ROB-KUKA_Projektspezifische_Vorgaben.pdf"
    if not source.exists():
        return
    app = _application()
    recovery_path = tmp_path / "real-document.openpdf-recovery"
    settings = QSettings(str(tmp_path / "real-settings.ini"), QSettings.IniFormat)
    window = MainWindow(recovery_path=recovery_path, settings=settings)
    engine = PdfEngine()
    engine.open(source)
    window._activate_document(engine, source, already_saved=True)
    run = next(
        item for item in engine.text_runs(1) if item.text == "Inhaltsverzeichnis:"
    )
    state = window._capture_state()
    state.edits[run.key] = TextEdit(
        run=run,
        new_text="Recovered contents heading",
        font_size=run.font_size,
        fit_to_width=False,
        font_family=run.font_name,
        bold=run.bold,
        italic=run.italic,
        color=run.color,
    )
    window._push_state(state, 1)
    window._recovery_timer.stop()
    window._start_recovery_write()
    deadline = time.monotonic() + 5
    while window._recovery_task is not None and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 20)
    assert recovery_path.is_file()

    recovered = MainWindow(recovery_path=recovery_path, settings=settings)
    recovered._recovery_protected = False
    assert recovered._restore_recovery_snapshot(read_recovery_snapshot(recovery_path))
    recovered._cancel_document_inspection()
    output = tmp_path / "recovered-edit.pdf"
    assert recovered._save_to_path(output, show_confirmation=False)
    assert not recovery_path.exists()
    with pymupdf.open(output) as document:
        assert "Recovered contents heading" in document[1].get_text()
        pixmap = document[1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
        assert pixmap.width > 500
        assert pixmap.height > 700

    window._maybe_save_changes = lambda: True
    recovered._maybe_save_changes = lambda: True
    window.close()
    recovered.close()
    window.deleteLater()
    recovered.deleteLater()
    app.processEvents()
