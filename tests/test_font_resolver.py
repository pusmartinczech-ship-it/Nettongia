from pathlib import Path

import openpdf_editor.font_resolver as font_resolver
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
