#!/usr/bin/env python3
"""Run deterministic before/after visual regression checks."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openpdf_editor import __version__
from openpdf_editor.engine import ImagePlacement, PdfEngine, TextEdit, TextPlacement
from openpdf_editor.visual_regression import (
    changed_pixels_outside_regions,
    compare_documents,
    pdf_rect_to_pixels,
    render_pdf,
)


SCALE = 1.5


def _test_image() -> bytes:
    image = Image.new("RGBA", (180, 90), (0, 0, 0, 0))
    drawing = ImageDraw.Draw(image)
    drawing.rounded_rectangle((4, 4, 175, 85), 14, fill=(32, 112, 190, 220))
    drawing.polygon(((22, 68), (76, 18), (126, 70)), fill=(248, 205, 60, 255))
    stream = BytesIO()
    image.save(stream, format="PNG", optimize=False)
    return stream.getvalue()


def golden_fixture_bytes() -> bytes:
    document = pymupdf.open()
    document.set_metadata(
        {
            "title": "OpenPDF deterministic golden fixture",
            "author": "OpenPDF Editor",
            "creator": "OpenPDF Editor visual regression",
            "producer": "PyMuPDF",
            "creationDate": "D:20260910000000Z",
            "modDate": "D:20260910000000Z",
        }
    )
    image = _test_image()

    page = document.new_page(width=480, height=360)
    page.draw_rect((24, 24, 456, 336), color=(0.1, 0.2, 0.35), width=2)
    page.draw_circle((410, 70), 28, color=(0.8, 0.1, 0.1), fill=(1.0, 0.82, 0.2))
    page.draw_line((30, 185), (450, 185), color=(0.15, 0.55, 0.3), width=3)
    page.insert_text((48, 78), "GOLDEN ORIGINAL", fontsize=22, fontname="helv")
    page.insert_text((48, 108), "Vector, text, image and annotation", fontsize=11)
    page.insert_image((315, 215, 435, 275), stream=image, keep_proportion=True)
    annotation = page.add_rect_annot((42, 48, 275, 92))
    annotation.set_colors(stroke=(0.65, 0.2, 0.75))
    annotation.set_border(width=1.5)
    annotation.update(opacity=0.8)

    page = document.new_page(width=360, height=480)
    page.insert_text((45, 70), "ROTATED PAGE", fontsize=20)
    page.draw_rect((40, 100, 320, 420), color=(0.2, 0.2, 0.2), fill=(0.92, 0.95, 1.0))
    page.draw_polyline(((60, 350), (140, 170), (220, 330), (300, 140)), color=(0.8, 0.2, 0.15), width=4)
    page.insert_image((105, 215, 255, 290), stream=image)
    page.set_rotation(90)

    page = document.new_page(width=480, height=360)
    page.draw_rect((55, 55, 270, 210), fill=(0.15, 0.55, 0.85), fill_opacity=0.42)
    page.draw_rect((175, 125, 400, 280), fill=(0.9, 0.25, 0.2), fill_opacity=0.38)
    page.insert_text((70, 315), "TRANSPARENCY AND OVERLAP", fontsize=16, color=(0.1, 0.1, 0.1))
    try:
        return document.tobytes(garbage=4, deflate=True, no_new_id=True)
    finally:
        document.close()


def run_audit(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_bytes = golden_fixture_bytes()
    with tempfile.TemporaryDirectory(prefix="OpenPDFEditor-golden-") as temporary:
        root = Path(temporary)
        source_path = root / "golden-source.pdf"
        noop_path = root / "golden-noop.pdf"
        edited_path = root / "golden-edited.pdf"
        source_path.write_bytes(source_bytes)

        engine = PdfEngine()
        engine.load_bytes(source_bytes)
        try:
            engine.save(noop_path, [])
            run = next(item for item in engine.text_runs(0) if item.text == "GOLDEN ORIGINAL")
            inserted_text = TextPlacement(
                key="golden-inserted-text",
                page_index=0,
                bbox=(48, 205, 285, 250),
                text="EXPECTED LOCAL CHANGE",
                font_size=14,
                bold=True,
                color=0x174A8B,
            )
            inserted_image = ImagePlacement(
                key="golden-inserted-image",
                page_index=0,
                bbox=(300, 285, 430, 340),
                image_bytes=_test_image(),
                description="golden image",
                rotation_degrees=21.0,
            )
            edit = TextEdit(
                run=run,
                new_text="GOLDEN EDITED",
                font_size=run.font_size,
                fit_to_width=True,
            )
            engine.save(
                edited_path,
                [edit],
                inserted_images=[inserted_image],
                inserted_texts=[inserted_text],
            )
        finally:
            engine.close()

        noop_diffs = compare_documents(source_path, noop_path, scale=SCALE)
        before_page = render_pdf(source_path, scale=SCALE, page_indices=(0,))[0]
        after_page = render_pdf(edited_path, scale=SCALE, page_indices=(0,))[0]
        edit_diff = compare_documents(
            source_path, edited_path, scale=SCALE, page_indices=(0,)
        )[0]
        allowed_regions = tuple(
            pdf_rect_to_pixels(rect, scale=SCALE, padding=4)
            for rect in (run.bbox, inserted_text.bbox, inserted_image.bbox)
        )
        outside = changed_pixels_outside_regions(
            before_page,
            after_page,
            allowed_regions,
        )
        noop_exact = all(item.changed_pixels == 0 for item in noop_diffs)
        edit_local = edit_diff.changed_pixels > 0 and outside == 0
        report: dict[str, object] = {
            "format": "openpdf-editor-golden-audit",
            "version": __version__,
            "scale": SCALE,
            "status": "passed" if noop_exact and edit_local else "failed",
            "fixture": {
                "pages": 3,
                "features": [
                    "text",
                    "vector_graphics",
                    "raster_image",
                    "annotation",
                    "rotated_page",
                    "transparency",
                ],
            },
            "noop_save": {
                "exact": noop_exact,
                "pages": [item.to_dict() for item in noop_diffs],
            },
            "representative_edit": {
                "local_only": edit_local,
                "outside_changed_pixels": outside,
                "allowed_regions": allowed_regions,
                "page": edit_diff.to_dict(),
            },
        }

    json_path = output_dir / "golden_pdf_audit.json"
    md_path = output_dir / "golden_pdf_audit.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(
        "# Golden PDF visual regression\n\n"
        f"- Status: **{report['status']}**\n"
        f"- No-op save pixel exact: **{noop_exact}**\n"
        f"- Edited page changed pixels: **{edit_diff.changed_pixels}**\n"
        f"- Changed pixels outside allowed areas: **{outside}**\n"
        f"- Render scale: **{SCALE}**\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports") / "golden_pdf",
    )
    args = parser.parse_args()
    report = run_audit(args.output_dir)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
