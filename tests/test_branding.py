from pathlib import Path
from xml.etree import ElementTree

from openpdf_editor.branding import APP_ID, APP_NAME, DISTRIBUTION_NAME, EXECUTABLE_NAME


ROOT = Path(__file__).resolve().parents[1]


def test_brand_identity_and_packaging_names_are_consistent() -> None:
    assert APP_NAME == "Nettongia PDF Editor"
    assert APP_ID == "Nettongia.PDFEditor"
    assert EXECUTABLE_NAME == "NettongiaPDFEditor"
    assert DISTRIBUTION_NAME == "Nettongia_PDF_Editor"
    spec = (ROOT / "OpenPDFEditor.spec").read_text(encoding="utf-8")
    installer = (ROOT / "installer" / "OpenPDFEditor.iss").read_text(encoding="utf-8")
    assert 'name="NettongiaPDFEditor"' in spec
    assert "Nettongia PDF Editor" in installer
    assert "NettongiaPDFEditor.exe" in installer
    assert "Nettongia_PDF_Editor_" in installer
    assert "3F9060A8-2B62-4F6D-BB67-D5C3D05D4057" in installer


def test_brand_and_toolbar_icons_are_valid_svg() -> None:
    names = (
        "app_logo.svg", "file_new.svg", "file_open.svg", "file_close.svg",
        "file_save.svg", "file_save_as.svg", "file_copy.svg", "print.svg",
        "compress.svg", "undo.svg", "redo.svg", "zoom_in.svg", "zoom_out.svg",
        "fit_width.svg", "page_add.svg", "page_remove.svg", "pages_import.svg",
        "image_add.svg", "image_remove.svg", "signature.svg", "text_add.svg",
        "text_remove.svg",
    )
    for name in names:
        root = ElementTree.parse(ROOT / "assets" / name).getroot()
        assert root.tag.endswith("svg")
        assert root.attrib["viewBox"]
    assert (ROOT / "assets" / "nettongia.ico").stat().st_size > 4096
    mascot = ROOT / "assets" / "nettongia_mascot_pdf.png"
    assert mascot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert mascot.stat().st_size > 100_000
