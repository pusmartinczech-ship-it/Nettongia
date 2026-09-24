from pathlib import Path
from xml.etree import ElementTree

from PIL import Image

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
        "file_new.svg", "file_open.svg", "file_close.svg",
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
    mascot = ROOT / "assets" / "nettongia_mascot_pdf.png"
    assert mascot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert mascot.stat().st_size > 100_000
    assert not (ROOT / "assets" / "app_logo.svg").exists()

    icon = ROOT / "assets" / "nettongia.ico"
    with Image.open(icon) as image:
        assert image.format == "ICO"
        assert {16, 24, 32, 48, 64, 128, 256}.issubset(
            {width for width, height in image.info["sizes"] if width == height}
        )

    website_mascot = ROOT / "website" / "assets" / "mascot.png"
    assert website_mascot.read_bytes() == mascot.read_bytes()
    assert not (ROOT / "website" / "assets" / "mascot.svg").exists()


def test_runtime_and_website_use_only_the_current_mascot() -> None:
    app_source = (ROOT / "openpdf_editor" / "app.py").read_text(encoding="utf-8")
    window_source = (ROOT / "openpdf_editor" / "main_window.py").read_text(
        encoding="utf-8"
    )
    assert "app_logo.svg" not in app_source + window_source
    assert "nettongia_mascot_pdf.png" in app_source
    assert "nettongia_mascot_pdf.png" in window_source
    for html in (ROOT / "website").rglob("*.html"):
        source = html.read_text(encoding="utf-8")
        assert "mascot.svg" not in source
