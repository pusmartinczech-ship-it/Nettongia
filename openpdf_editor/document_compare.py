from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from PIL import Image, ImageChops

try:
    import pymupdf
except ImportError:  # PyMuPDF before 1.24
    import fitz as pymupdf


COMPARISON_STATUSES = {
    "identical",
    "changed",
    "geometry",
    "current_only",
    "comparison_only",
}


@dataclass(frozen=True)
class PageComparison:
    page_index: int
    status: str
    changed_ratio: float = 0.0
    changed_pixels: int = 0
    total_pixels: int = 0
    changed_bbox: tuple[int, int, int, int] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> "PageComparison":
        if not isinstance(value, dict):
            raise ValueError("Invalid page-comparison result.")
        status = value.get("status")
        if status not in COMPARISON_STATUSES:
            raise ValueError("Invalid page-comparison status.")
        bbox = value.get("changed_bbox")
        if bbox is not None:
            if (
                not isinstance(bbox, (list, tuple))
                or len(bbox) != 4
                or any(type(item) is not int or item < 0 for item in bbox)
            ):
                raise ValueError("Invalid page-comparison bounding box.")
            bbox = tuple(bbox)
        try:
            page_index = int(value["page_index"])
            changed_ratio = float(value.get("changed_ratio", 0.0))
            changed_pixels = int(value.get("changed_pixels", 0))
            total_pixels = int(value.get("total_pixels", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid page-comparison result.") from exc
        if (
            page_index < 0
            or not 0.0 <= changed_ratio <= 1.0
            or changed_pixels < 0
            or total_pixels < 0
            or changed_pixels > total_pixels
        ):
            raise ValueError("Invalid page-comparison values.")
        return cls(
            page_index=page_index,
            status=str(status),
            changed_ratio=changed_ratio,
            changed_pixels=changed_pixels,
            total_pixels=total_pixels,
            changed_bbox=bbox,
        )


@dataclass(frozen=True)
class DocumentComparison:
    current_page_count: int
    comparison_page_count: int
    pages: tuple[PageComparison, ...]

    @property
    def changed_page_count(self) -> int:
        return sum(page.status != "identical" for page in self.pages)

    def to_dict(self) -> dict[str, object]:
        return {
            "current_page_count": self.current_page_count,
            "comparison_page_count": self.comparison_page_count,
            "pages": [page.to_dict() for page in self.pages],
        }

    @classmethod
    def from_dict(cls, value: object) -> "DocumentComparison":
        if not isinstance(value, dict) or not isinstance(value.get("pages"), list):
            raise ValueError("Invalid document-comparison result.")
        try:
            current_count = int(value["current_page_count"])
            comparison_count = int(value["comparison_page_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid document-comparison result.") from exc
        pages = tuple(PageComparison.from_dict(item) for item in value["pages"])
        if current_count < 0 or comparison_count < 0:
            raise ValueError("Invalid document-comparison page count.")
        if len(pages) != max(current_count, comparison_count):
            raise ValueError("Incomplete document-comparison result.")
        return cls(current_count, comparison_count, pages)


def _render_page(page: pymupdf.Page, *, max_pixels: int) -> Image.Image:
    area = max(1.0, page.rect.width * page.rect.height)
    scale = max(0.1, min(1.0, math.sqrt(max_pixels / area)))
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale),
        colorspace=pymupdf.csRGB,
        alpha=False,
        annots=True,
    )
    return Image.frombytes(
        "RGB",
        (pixmap.width, pixmap.height),
        bytes(pixmap.samples),
        "raw",
        "RGB",
        pixmap.stride,
        1,
    )


def compare_pdf_documents(
    current_pdf: bytes,
    comparison_pdf: bytes,
    *,
    pixel_threshold: int = 12,
    max_page_pixels: int = 1_500_000,
) -> DocumentComparison:
    """Compare rendered pages while ignoring insignificant channel noise."""

    if not 0 <= pixel_threshold <= 255:
        raise ValueError("The comparison pixel threshold is invalid.")
    if not 100_000 <= max_page_pixels <= 8_000_000:
        raise ValueError("The comparison render limit is invalid.")
    current = pymupdf.open(stream=current_pdf, filetype="pdf")
    other = pymupdf.open(stream=comparison_pdf, filetype="pdf")
    try:
        pages: list[PageComparison] = []
        for page_index in range(max(current.page_count, other.page_count)):
            if page_index >= current.page_count:
                pages.append(PageComparison(page_index, "comparison_only"))
                continue
            if page_index >= other.page_count:
                pages.append(PageComparison(page_index, "current_only"))
                continue
            current_page = current[page_index]
            other_page = other[page_index]
            if (
                abs(current_page.rect.width - other_page.rect.width) > 0.1
                or abs(current_page.rect.height - other_page.rect.height) > 0.1
            ):
                pages.append(PageComparison(page_index, "geometry"))
                continue
            current_image = _render_page(current_page, max_pixels=max_page_pixels)
            other_image = _render_page(other_page, max_pixels=max_page_pixels)
            if current_image.size != other_image.size:
                pages.append(PageComparison(page_index, "geometry"))
                continue
            difference = ImageChops.difference(current_image, other_image)
            channels = difference.split()
            maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
            mask = maximum.point(lambda value: 255 if value > pixel_threshold else 0)
            histogram = mask.histogram()
            changed_pixels = histogram[255]
            total_pixels = current_image.width * current_image.height
            bbox = mask.getbbox()
            pages.append(
                PageComparison(
                    page_index=page_index,
                    status="changed" if changed_pixels else "identical",
                    changed_ratio=changed_pixels / max(1, total_pixels),
                    changed_pixels=changed_pixels,
                    total_pixels=total_pixels,
                    changed_bbox=bbox,
                )
            )
        return DocumentComparison(current.page_count, other.page_count, tuple(pages))
    finally:
        current.close()
        other.close()
