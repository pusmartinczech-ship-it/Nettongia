import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from openpdf_editor.engine import PdfEngine
from openpdf_editor.main_window import MainWindow


def _application() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("OpenPDF Editor Tests")
    app.setApplicationName("OpenPDF Editor Tests")
    return app


def _large_blank_engine(page_count: int = 120) -> PdfEngine:
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300, page_count))
    return engine


def _wheel(view, delta: int) -> None:
    position = QPointF(view.viewport().rect().center())
    global_position = QPointF(view.viewport().mapToGlobal(position.toPoint()))
    event = QWheelEvent(
        position,
        global_position,
        QPoint(),
        QPoint(0, delta),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.NoScrollPhase,
        False,
    )
    view.wheelEvent(event)


def test_large_document_thumbnails_load_progressively() -> None:
    app = _application()
    window = MainWindow()
    window._activate_document(_large_blank_engine(), None, already_saved=True)

    assert window.page_list.count() == 120
    assert window.page_view.scene().items()
    assert len(window._thumbnail_queue) == 120
    assert window._thumbnail_timer.isActive()

    deadline = time.monotonic() + 5
    while window._thumbnail_queue and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 20)

    assert not window._thumbnail_queue
    assert not window._thumbnail_timer.isActive()
    assert all(not window.page_list.item(index).icon().isNull() for index in range(120))

    window.close()
    window.deleteLater()
    app.processEvents()


def test_closing_document_cancels_thumbnail_loading(monkeypatch) -> None:
    app = _application()
    window = MainWindow()
    window._activate_document(_large_blank_engine(80), None, already_saved=True)
    monkeypatch.setattr(window, "_maybe_save_changes", lambda: True)

    assert window._thumbnail_timer.isActive()
    assert window.close_document()
    assert not window._thumbnail_timer.isActive()
    assert not window._thumbnail_queue

    window.close()
    window.deleteLater()
    app.processEvents()


def test_main_view_wheel_scrolls_page_then_changes_pages() -> None:
    app = _application()
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window._activate_document(_large_blank_engine(3), None, already_saved=True)
    window.set_zoom_percent(400)
    app.processEvents()

    scroll_bar = window.page_view.verticalScrollBar()
    assert scroll_bar.maximum() > scroll_bar.minimum()
    scroll_bar.setValue(scroll_bar.minimum())

    _wheel(window.page_view, -120)
    assert window.current_page == 0
    assert scroll_bar.value() > scroll_bar.minimum()

    scroll_bar.setValue(scroll_bar.maximum())
    _wheel(window.page_view, -120)
    assert window.current_page == 1
    assert window.page_list.currentRow() == 1
    assert scroll_bar.value() == scroll_bar.minimum()

    _wheel(window.page_view, 120)
    assert window.current_page == 0
    assert window.page_list.currentRow() == 0
    assert scroll_bar.value() == scroll_bar.maximum()

    window.close()
    window.deleteLater()
    app.processEvents()


def test_high_zoom_refines_visible_area_with_tiles() -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(595.28, 841.89))
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window._activate_document(engine, None, already_saved=True)
    window.set_zoom_percent(400)

    deadline = time.monotonic() + 5
    while not window.page_view._tile_items and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)

    assert window.page_view._tile_items
    assert window.page_view._page_item is not None
    assert window.page_view._page_item.pixmap().width() < window.page_view.sceneRect().width()
    assert window.page_view._page_item.pixmap().height() < window.page_view.sceneRect().height()
    assert all(
        item.pixmap().width() <= 768 and item.pixmap().height() <= 768
        for item in window.page_view._tile_items.values()
    )
    assert 0 < window._tile_cache_bytes <= 96 * 1024 * 1024

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_tile_cache_survives_page_navigation_and_is_reused() -> None:
    app = _application()
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(595.28, 841.89, 2))
    window._activate_document(engine, None, already_saved=True)
    window.set_zoom_percent(400)

    deadline = time.monotonic() + 5
    while (window._tile_task is not None or not window.page_view._tile_items) and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
    page_zero_keys = {key for key in window._tile_cache if key[2] == 0}
    assert page_zero_keys

    window._select_and_render_page(1)
    deadline = time.monotonic() + 5
    while window._tile_task is not None and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
    assert page_zero_keys.issubset(window._tile_cache)

    hits_before = window._tile_cache_hits
    window._select_and_render_page(0)
    deadline = time.monotonic() + 5
    while window._tile_timer.isActive() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)

    assert window._tile_cache_hits > hits_before
    assert page_zero_keys.intersection(window.page_view._tile_items)

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_cancelling_tiles_clears_queued_runnables() -> None:
    app = _application()
    window = MainWindow()

    class PoolProbe:
        def __init__(self) -> None:
            self.clear_calls = 0
            self.wait_calls = 0

        def clear(self) -> None:
            self.clear_calls += 1

        def waitForDone(self) -> None:
            self.wait_calls += 1

    class TaskProbe:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    pool = PoolProbe()
    task = TaskProbe()
    window._tile_pool = pool
    window._tile_task = task

    window._cancel_tile_render(wait=True)

    assert task.cancelled
    assert pool.clear_calls == 1
    assert pool.wait_calls == 1
    window.deleteLater()
    app.processEvents()
