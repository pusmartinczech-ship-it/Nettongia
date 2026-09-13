import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PySide6.QtCore import QEventLoop, QProcess, QTimer
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import PdfEngine, TextPlacement
from openpdf_editor.main_window import MainWindow
from openpdf_editor.tile_worker import prepare_tile_job, read_tile_result, run_tile_job


SAMPLES = Path(
    os.environ.get("OPENPDF_TEST_SAMPLES", Path(__file__).resolve().parents[2] / "upload")
)


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_tile_job_round_trip_preserves_unsaved_edits(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(PdfEngine.blank_document_bytes(420, 300))
    placement = TextPlacement(
        key="isolated-text",
        page_index=0,
        bbox=(60, 80, 300, 120),
        text="Isolated unsaved text",
        font_size=18,
    )
    job_path, result_path = prepare_tile_job(
        tmp_path / "job",
        source,
        0,
        2.0,
        ((0, 0, 500, 400),),
        inserted_texts=(placement,),
    )

    assert run_tile_job(job_path) == 0
    tiles, error = read_tile_result(result_path)

    assert error is None
    assert tiles is not None and len(tiles) == 1
    engine = PdfEngine()
    engine.open(source)
    document = engine.build_document(inserted_texts=(placement,))
    try:
        expected = document[0].get_pixmap(
            matrix=pymupdf.Matrix(2.0, 2.0),
            clip=pymupdf.Rect(0, 0, 250, 200),
            alpha=False,
            annots=True,
        )
    finally:
        document.close()
        engine.close()
    assert tiles[0].samples == bytes(expected.samples)


def test_tile_result_detects_modified_pixel_payload(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(PdfEngine.blank_document_bytes(420, 300))
    job_path, result_path = prepare_tile_job(
        tmp_path / "job", source, 0, 1.0, ((0, 0, 200, 200),)
    )
    assert run_tile_job(job_path) == 0
    payload = result_path.parent / "tiles" / "tile-000.rgb"
    damaged = bytearray(payload.read_bytes())
    damaged[0] ^= 0xFF
    payload.write_bytes(damaged)

    with pytest.raises(ValueError, match="integrity"):
        read_tile_result(result_path)


@pytest.mark.parametrize(
    "file_name",
    (
        "33-E00-01EKFA2A22_2018-03-16_CZ.pdf",
        "KS_Teil_2_2_01_KS26_ROB-KUKA_Projektspezifische_Vorgaben.pdf",
        "LV-15D_150026_________00_____ZSB_AFO_210_BLATT_001.pdf",
    ),
)
def test_supplied_reference_pdf_passes_isolated_tile_render(
    tmp_path: Path, file_name: str
) -> None:
    source = SAMPLES / file_name
    if not source.is_file():
        pytest.skip("supplied regression PDF is not available")
    with pymupdf.open(source) as document:
        page_index = document.page_count // 2
    job_path, result_path = prepare_tile_job(
        tmp_path / "job", source, page_index, 2.0, ((0, 0, 768, 768),)
    )

    assert run_tile_job(job_path) == 0
    tiles, error = read_tile_result(result_path)

    assert error is None
    assert tiles is not None and len(tiles) == 1
    assert tiles[0].width <= 768 and tiles[0].height <= 768


def test_window_tile_render_uses_child_process_and_keeps_gui_responsive() -> None:
    app = _application()
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(595.28, 841.89))
    window._activate_document(engine, None, already_saved=True)
    window._cancel_document_inspection()
    heartbeat: list[bool] = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    window.set_zoom_percent(400)

    deadline = time.monotonic() + 8
    saw_process = False
    while time.monotonic() < deadline and not window.page_view._tile_items:
        app.processEvents(QEventLoop.AllEvents, 25)
        saw_process = saw_process or isinstance(window._tile_task, QProcess)
        time.sleep(0.005)

    assert saw_process
    assert heartbeat == [True]
    assert window.page_view._tile_items
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
