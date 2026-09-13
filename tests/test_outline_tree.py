import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import PdfEngine
from openpdf_editor.main_window import MainWindow, PdfOutlineModel


SAMPLES = Path(os.environ.get("OPENPDF_TEST_SAMPLES", Path(__file__).resolve().parents[2] / "upload"))


def _application() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("OpenPDF Editor Tests")
    app.setApplicationName("OpenPDF Editor Tests")
    return app


def _outlined_document() -> bytes:
    document = pymupdf.open()
    for _ in range(3):
        document.new_page(width=420, height=300)
    document.set_toc(
        [
            [1, "Root A", 1],
            [2, "Child A1", 2],
            [2, "Child A2", 3],
            [1, "Root B", 3],
        ]
    )
    try:
        return document.tobytes()
    finally:
        document.close()


def _empty_outline_dictionary_document() -> bytes:
    document = pymupdf.open()
    document.new_page(width=420, height=300)
    outline_xref = document.get_new_xref()
    document.update_object(outline_xref, "<< /Type /Outlines /Count 0 >>")
    document.xref_set_key(
        document.pdf_catalog(),
        "Outlines",
        f"{outline_xref} 0 R",
    )
    try:
        return document.tobytes()
    finally:
        document.close()


def test_outline_model_preserves_hierarchy_and_fetches_in_batches() -> None:
    _application()
    engine = PdfEngine()
    engine.load_bytes(_outlined_document())
    model = PdfOutlineModel(engine, batch_size=1)

    assert model.rowCount(QModelIndex()) == 2
    root_a = model.index(0, 0)
    assert model.data(root_a) == "Root A"
    assert model.hasChildren(root_a)
    assert model.canFetchMore(root_a)

    model.fetchMore(root_a)
    assert model.rowCount(root_a) == 1
    assert model.canFetchMore(root_a)
    child_a1 = model.index(0, 0, root_a)
    assert model.data(child_a1) == "Child A1"
    assert model.entry_for_index(child_a1).page_index == 1
    assert model.parent(child_a1) == root_a

    model.fetchMore(root_a)
    assert model.rowCount(root_a) == 2
    assert not model.canFetchMore(root_a)
    engine.close()


def test_empty_outline_dictionary_is_treated_as_no_tree() -> None:
    _application()
    engine = PdfEngine()
    engine.load_bytes(_empty_outline_dictionary_document())

    assert engine.first_outline() is None
    model = PdfOutlineModel(engine)
    assert not model.has_entries
    assert model.rowCount(QModelIndex()) == 0
    engine.close()


def test_outline_click_navigates_to_bookmarked_page() -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(_outlined_document())
    window = MainWindow()
    window._activate_document(engine, Path("outlined.pdf"), already_saved=True)

    assert window.sidebar_tabs.isTabEnabled(window.outline_tab_index)
    assert window.sidebar_tabs.currentIndex() == window.outline_tab_index
    root_a = window._outline_model.index(0, 0)
    window._outline_model.fetchMore(root_a)
    child_a1 = window._outline_model.index(0, 0, root_a)
    window._outline_clicked(child_a1)
    assert window.current_page == 1
    assert window.page_list.currentRow() == 1

    window.close()
    window.deleteLater()
    app.processEvents()


def test_eplan_outline_is_lazy_and_preserves_view_rectangle() -> None:
    source = SAMPLES / "33-E00-01EKFA2A22_2018-03-16_CZ.pdf"
    if not source.exists():
        pytest.skip("The supplied EPLAN PDF fixture is not available.")
    _application()
    engine = PdfEngine()
    engine.open(source)

    started = time.perf_counter()
    model = PdfOutlineModel(engine)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0
    assert [model.data(model.index(row, 0)) for row in range(4)] == [
        "Strom stránek",
        "Seznam stránek",
        "Strom přístrojů",
        "Seznam přístrojů",
    ]

    device_list = model.index(3, 0)
    model.fetchMore(device_list)
    assert model.rowCount(device_list) == 128
    assert model.canFetchMore(device_list)
    first_device = model.entry_for_index(model.index(0, 0, device_list))
    assert first_device.page_index == 72
    assert first_device.target_rect is not None
    engine.close()
