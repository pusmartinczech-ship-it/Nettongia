from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "nettongia_mascot_pdf.png"
WINDOWS_ICON = ROOT / "assets" / "nettongia.ico"
WEBSITE_MASCOT = ROOT / "website" / "assets" / "mascot.png"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def main() -> None:
    with Image.open(SOURCE) as source:
        mascot = source.convert("RGBA")
        if mascot.width != mascot.height or mascot.width < 256:
            raise ValueError("The approved mascot must be a square RGBA image.")
        mascot.save(
            WINDOWS_ICON,
            format="ICO",
            sizes=[(size, size) for size in ICON_SIZES],
            bitmap_format="png",
        )
    WEBSITE_MASCOT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE, WEBSITE_MASCOT)


if __name__ == "__main__":
    main()
