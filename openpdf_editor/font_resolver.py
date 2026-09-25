from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont


def _font_roots() -> list[Path]:
    roots: list[Path] = []
    windir = os.environ.get("WINDIR")
    if windir:
        roots.append(Path(windir) / "Fonts")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.append(Path(local_app_data) / "Microsoft/Windows/Fonts")
    roots.extend(
        [
            Path("/usr/share/fonts/truetype/msttcorefonts"),
            Path("/usr/share/fonts/truetype/dejavu"),
            Path("/usr/share/fonts/opentype/urw-base35"),
            Path("/Library/Fonts"),
        ]
    )
    return [path for path in roots if path.exists()]


@lru_cache(maxsize=1)
def _font_files() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for root in _font_roots():
        for pattern in ("*.ttf", "*.otf", "*.ttc"):
            for path in root.rglob(pattern):
                result.setdefault(path.name.lower(), path)
    return result


def _family_name(original_name: str) -> str:
    name = original_name.split("+")[-1].lower()
    name = re.sub(r"[^a-z0-9]+", "", name)
    name = re.sub(
        r"(?:bolditalic|boldoblique|semibolditalic|semibold|demibold|"
        r"bold|italic|oblique|regular)(?:mt)?$",
        "",
        name,
    )
    name = re.sub(r"(?:ps)?mt$", "", name)
    return name or "arial"


def _style_rank(remainder: str, bold: bool, italic: bool) -> int:
    """Rank a filename suffix without mistaking family letters for styles."""

    remainder = remainder.strip()
    bold_italic_alias = remainder in {"bi", "z", "bolditalic", "boldoblique"}
    has_bold = bold_italic_alias or remainder in {"b", "bd"} or any(
        marker in remainder
        for marker in ("bold", "demi", "semibold", "extrabold", "black")
    )
    has_italic = bold_italic_alias or remainder in {"i", "it"} or any(
        marker in remainder for marker in ("italic", "oblique")
    )
    mismatch = int(has_bold != bold) + int(has_italic != italic)
    regular = remainder in {"", "r", "rg", "regular", "roman", "book", "normal"}
    extra = 0 if mismatch == 0 else 100 * mismatch
    if not bold and not italic and not regular:
        extra += 10
    if any(marker in remainder for marker in ("mono", "narrow", "condensed", "light")):
        extra += 8
    return extra + len(remainder)


@lru_cache(maxsize=4096)
def _font_identity(path: str) -> tuple[str, str] | None:
    """Read the family and style independently of abbreviated filenames."""
    try:
        family, style = ImageFont.truetype(path, 16).getname()
    except (OSError, ValueError):
        return None
    return (
        _family_name(family),
        re.sub(r"[^a-z0-9]+", "", style.lower()),
    )


def resolve_font(original_name: str, bold: bool = False, italic: bool = False) -> str | None:
    """Return a broadly compatible system font that resembles the PDF font."""
    files = _font_files()
    # QFontComboBox may return names such as ``Nimbus Roman [urw]``.  Strip
    # punctuation for matching, but also recognise the URW metric-compatible
    # families explicitly so selecting a size or style does not unexpectedly
    # fall back to DejaVu Sans.
    normalized = re.sub(r"[^a-z0-9]+", "", original_name.lower())
    family_name = _family_name(original_name)

    # Qt presents internal family names, not filenames (e.g. Windows uses
    # cour.ttf for Courier New). Prefer an actual installed family before
    # considering metric-compatible substitutions or filename heuristics.
    exact: list[tuple[int, str]] = []
    for path in files.values():
        identity = _font_identity(str(path))
        if identity is not None and identity[0] == family_name:
            exact.append((_style_rank(identity[1], bold, italic), str(path)))
    if exact:
        return min(exact)[1]

    if "calibri" in normalized:
        families = ["calibri", "carlito", "dejavusans"]
    elif "nimbusroman" in normalized:
        families = ["nimbusroman", "timesnewroman", "liberationserif", "dejavuserif"]
    elif "nimbussans" in normalized:
        families = ["nimbussans", "arial", "liberationsans", "dejavusans"]
    elif "arial" in normalized or "helvetica" in normalized:
        families = ["arial", "liberationsans", "nimbussans", "dejavusans"]
    elif "times" in normalized or "serif" in normalized:
        # Windows ships Times New Roman as times.ttf / timesbd.ttf /
        # timesi.ttf / timesbi.ttf, not as timesnewroman*.ttf.
        families = ["timesnewroman", "times", "liberationserif", "nimbusroman", "dejavuserif"]
    elif "courier" in normalized or "mono" in normalized:
        families = ["couriernew", "liberationmono", "nimbusmono", "dejavusansmono"]
    else:
        families = [family_name, "arial", "liberationsans", "nimbussans", "dejavusans"]

    ranked: list[tuple[int, Path]] = []
    for filename, path in files.items():
        compact = re.sub(r"[^a-z0-9]+", "", Path(filename).stem.lower())
        family_match = next(
            (
                (index, family, compact.find(family))
                for index, family in enumerate(families)
                if family and family in compact
            ),
            None,
        )
        family_rank = family_match[0] if family_match is not None else None
        if family_rank is None:
            continue
        _, family, position = family_match
        remainder = compact[:position] + compact[position + len(family) :]
        style_rank = _style_rank(remainder, bold, italic)
        ranked.append((family_rank * 20 + style_rank, path))

    if ranked:
        ranked.sort(key=lambda item: (item[0], len(item[1].name)))
        return str(ranked[0][1])
    return None
