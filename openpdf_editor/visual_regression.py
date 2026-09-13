from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

try:
    import pymupdf
except ImportError:  # PyMuPDF before 1.24
    import fitz as pymupdf


@dataclass(frozen=True)
class PageRaster:
    page_index: int
    width: int
    height: int
    stride: int
    samples: bytes


@dataclass(frozen=True)
class PixelDiff:
    page_index: int
    total_pixels: int
    changed_pixels: int
    changed_ratio: float
    mean_absolute_delta: float
    max_channel_delta: int
    changed_bbox: tuple[int, int, int, int] | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def render_pdf(
    source: str | Path | bytes,
    *,
    scale: float = 1.5,
    page_indices: Iterable[int] | None = None,
) -> tuple[PageRaster, ...]:
    if not 0.1 <= float(scale) <= 4.0:
        raise ValueError("Visual-regression scale is out of range.")
    document = (
        pymupdf.open(stream=source, filetype="pdf")
        if isinstance(source, bytes)
        else pymupdf.open(source)
    )
    try:
        indices = (
            tuple(range(document.page_count))
            if page_indices is None
            else tuple(page_indices)
        )
        if any(type(index) is not int or not 0 <= index < document.page_count for index in indices):
            raise ValueError("Visual-regression page index is out of range.")
        rasters: list[PageRaster] = []
        matrix = pymupdf.Matrix(scale, scale)
        for page_index in indices:
            pixmap = document[page_index].get_pixmap(
                matrix=matrix,
                alpha=False,
                annots=True,
                colorspace=pymupdf.csRGB,
            )
            rasters.append(
                PageRaster(
                    page_index=page_index,
                    width=pixmap.width,
                    height=pixmap.height,
                    stride=pixmap.stride,
                    samples=bytes(pixmap.samples),
                )
            )
        return tuple(rasters)
    finally:
        document.close()


def compare_rasters(before: PageRaster, after: PageRaster) -> PixelDiff:
    if (
        before.page_index != after.page_index
        or before.width != after.width
        or before.height != after.height
        or before.stride != after.stride
        or len(before.samples) != len(after.samples)
    ):
        raise ValueError("Rendered page geometry changed.")
    changed = 0
    absolute_delta = 0
    max_delta = 0
    min_x = before.width
    min_y = before.height
    max_x = -1
    max_y = -1
    for y in range(before.height):
        row = y * before.stride
        for x in range(before.width):
            offset = row + x * 3
            deltas = (
                abs(before.samples[offset + channel] - after.samples[offset + channel])
                for channel in range(3)
            )
            pixel_deltas = tuple(deltas)
            pixel_max = max(pixel_deltas)
            absolute_delta += sum(pixel_deltas)
            if pixel_max:
                changed += 1
                max_delta = max(max_delta, pixel_max)
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    total = before.width * before.height
    bbox = None if not changed else (min_x, min_y, max_x + 1, max_y + 1)
    return PixelDiff(
        page_index=before.page_index,
        total_pixels=total,
        changed_pixels=changed,
        changed_ratio=changed / max(1, total),
        mean_absolute_delta=absolute_delta / max(1, total * 3),
        max_channel_delta=max_delta,
        changed_bbox=bbox,
    )


def compare_documents(
    before: str | Path | bytes,
    after: str | Path | bytes,
    *,
    scale: float = 1.5,
    page_indices: Iterable[int] | None = None,
) -> tuple[PixelDiff, ...]:
    before_pages = render_pdf(before, scale=scale, page_indices=page_indices)
    after_pages = render_pdf(after, scale=scale, page_indices=page_indices)
    if len(before_pages) != len(after_pages):
        raise ValueError("Rendered page count changed.")
    return tuple(
        compare_rasters(reference, candidate)
        for reference, candidate in zip(before_pages, after_pages)
    )


def changed_pixels_outside_regions(
    before: PageRaster,
    after: PageRaster,
    regions: Iterable[tuple[int, int, int, int]],
) -> int:
    if (
        before.width != after.width
        or before.height != after.height
        or before.stride != after.stride
    ):
        raise ValueError("Rendered page geometry changed.")
    normalized = tuple(regions)
    outside = 0
    for y in range(before.height):
        row = y * before.stride
        for x in range(before.width):
            offset = row + x * 3
            if before.samples[offset : offset + 3] == after.samples[offset : offset + 3]:
                continue
            if not any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in normalized):
                outside += 1
    return outside


def pdf_rect_to_pixels(
    rect: tuple[float, float, float, float],
    *,
    scale: float,
    padding: int = 0,
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    return (
        max(0, int(x0 * scale) - padding),
        max(0, int(y0 * scale) - padding),
        int(x1 * scale + 0.999999) + padding,
        int(y1 * scale + 0.999999) + padding,
    )
