import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest

from openpdf_editor.engine import PdfEngine, TextPlacement
from openpdf_editor.workers import RenderedTile, TileRenderTask

SAMPLES = Path(
    os.environ.get("OPENPDF_TEST_SAMPLES", Path(__file__).resolve().parents[2] / "upload")
)


def test_unmodified_tile_worker_uses_single_document_fast_path(monkeypatch) -> None:
    source_bytes = PdfEngine.blank_document_bytes(420, 300)

    def unexpected_engine_open(*_args, **_kwargs):
        pytest.fail("unmodified tile rendering must not open a second PdfEngine document")

    monkeypatch.setattr(PdfEngine, "load_bytes", unexpected_engine_open)
    task = TileRenderTask(11, source_bytes, 0, 2.0, ((0, 0, 200, 200),))
    ready = []
    finished = []
    task.signals.tile_ready.connect(lambda *args: ready.append(args))
    task.signals.finished.connect(finished.append)

    task.run()

    assert finished == [11]
    assert len(ready) == 1


def test_tile_worker_matches_direct_clipped_render() -> None:
    source = fitz.open()
    page = source.new_page(width=420, height=300)
    page.insert_text((60, 90), "Tile rendering", fontsize=24)
    source_bytes = source.tobytes()
    source.close()

    requested = (80, 40, 360, 260)
    task = TileRenderTask(
        request_id=7,
        source_bytes=source_bytes,
        page_index=0,
        scale=2.0,
        tile_rects=(requested,),
        inserted_texts=(
            TextPlacement(
                key="tile-text",
                page_index=0,
                bbox=(80, 120, 300, 160),
                text="Unsaved tile text",
                font_size=16,
            ),
        ),
    )
    ready: list[tuple[int, RenderedTile]] = []
    finished: list[int] = []
    task.signals.tile_ready.connect(lambda request_id, tile: ready.append((request_id, tile)))
    task.signals.finished.connect(finished.append)
    task.run()

    assert finished == [7]
    assert len(ready) == 1
    request_id, rendered = ready[0]
    assert request_id == 7
    assert rendered.requested_rect == requested

    engine = PdfEngine()
    engine.load_bytes(source_bytes)
    document = engine.build_document(inserted_texts=task.inserted_texts)
    try:
        expected = document[0].get_pixmap(
            matrix=fitz.Matrix(2.0, 2.0),
            clip=fitz.Rect(40, 20, 180, 130),
            alpha=False,
            annots=True,
        )
    finally:
        document.close()
        engine.close()

    assert (rendered.x, rendered.y) == (expected.x, expected.y)
    assert (rendered.width, rendered.height, rendered.stride) == (
        expected.width,
        expected.height,
        expected.stride,
    )
    assert rendered.samples == bytes(expected.samples)


def test_cancelled_tile_worker_emits_no_results() -> None:
    source_bytes = PdfEngine.blank_document_bytes(420, 300)
    task = TileRenderTask(3, source_bytes, 0, 2.0, ((0, 0, 200, 200),))
    ready = []
    finished = []
    task.signals.tile_ready.connect(lambda *args: ready.append(args))
    task.signals.finished.connect(finished.append)
    task.cancel()
    task.run()

    assert ready == []
    assert finished == []


@pytest.mark.parametrize(
    "file_name",
    (
        "33-E00-01EKFA2A22_2018-03-16_CZ.pdf",
        "KS_Teil_2_2_01_KS26_ROB-KUKA_Projektspezifische_Vorgaben.pdf",
        "LV-15D_150026_________00_____ZSB_AFO_210_BLATT_001.pdf",
    ),
)
def test_supplied_reference_pdf_tile_fast_path(file_name: str) -> None:
    source_path = SAMPLES / file_name
    if not source_path.is_file():
        pytest.skip("supplied regression PDF is not available")
    engine = PdfEngine()
    engine.open(source_path)
    page_index = engine.page_count // 2
    page_rect = engine.page_rect(page_index)
    requested = (
        0,
        0,
        min(768, max(1, round(page_rect.width * 2))),
        min(768, max(1, round(page_rect.height * 2))),
    )
    task = TileRenderTask(23, engine.source_bytes, page_index, 2.0, (requested,))
    ready = []
    finished = []
    task.signals.tile_ready.connect(lambda *args: ready.append(args))
    task.signals.finished.connect(finished.append)

    task.run()
    engine.close()

    assert finished == [23]
    assert len(ready) == 1
