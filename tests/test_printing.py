import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
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
    app.setOrganizationName("OpenPDF Editor Tests")
    app.setApplicationName("OpenPDF Editor Tests")
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

    assert FakePreview.latest.title.startswith("OpenPDF Editor - ")
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
    assert app.applicationName() == "OpenPDF Editor"
    assert app.applicationDisplayName() == "OpenPDF Editor"

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
    assert FakePrintDialog.latest.title == "OpenPDF Editor - Tisk"
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
