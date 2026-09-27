import os
from io import BytesIO
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QPageRanges
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import QApplication, QToolBar

from openpdf_editor.app import _set_application_identity
from openpdf_editor.engine import PdfEngine, TextPlacement
import openpdf_editor.main_window as main_window_module
from openpdf_editor.main_window import MainWindow


def _application() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("Nettongia PDF Editor Tests")
    app.setApplicationName("Nettongia PDF Editor Tests")
    return app


def test_print_ranges_and_pdf_printer_output(tmp_path: Path) -> None:
    app = _application()
    window = MainWindow()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(595, 842, 2))
    window._activate_document(engine, Path("print-test.pdf"), already_saved=True)
    window.inserted_texts = [
        TextPlacement(
            key="print-text",
            page_index=0,
            bbox=(72, 72, 300, 120),
            text="Unsaved print test",
            font_size=24,
        )
    ]

    printer = QPrinter(QPrinter.HighResolution)
    printer.setPrintRange(QPrinter.AllPages)
    assert window._print_page_indices(printer) == [0, 1]
    window.current_page = 1
    printer.setPrintRange(QPrinter.CurrentPage)
    assert window._print_page_indices(printer) == [1]
    assert window._print_page_indices(printer, current_page=0) == [0]
    page_ranges = QPageRanges()
    page_ranges.addPage(2)
    printer.setPageRanges(page_ranges)
    printer.setPrintRange(QPrinter.PageRange)
    assert window._print_page_indices(printer) == [1]

    output_path = tmp_path / "printed.pdf"
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(output_path))
    printer.setResolution(72)

    assert window._render_print_job(printer, [0, 1]) == 2
    with pymupdf.open(output_path) as printed:
        assert printed.page_count == 2
        assert all(page.rect.width > 0 and page.rect.height > 0 for page in printed)
        first_page_pixels = printed[0].get_pixmap(dpi=72, alpha=False).samples
        assert min(first_page_pixels) < 128

    window.close()
    window.deleteLater()
    app.processEvents()


def test_print_to_pdf_keeps_vector_paths_and_unsaved_text(tmp_path: Path) -> None:
    app = _application()
    document = pymupdf.open()
    page = document.new_page(width=360, height=240)
    page.draw_rect(pymupdf.Rect(40, 40, 260, 180), color=(1, 0, 0), width=0.5)
    page.insert_text((50, 85), "Original", fontsize=18)
    engine = PdfEngine()
    engine.load_bytes(document.tobytes())
    document.close()
    window = MainWindow()
    window._activate_document(engine, Path("vector-print.pdf"), already_saved=True)
    window.inserted_texts = [
        TextPlacement(
            key="print-text", page_index=0,
            bbox=(50, 110, 280, 145), text="Unsaved vector", font_size=17,
        )
    ]
    output = tmp_path / "vector-print.pdf"
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(output))
    printer.setResolution(72)
    try:
        assert window._render_print_job(printer, [0]) == 1
        with pymupdf.open(output) as printed:
            assert printed[0].get_drawings()
            assert printed[0].get_images() == []
            assert min(printed[0].get_pixmap(dpi=144).samples) < 128
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_print_annotated_page_keeps_annotation_appearance(tmp_path: Path) -> None:
    app = _application()
    document = pymupdf.open()
    page = document.new_page(width=360, height=240)
    page.add_rect_annot(pymupdf.Rect(35, 35, 100, 95))
    engine = PdfEngine()
    engine.load_bytes(document.tobytes())
    document.close()
    window = MainWindow()
    window._activate_document(engine, Path("annotated.pdf"), already_saved=True)
    output = tmp_path / "annotation-print.pdf"
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(output))
    try:
        assert window._render_print_job(printer, [0]) == 1
        with pymupdf.open(output) as printed:
            assert printed[0].get_images()
            assert min(printed[0].get_pixmap(dpi=72).samples) < 200
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_vector_print_keeps_images_next_to_vector_art(tmp_path: Path) -> None:
    app = _application()
    image_stream = BytesIO()
    Image.new("RGB", (32, 32), (17, 115, 222)).save(image_stream, format="PNG")
    source = pymupdf.open()
    page = source.new_page(width=320, height=220)
    page.draw_circle((145, 70), 26, color=(1, 0, 0))
    page.insert_image(pymupdf.Rect(35, 115, 85, 165), stream=image_stream.getvalue())
    engine = PdfEngine()
    engine.load_bytes(source.tobytes())
    source.close()
    window = MainWindow()
    window._activate_document(engine, Path("mixed.pdf"), already_saved=True)
    output = tmp_path / "mixed-print.pdf"
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(str(output))
    try:
        window._render_print_job(printer, [0])
        with pymupdf.open(output) as printed:
            assert printed[0].get_drawings()
            assert printed[0].get_images()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_print_action_opens_application_preview(monkeypatch) -> None:
    app = _application()
    window = MainWindow()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(595, 842, 2))
    window._activate_document(engine, Path("preview-test.pdf"), already_saved=True)

    class PreviewSignal:
        callback = None

        def connect(self, callback) -> None:
            self.callback = callback

    class FakePreview:
        latest = None

        def __init__(self, printer, parent) -> None:
            self.printer = printer
            self.parent = parent
            self.paintRequested = PreviewSignal()
            self.title = ""
            FakePreview.latest = self

        def setWindowTitle(self, title: str) -> None:
            self.title = title

        def resize(self, width: int, height: int) -> None:
            self.size = (width, height)

        def findChildren(self, child_type) -> list:
            return []

        def exec(self) -> int:
            self.paintRequested.callback(self.printer)
            return 0

    rendered_pages = []
    monkeypatch.setattr(main_window_module, "QPrintPreviewDialog", FakePreview)
    monkeypatch.setattr(
        window,
        "_render_print_job",
        lambda printer, pages: rendered_pages.append(pages) or len(pages),
    )

    window.print_document()

    assert FakePreview.latest.title.startswith("Nettongia PDF Editor - ")
    assert FakePreview.latest.size == (1100, 800)
    assert rendered_pages == [[0, 1]]

    window.close()
    window.deleteLater()
    app.processEvents()


