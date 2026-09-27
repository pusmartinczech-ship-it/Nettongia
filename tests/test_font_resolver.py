from pathlib import Path
import shutil

import fitz
from PIL import ImageFont

import openpdf_editor.font_resolver as font_resolver
from openpdf_editor.engine import PdfEngine, TextEdit
from openpdf_editor.text_layer import clean_pdf_font_name


def test_pdf_font_names_are_displayed_as_windows_families() -> None:
    assert clean_pdf_font_name("TimesNewRomanPS-BoldItalicMT") == "Times New Roman"
    assert clean_pdf_font_name("Arial-BoldMT") == "Arial"
    assert clean_pdf_font_name("ABCDEF+CourierNewPSMT") == "Courier New"


def test_windows_times_font_files_are_resolved_with_the_right_style(monkeypatch) -> None:
    names = (
        "times.ttf",
        "timesbd.ttf",
        "timesi.ttf",
        "timesbi.ttf",
        "arial.ttf",
        "arialbd.ttf",
        "ariali.ttf",
        "arialbi.ttf",
        "corbel.ttf",
        "corbelb.ttf",
        "corbeli.ttf",
        "corbelz.ttf",
    )
    files = {name: Path("C:/Windows/Fonts") / name for name in names}
    monkeypatch.setattr(font_resolver, "_font_files", lambda: files)

    assert font_resolver.resolve_font("TimesNewRomanPSMT") == str(files["times.ttf"])
    assert font_resolver.resolve_font("TimesNewRomanPS-BoldMT", True) == str(files["timesbd.ttf"])
    assert font_resolver.resolve_font("TimesNewRomanPS-ItalicMT", False, True) == str(files["timesi.ttf"])
    assert font_resolver.resolve_font("TimesNewRomanPS-BoldItalicMT", True, True) == str(files["timesbi.ttf"])
    assert font_resolver.resolve_font("Arial-BoldMT", True) == str(files["arialbd.ttf"])
    assert font_resolver.resolve_font("Arial-BoldItalicMT", True, True) == str(files["arialbi.ttf"])
    assert font_resolver.resolve_font("Corbel") == str(files["corbel.ttf"])
    assert font_resolver.resolve_font("Corbel", True, True) == str(files["corbelz.ttf"])


def test_abbreviated_font_is_used_in_rendered_and_saved_pdf(tmp_path, monkeypatch) -> None:
    # Read a real system font without relying on Qt's headless font database.
    files = font_resolver._font_files()
    source = next((files[name] for name in ("times.ttf", "DejaVuSerif.ttf".lower(),
                  "nimbusroman-regular.otf") if name in files), None)
    assert source is not None, "A serif font is required for the PDF rendering regression"
    font_path = tmp_path / "unrelated_filename.ttf"
    shutil.copyfile(source, font_path)
    family = ImageFont.truetype(str(font_path), 16).getname()[0]
    monkeypatch.setattr(font_resolver, "_font_files", lambda: {font_path.name: font_path})
    assert font_resolver.resolve_font(family) == str(font_path)

    with fitz.open() as original:
        original.new_page().insert_text((50, 100), "FONT CHANGE", fontsize=18)
        engine = PdfEngine()
        engine.load_bytes(original.tobytes())
    run = engine.text_runs(0)[0]
    edit = TextEdit(run=run, new_text=run.text, font_size=18, font_family=family)
    before = engine.render_page(0, 1)[0]
    after = engine.render_page(0, 1, [edit])[0]
    assert after != before
    with engine.build_document([edit]) as document:
        spans = [span for block in document[0].get_text("dict")["blocks"]
                 for line in block.get("lines", []) for span in line["spans"]]
        assert spans[0]["font"] != run.font_name
        embedded = [document.extract_font(entry[0])[3]
                    for entry in document.get_page_fonts(0)]
        assert font_path.read_bytes() in embedded
        saved = document.tobytes()
    with fitz.open(stream=saved, filetype="pdf") as reopened:
        assert bytes(reopened[0].get_pixmap(alpha=False).samples) == after