def test_print_dialog_title_and_application_identity(monkeypatch) -> None:
    app = _application()
    original_name = app.applicationName()
    original_display_name = app.applicationDisplayName()
    original_organization = app.organizationName()
    _set_application_identity()
    assert app.applicationName() == "Nettongia PDF Editor"
    assert app.applicationDisplayName() == "Nettongia PDF Editor"

    window = MainWindow()
    window.language_code = "cs"
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(595, 842, 1))
    window._activate_document(engine, Path("title-test.pdf"), already_saved=True)

    class FakePrintDialog:
        latest = None

        def __init__(self, printer, parent) -> None:
            self.title = ""
            FakePrintDialog.latest = self

        def setWindowTitle(self, title: str) -> None:
            self.title = title

        def setMinMax(self, first: int, last: int) -> None:
            pass

        def setFromTo(self, first: int, last: int) -> None:
            pass

        def setOption(self, option, enabled: bool) -> None:
            pass

        def exec(self) -> int:
            assert QApplication.testAttribute(Qt.AA_DontUseNativeDialogs)
            return 0

    monkeypatch.setattr(main_window_module, "QPrintDialog", FakePrintDialog)
    previous_non_native = QApplication.testAttribute(Qt.AA_DontUseNativeDialogs)
    window._print_from_preview(object(), QPrinter(QPrinter.HighResolution))
    assert FakePrintDialog.latest.title == "Nettongia PDF Editor - Tisk"
    assert (
        QApplication.testAttribute(Qt.AA_DontUseNativeDialogs)
        == previous_non_native
    )

    window.close()
    window.deleteLater()
    app.processEvents()
    app.setApplicationName(original_name)
    app.setApplicationDisplayName(original_display_name)
    app.setOrganizationName(original_organization)


def test_preview_print_button_uses_editor_print_flow(monkeypatch) -> None:
    app = _application()
    window = MainWindow()
    printer = QPrinter(QPrinter.HighResolution)
    preview = QPrintPreviewDialog(printer, window)
    calls = []
    monkeypatch.setattr(
        window,
        "_print_from_preview",
        lambda actual_preview, actual_printer: calls.append(
            (actual_preview, actual_printer)
        ),
    )

    window._redirect_preview_print_action(preview, printer)
    preview.findChildren(QToolBar)[0].actions()[-1].trigger()

    assert calls == [(preview, printer)]
    preview.close()
    window.close()
    window.deleteLater()
    app.processEvents()
