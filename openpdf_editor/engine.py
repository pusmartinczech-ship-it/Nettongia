from __future__ import annotations

import math
import os
import tempfile
import zlib
from dataclasses import dataclass, field, replace
from io import BytesIO
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs

from PIL import Image

try:
    import pymupdf
except ImportError:  # PyMuPDF before 1.24
    import fitz as pymupdf

from .font_resolver import resolve_font


# Rendering a page creates an RGB buffer and Qt usually creates one or two
# additional copies while it turns that buffer into a QImage/QPixmap.  Keep a
# predictable upper bound so an A0 page at 400% cannot exhaust the process
# memory before the UI has a chance to react.
MAX_RENDER_PIXELS = 32_000_000


class PdfPasswordRequiredError(ValueError):
    """Raised when an encrypted PDF needs a password before it can be opened."""


class PdfInvalidPasswordError(ValueError):
    """Raised when a supplied PDF password was not accepted."""


def _normalized_text_direction(value: object) -> tuple[float, float]:
    """Return a safe unit vector for a PDF text baseline."""

    try:
        x, y = value  # type: ignore[misc]
        x = float(x)
        y = float(y)
    except (TypeError, ValueError):
        return 1.0, 0.0
    length = math.hypot(x, y)
    if not math.isfinite(length) or length < 1e-7:
        return 1.0, 0.0
    return x / length, y / length


def _builtin_pdf_font_name(font_family: str, bold: bool, italic: bool) -> str:
    """Choose a styled Base-14 fallback instead of always using Helvetica."""

    normalized = "".join(character for character in font_family.lower() if character.isalnum())
    if any(token in normalized for token in ("times", "roman", "serif")):
        return {
            (False, False): "tiro",
            (True, False): "tibo",
            (False, True): "tiit",
            (True, True): "tibi",
        }[(bold, italic)]
    if any(token in normalized for token in ("courier", "mono", "consolas")):
        return {
            (False, False): "cour",
            (True, False): "cobo",
            (False, True): "coit",
            (True, True): "cobi",
        }[(bold, italic)]
    return {
        (False, False): "helv",
        (True, False): "hebo",
        (False, True): "heit",
        (True, True): "hebi",
    }[(bold, italic)]


def _can_use_simple_font_encoding(text: str) -> bool:
    """Use a simple TrueType font when WinAnsi can represent the text.

    PyMuPDF's composite Identity-H mapping can expose ordinary spaces from
    some Windows system fonts (notably Arial) as U+00A0. A simple font keeps
    ASCII and Western-European text searchable with ordinary spaces. Other
    scripts retain the composite Unicode mapping.
    """

    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


@dataclass(frozen=True)
class TextRun:
    key: str
    page_index: int
    block_index: int
    line_index: int
    span_index: int
    text: str
    bbox: tuple[float, float, float, float]
    origin: tuple[float, float]
    font_name: str
    font_size: float
    color: int
    flags: int
    direction: tuple[float, float] = (1.0, 0.0)

    @property
    def bold(self) -> bool:
        return bool(self.flags & 16) or "bold" in self.font_name.lower()

    @property
    def italic(self) -> bool:
        return bool(self.flags & 2) or any(x in self.font_name.lower() for x in ("italic", "oblique"))


@dataclass(frozen=True)
class TextEdit:
    run: TextRun
    new_text: str
    font_size: float
    fit_to_width: bool = True
    font_family: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool = False
    color: int | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class TextPlacement:
    key: str
    page_index: int
    bbox: tuple[float, float, float, float]
    text: str
    font_family: str = "Arial"
    font_size: float = 12.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: int = 0


@dataclass(frozen=True)
class SignaturePlacement:
    page_index: int
    bbox: tuple[float, float, float, float]
    png_bytes: bytes
    description: str = "Visual signature"
    key: str = ""
    rotation_degrees: float = 0.0


@dataclass(frozen=True)
class ImageRun:
    key: str
    page_index: int
    bbox: tuple[float, float, float, float]
    xref: int
    width: int
    height: int
    smask: int = 0
    rotation_degrees: float = 0.0


@dataclass(frozen=True)
class ImagePlacement:
    key: str
    page_index: int
    bbox: tuple[float, float, float, float]
    image_bytes: bytes
    description: str = "Inserted image"
    rotation_degrees: float = 0.0
    overlay: bool = True


@dataclass(frozen=True)
class ImageDeletion:
    run: ImageRun
    fill_removed_area: bool = True


@dataclass(frozen=True)
class CompressionResult:
    original_size: int
    output_size: int
    recompressed_images: int


@dataclass(frozen=True)
class OutlineEntry:
    title: str
    page_index: int | None
    target_rect: tuple[float, float, float, float] | None
    has_children: bool
    _cursor: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class AnnotationInfo:
    """A stable, user-facing description of one native PDF annotation."""

    xref: int
    page_index: int
    type_name: str
    content: str
    author: str
    bbox: tuple[float, float, float, float]


class PdfEngine:
    def __init__(self) -> None:
        self.path: Path | None = None
        self._original_bytes: bytes | None = None
        self._source: pymupdf.Document | None = None
        self._runs: dict[int, list[TextRun]] = {}
        self._image_runs: dict[int, list[ImageRun]] = {}
        self._has_outline: bool | None = None
        self._was_encrypted = False

    @property
    def is_open(self) -> bool:
        return self._source is not None

    @property
    def page_count(self) -> int:
        return self._source.page_count if self._source else 0

    @property
    def source_bytes(self) -> bytes:
        self._require_open()
        return bytes(self._original_bytes)

    @property
    def was_encrypted(self) -> bool:
        return self._was_encrypted

    def close(self) -> None:
        if self._source is not None:
            self._source.close()
        self._source = None
        self._original_bytes = None
        self._runs.clear()
        self._image_runs.clear()
        self._has_outline = None
        self._was_encrypted = False
        self.path = None

    def open(self, path: str | Path, password: str | None = None) -> None:
        source_path = Path(path)
        self.load_bytes(source_path.read_bytes(), source_path, password=password)

    def load_bytes(
        self,
        data: bytes,
        path: str | Path | None = None,
        password: str | None = None,
    ) -> None:
        self.close()
        source = pymupdf.open(stream=bytes(data), filetype="pdf")
        was_encrypted = bool(source.needs_pass)
        try:
            if was_encrypted:
                if password is None:
                    raise PdfPasswordRequiredError("A password is required to open this PDF.")
                if not source.authenticate(password):
                    raise PdfInvalidPasswordError("The PDF password is incorrect.")
                # Retain no password in application state. A decrypted working
                # copy lets rendering, search, recovery and page operations use
                # the same code paths as ordinary documents.
                data = source.tobytes(
                    garbage=0,
                    clean=False,
                    deflate=False,
                    encryption=pymupdf.PDF_ENCRYPT_NONE,
                    use_objstms=0,
                )
                source.close()
                source = pymupdf.open(stream=data, filetype="pdf")
            if source.page_count < 1:
                raise ValueError("A PDF must contain at least one page.")
            self.path = Path(path) if path is not None else None
            self._original_bytes = bytes(data)
            self._source = source
            self._was_encrypted = was_encrypted
        except BaseException:
            source.close()
            raise

    def page_rect(self, page_index: int) -> pymupdf.Rect:
        self._require_open()
        return pymupdf.Rect(self._source[page_index].rect)

    def annotations(self) -> list[AnnotationInfo]:
        """Return native PDF annotations without keeping PyMuPDF proxies alive."""

        self._require_open()
        result: list[AnnotationInfo] = []
        for page_index in range(self._source.page_count):
            page = self._source[page_index]
            for annotation in page.annots() or ():
                info = annotation.info or {}
                rect = self._view_rect(page, annotation.rect)
                result.append(
                    AnnotationInfo(
                        xref=int(annotation.xref),
                        page_index=page_index,
                        type_name=str(annotation.type[1] or "Annotation"),
                        content=str(info.get("content") or ""),
                        author=str(info.get("title") or ""),
                        bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                    )
                )
        return result

    @staticmethod
    def _view_rect(
        page: pymupdf.Page,
        bbox: tuple[float, float, float, float] | pymupdf.Rect,
    ) -> pymupdf.Rect:
        """Map an unrotated PDF rectangle into the page's visible coordinates."""

        return pymupdf.Rect(bbox) * page.rotation_matrix

    @staticmethod
    def _page_rect_from_view(
        page: pymupdf.Page,
        bbox: tuple[float, float, float, float] | pymupdf.Rect,
    ) -> pymupdf.Rect:
        """Map a visible rectangle back into unrotated PDF coordinates."""

        return pymupdf.Rect(bbox) * page.derotation_matrix

    @staticmethod
    def _mapped_point(page: pymupdf.Page, point: object, *, to_view: bool) -> pymupdf.Point:
        matrix = page.rotation_matrix if to_view else page.derotation_matrix
        return pymupdf.Point(point) * matrix

    @staticmethod
    def _mapped_direction(
        page: pymupdf.Page,
        direction: tuple[float, float],
        *,
        to_view: bool,
    ) -> tuple[float, float]:
        matrix = page.rotation_matrix if to_view else page.derotation_matrix
        start = pymupdf.Point(0, 0) * matrix
        end = pymupdf.Point(direction) * matrix
        return _normalized_text_direction((end.x - start.x, end.y - start.y))

    def max_render_scale(
        self,
        page_index: int,
        max_pixels: int = MAX_RENDER_PIXELS,
    ) -> float:
        """Return the largest practical scale for a page.

        The value is deliberately based on pixels rather than a fixed zoom
        percentage: a 400% A4 render is harmless while a 400% A0 render can
        allocate more than a gigabyte during the Qt conversion step.
        """

        rect = self.page_rect(page_index)
        page_area = max(1.0, float(rect.width) * float(rect.height))
        pixel_budget = max(1, int(max_pixels))
        return max(0.25, min(4.0, (pixel_budget / page_area) ** 0.5))

    def first_outline(self) -> OutlineEntry | None:
        self._require_open()
        if self._has_outline is None:
            # PyMuPDF may expose an unusable Outline wrapper for a valid empty
            # /Outlines dictionary and then segfault when its ``down`` or
            # ``next`` property is read. A non-empty outline must have /First,
            # so validate that reference before touching Document.outline. This
            # remains constant-time for large EPLAN trees.
            outline_type, outline_value = self._source.xref_get_key(
                self._source.pdf_catalog(),
                "Outlines",
            )
            self._has_outline = False
            if outline_type == "xref":
                try:
                    outline_xref = int(outline_value.split()[0])
                    first_type, _ = self._source.xref_get_key(outline_xref, "First")
                    self._has_outline = first_type == "xref"
                except (IndexError, RuntimeError, TypeError, ValueError):
                    self._has_outline = False
        if not self._has_outline:
            return None
        cursor = self._source.outline
        return self._outline_entry(cursor) if cursor is not None else None

    def next_outline(self, entry: OutlineEntry) -> OutlineEntry | None:
        self._require_open()
        cursor = getattr(entry._cursor, "next", None)
        return self._outline_entry(cursor) if cursor is not None else None

    def child_outline(self, entry: OutlineEntry) -> OutlineEntry | None:
        self._require_open()
        cursor = getattr(entry._cursor, "down", None)
        return self._outline_entry(cursor) if cursor is not None else None

    def _outline_entry(self, cursor: object) -> OutlineEntry:
        page_number = int(getattr(cursor, "page", -1))
        page_index = page_number if 0 <= page_number < self.page_count else None
        target_rect = None
        try:
            query = parse_qs(str(getattr(cursor, "uri", "")).lstrip("#"))
            view_rect = query.get("viewrect", [None])[0]
            values = [float(value) for value in str(view_rect).split(",")]
            if len(values) == 4 and values[2] > 0 and values[3] > 0:
                x, y, width, height = values
                target_rect = (x, y, x + width, y + height)
        except (AttributeError, TypeError, ValueError):
            pass
        return OutlineEntry(
            title=str(getattr(cursor, "title", "") or "").strip() or "...",
            page_index=page_index,
            target_rect=target_rect,
            has_children=getattr(cursor, "down", None) is not None,
            _cursor=cursor,
        )

    def text_runs(self, page_index: int) -> list[TextRun]:
        self._require_open()
        if page_index in self._runs:
            return self._runs[page_index]

        page = self._source[page_index]
        page_dict = page.get_text("dict", sort=False)
        runs: list[TextRun] = []
        for block_index, block in enumerate(page_dict.get("blocks", [])):
            if block.get("type") != 0:
                continue
            for line_index, line in enumerate(block.get("lines", [])):
                direction = _normalized_text_direction(line.get("dir", (1.0, 0.0)))
                for span_index, span in enumerate(line.get("spans", [])):
                    text = span.get("text", "")
                    if not text.strip():
                        continue
                    key = f"{page_index}:{block_index}:{line_index}:{span_index}"
                    bbox = self._view_rect(page, tuple(float(v) for v in span["bbox"]))
                    origin = self._mapped_point(page, span["origin"], to_view=True)
                    runs.append(
                        TextRun(
                            key=key,
                            page_index=page_index,
                            block_index=block_index,
                            line_index=line_index,
                            span_index=span_index,
                            text=text,
                            bbox=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                            origin=(origin.x, origin.y),
                            font_name=str(span.get("font", "Helvetica")),
                            font_size=float(span.get("size", 11.0)),
                            color=int(span.get("color", 0)),
                            flags=int(span.get("flags", 0)),
                            direction=self._mapped_direction(page, direction, to_view=True),
                        )
                    )
        self._runs[page_index] = runs
        return runs

    def image_runs(self, page_index: int) -> list[ImageRun]:
        self._require_open()
        if page_index in self._image_runs:
            return self._image_runs[page_index]
        runs: list[ImageRun] = []
        masks = {
            int(item[0]): int(item[1])
            for item in self._source[page_index].get_images(full=True)
            if len(item) > 1
        }
        page = self._source[page_index]
        for occurrence, info in enumerate(page.get_image_info(xrefs=True)):
            bbox = self._view_rect(page, info.get("bbox", (0, 0, 0, 0)))
            if bbox.is_empty:
                continue
            runs.append(
                ImageRun(
                    key=f"image:{page_index}:{occurrence}",
                    page_index=page_index,
                    bbox=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                    xref=int(info.get("xref", 0)),
                    width=int(info.get("width", 0)),
                    height=int(info.get("height", 0)),
                    smask=masks.get(int(info.get("xref", 0)), 0),
                    rotation_degrees=(
                        self._image_rotation(info.get("transform"))
                        + float(page.rotation)
                        + 180.0
                    ) % 360.0 - 180.0,
                )
            )
        self._image_runs[page_index] = runs
        return runs

    @staticmethod
    def _image_rotation(transform: object) -> float:
        try:
            a, b, _c, _d, _e, _f = transform  # type: ignore[misc]
            angle = math.degrees(math.atan2(float(b), float(a)))
        except (TypeError, ValueError):
            return 0.0
        return (angle + 180.0) % 360.0 - 180.0

    def extract_image_payload(self, run: ImageRun) -> bytes:
        """Return the highest-fidelity reusable payload for one image.

        JPEG and other self-contained image streams are returned in their
        original encoding. Only an image with a separate PDF soft mask must be
        materialized as a lossless PNG so its transparency remains attached.
        """

        self._require_open()
        if not 0 <= run.page_index < self.page_count:
            raise ValueError("The source image page is unavailable.")
        if max(1, run.width) * max(1, run.height) > MAX_RENDER_PIXELS:
            raise ValueError(
                "The source image is too large for safe interactive editing."
            )
        if run.xref > 0:
            if run.smask <= 0:
                try:
                    extracted = self._source.extract_image(run.xref)
                    payload = extracted.get("image")
                    if isinstance(payload, (bytes, bytearray)) and payload:
                        return bytes(payload)
                except (RuntimeError, ValueError):
                    # Fall back to a lossless pixmap for unusual image object
                    # types that MuPDF cannot expose as a reusable stream.
                    pass
            base = pymupdf.Pixmap(self._source, run.xref)
            mask = None
            try:
                if run.smask > 0:
                    mask = pymupdf.Pixmap(self._source, run.smask)
                    combined = pymupdf.Pixmap(base, mask)
                    base = combined
                return base.tobytes("png")
            finally:
                mask = None
                base = None

        page = self._source[run.page_index]
        rect = self._page_rect_from_view(page, run.bbox)
        if rect.is_empty:
            raise ValueError("The source image has invalid geometry.")
        scale = min(
            4.0,
            max(
                1.0,
                run.width / max(1.0, rect.width),
                run.height / max(1.0, rect.height),
            ),
        )
        scale = min(
            scale,
            math.sqrt(MAX_RENDER_PIXELS / max(1.0, rect.width * rect.height)),
        )
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale),
            clip=rect,
            alpha=True,
            annots=False,
        )
        return pixmap.tobytes("png")

    def find_run(self, key: str) -> TextRun | None:
        try:
            page_index = int(key.split(":", 1)[0])
        except (ValueError, IndexError):
            return None
        return next((run for run in self.text_runs(page_index) if run.key == key), None)

    def find_image_run(self, key: str) -> ImageRun | None:
        try:
            page_index = int(key.split(":")[1])
        except (ValueError, IndexError):
            return None
        return next((run for run in self.image_runs(page_index) if run.key == key), None)

    def page_has_editable_text(self, page_index: int) -> bool:
        return bool(self.text_runs(page_index))

    def render_page(
        self,
        page_index: int,
        scale: float,
        edits: Iterable[TextEdit] = (),
        signatures: Iterable[SignaturePlacement] = (),
        inserted_images: Iterable[ImagePlacement] = (),
        deleted_images: Iterable[ImageDeletion] = (),
        inserted_texts: Iterable[TextPlacement] = (),
    ) -> tuple[bytes, int, int, int]:
        self._require_open()
        scale = min(4.0, max(0.25, float(scale)))
        scale = min(scale, self.max_render_scale(page_index))
        edits = tuple(edits)
        signatures = tuple(signatures)
        inserted_images = tuple(inserted_images)
        deleted_images = tuple(deleted_images)
        inserted_texts = tuple(inserted_texts)
        if not any(
            (
                edits,
                signatures,
                inserted_images,
                deleted_images,
                inserted_texts,
            )
        ):
            page = self._source[page_index]
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(scale, scale),
                alpha=False,
                annots=True,
            )
            return bytes(pixmap.samples), pixmap.width, pixmap.height, pixmap.stride

        document = self.build_document(
            edits,
            signatures,
            inserted_images,
            deleted_images,
            inserted_texts,
        )
        try:
            page = document[page_index]
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, annots=True)
            return bytes(pixmap.samples), pixmap.width, pixmap.height, pixmap.stride
        finally:
            document.close()

    def build_document(
        self,
        edits: Iterable[TextEdit] = (),
        signatures: Iterable[SignaturePlacement] = (),
        inserted_images: Iterable[ImagePlacement] = (),
        deleted_images: Iterable[ImageDeletion] = (),
        inserted_texts: Iterable[TextPlacement] = (),
    ) -> pymupdf.Document:
        self._require_open()
        document = pymupdf.open(stream=self._original_bytes, filetype="pdf")

        deletion_groups: dict[int, list[ImageDeletion]] = {}
        for deletion in deleted_images:
            deletion_groups.setdefault(deletion.run.page_index, []).append(deletion)
        for page_index, page_deletions in deletion_groups.items():
            if not 0 <= page_index < document.page_count:
                continue
            page = document[page_index]
            for deletion in page_deletions:
                page.add_redact_annot(
                    self._page_rect_from_view(page, deletion.run.bbox),
                    fill=(1, 1, 1) if deletion.fill_removed_area else False,
                    cross_out=False,
                )
            page.apply_redactions(images=1, graphics=0, text=1)

        edit_groups: dict[int, list[TextEdit]] = {}
        for edit in edits:
            edit_groups.setdefault(edit.run.page_index, []).append(edit)
        for page_index, page_edits in edit_groups.items():
            if not 0 <= page_index < document.page_count:
                continue
            page = document[page_index]
            page_space_edits: list[TextEdit] = []
            for edit in page_edits:
                run = edit.run
                run_bbox = self._page_rect_from_view(page, run.bbox)
                run_origin = self._mapped_point(page, run.origin, to_view=False)
                page_run = replace(
                    run,
                    bbox=(run_bbox.x0, run_bbox.y0, run_bbox.x1, run_bbox.y1),
                    origin=(run_origin.x, run_origin.y),
                    direction=self._mapped_direction(page, run.direction, to_view=False),
                )
                target_bbox = None
                if edit.bbox is not None:
                    target = self._page_rect_from_view(page, edit.bbox)
                    target_bbox = (target.x0, target.y0, target.x1, target.y1)
                page_edit = replace(edit, run=page_run, bbox=target_bbox)
                page_space_edits.append(page_edit)
                rect = self._redaction_rect(page_run, page.cropbox)
                page.add_redact_annot(rect, fill=(1, 1, 1), cross_out=False)
            page.apply_redactions(images=0, graphics=0, text=0)

            for ordinal, edit in enumerate(page_space_edits):
                if edit.new_text:
                    self._insert_edit(page, edit, ordinal)

        text_groups: dict[int, list[TextPlacement]] = {}
        for placement in inserted_texts:
            text_groups.setdefault(placement.page_index, []).append(placement)
        for page_index, page_texts in text_groups.items():
            if not 0 <= page_index < document.page_count:
                continue
            page = document[page_index]
            for ordinal, placement in enumerate(page_texts):
                if placement.text:
                    self._insert_text_placement(page, placement, ordinal)

        for image in inserted_images:
            self._insert_visual(
                document,
                image.page_index,
                image.bbox,
                image.image_bytes,
                overlay=image.overlay,
                rotation_degrees=image.rotation_degrees,
            )
        for signature in signatures:
            self._insert_visual(
                document,
                signature.page_index,
                signature.bbox,
                signature.png_bytes,
                rotation_degrees=signature.rotation_degrees,
            )
        return document

    def compose_bytes(
        self,
        edits: Iterable[TextEdit] = (),
        signatures: Iterable[SignaturePlacement] = (),
        inserted_images: Iterable[ImagePlacement] = (),
        deleted_images: Iterable[ImageDeletion] = (),
        inserted_texts: Iterable[TextPlacement] = (),
    ) -> bytes:
        document = self.build_document(
            edits,
            signatures,
            inserted_images,
            deleted_images,
            inserted_texts,
        )
        try:
            return self._serialize(document)
        finally:
            document.close()

    def save(
        self,
        path: str | Path,
        edits: Iterable[TextEdit],
        signatures: Iterable[SignaturePlacement] = (),
        inserted_images: Iterable[ImagePlacement] = (),
        deleted_images: Iterable[ImageDeletion] = (),
        inserted_texts: Iterable[TextPlacement] = (),
    ) -> None:
        document = self.build_document(
            edits,
            signatures,
            inserted_images,
            deleted_images,
            inserted_texts,
        )
        try:
            self._save_document_atomic(
                document,
                path,
                # Normal Save must not spend minutes deduplicating every
                # stream in a large CAD/EPLAN document. Garbage level 2 still
                # removes unreachable objects (including replaced content)
                # and compacts the xref table, while expensive duplicate-
                # stream analysis remains part of Compress PDF.
                garbage=2,
                clean=False,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                use_objstms=1,
            )
        finally:
            document.close()

    def save_compressed(
        self,
        path: str | Path,
        profile: str,
        edits: Iterable[TextEdit] = (),
        signatures: Iterable[SignaturePlacement] = (),
        inserted_images: Iterable[ImagePlacement] = (),
        deleted_images: Iterable[ImageDeletion] = (),
        inserted_texts: Iterable[TextPlacement] = (),
    ) -> CompressionResult:
        document = self.build_document(
            edits,
            signatures,
            inserted_images,
            deleted_images,
            inserted_texts,
        )
        recompressed = 0
        try:
            logical_original_size = len(self._serialize(document))
            if profile == "balanced":
                recompressed = self._recompress_images(document, target_dpi=150, jpeg_quality=74)
            elif profile == "strong":
                recompressed = self._recompress_images(document, target_dpi=105, jpeg_quality=52)
            elif profile != "lossless":
                raise ValueError(f"Unknown compression profile: {profile}")
            self._save_document_atomic(
                document,
                path,
                garbage=4,
                clean=True,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                use_objstms=1,
                compression_effort=100,
            )
        finally:
            document.close()
        return CompressionResult(
            original_size=logical_original_size,
            output_size=Path(path).stat().st_size,
            recompressed_images=recompressed,
        )

    @staticmethod
    def blank_document_bytes(width: float, height: float, page_count: int = 1) -> bytes:
        if width < 36 or height < 36:
            raise ValueError("Page dimensions must be at least 36 points.")
        if not 1 <= page_count <= 1000:
            raise ValueError("Page count must be between 1 and 1000.")
        document = pymupdf.open()
        try:
            document.set_metadata(
                {
                    "creator": "Nettongia PDF Editor",
                    "producer": "Nettongia PDF Editor 0.19.0",
                }
            )
            for _ in range(page_count):
                document.new_page(width=float(width), height=float(height))
            return PdfEngine._serialize(document)
        finally:
            document.close()

    def bytes_with_blank_page(self, after_page: int) -> bytes:
        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            reference = document[after_page].rect
            document.new_page(pno=after_page + 1, width=reference.width, height=reference.height)
            return self._serialize(document)
        finally:
            document.close()

    def bytes_with_pdf_inserted(
        self,
        after_page: int,
        source_path: str | Path,
        password: str | None = None,
    ) -> tuple[bytes, int]:
        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        source = pymupdf.open(str(source_path))
        try:
            if source.needs_pass:
                if password is None:
                    raise PdfPasswordRequiredError(
                        "A password is required to open the selected PDF."
                    )
                if not source.authenticate(password):
                    raise PdfInvalidPasswordError("The PDF password is incorrect.")
            count = source.page_count
            document.insert_pdf(source, start_at=after_page + 1)
            return self._serialize(document), count
        finally:
            source.close()
            document.close()

    def bytes_without_page(self, page_index: int) -> bytes:
        if self.page_count <= 1:
            raise ValueError("A PDF must contain at least one page.")
        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            document.delete_page(page_index)
            return self._serialize(document)
        finally:
            document.close()

    def bytes_with_page_moved(self, page_index: int, target_index: int) -> bytes:
        if not 0 <= page_index < self.page_count:
            raise IndexError("The source page is unavailable.")
        if not 0 <= target_index < self.page_count:
            raise IndexError("The target page position is unavailable.")
        if page_index == target_index:
            return self.source_bytes
        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            # PyMuPDF's ``to`` is an insertion point before a page, while this
            # API accepts the final zero-based page index.
            destination = target_index
            if page_index < target_index:
                destination = -1 if target_index == self.page_count - 1 else target_index + 1
            document.move_page(page_index, destination)
            # Page movement changes the page tree but does not require the
            # expensive whole-document duplicate-stream cleanup used by
            # `_serialize`. Keep this interactive even for CAD/EPLAN files.
            return document.tobytes(
                garbage=2,
                clean=False,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                use_objstms=1,
            )
        finally:
            document.close()

    def bytes_with_page_rotated(self, page_index: int, quarter_turns: int) -> bytes:
        """Return the PDF with one page rotated in 90-degree increments."""

        if not 0 <= page_index < self.page_count:
            raise IndexError("The page is unavailable.")
        turns = int(quarter_turns)
        if turns == 0 or turns % 4 == 0:
            return self.source_bytes
        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            page = document[page_index]
            page.set_rotation((int(page.rotation) + turns * 90) % 360)
            return document.tobytes(
                garbage=2,
                clean=False,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                use_objstms=1,
            )
        finally:
            document.close()

    def bytes_with_text_comment(
        self,
        page_index: int,
        point: tuple[float, float],
        content: str,
        *,
        author: str = "",
    ) -> bytes:
        """Return a PDF containing a native sticky-note annotation."""

        if not 0 <= page_index < self.page_count:
            raise IndexError("The page is unavailable.")
        if not content.strip():
            raise ValueError("A comment cannot be empty.")
        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            page = document[page_index]
            view_point = pymupdf.Point(float(point[0]), float(point[1]))
            page_point = self._mapped_point(page, view_point, to_view=False)
            annotation = page.add_text_annot(page_point, content.strip())
            annotation.set_info(
                title=author.strip(),
                content=content.strip(),
                subject="Nettongia comment",
            )
            annotation.update()
            return self._serialize(document)
        finally:
            document.close()

    def bytes_with_highlight(
        self,
        page_index: int,
        bbox: tuple[float, float, float, float],
        *,
        content: str = "",
        author: str = "",
    ) -> bytes:
        """Return a PDF containing a native yellow highlight annotation."""

        if not 0 <= page_index < self.page_count:
            raise IndexError("The page is unavailable.")
        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            page = document[page_index]
            view_rect = pymupdf.Rect(bbox) & page.rect
            if view_rect.is_empty or view_rect.width < 0.5 or view_rect.height < 0.5:
                raise ValueError("The selected text area is unavailable.")
            # A plain Rect loses the text-baseline direction on rotated pages.
            # Preserve the visible corner order in an explicit Quad so the
            # highlight remains horizontal to the user.
            quad = pymupdf.Quad(
                self._mapped_point(page, view_rect.top_left, to_view=False),
                self._mapped_point(page, view_rect.top_right, to_view=False),
                self._mapped_point(page, view_rect.bottom_left, to_view=False),
                self._mapped_point(page, view_rect.bottom_right, to_view=False),
            )
            annotation = page.add_highlight_annot(quad)
            annotation.set_info(
                title=author.strip(),
                content=content.strip(),
                subject="Nettongia highlight",
            )
            annotation.set_colors(stroke=(1.0, 0.82, 0.0))
            annotation.update(opacity=0.45)
            return self._serialize(document)
        finally:
            document.close()

    def bytes_with_annotation_content(
        self,
        annotation_xref: int,
        content: str,
    ) -> bytes:
        """Return a PDF with one annotation's comment text changed."""

        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            for page in document:
                for annotation in page.annots() or ():
                    if int(annotation.xref) != int(annotation_xref):
                        continue
                    info = annotation.info or {}
                    annotation.set_info(
                        title=str(info.get("title") or ""),
                        content=content.strip(),
                        subject=str(info.get("subject") or ""),
                    )
                    annotation.update()
                    return self._serialize(document)
            raise ValueError("The annotation is no longer available.")
        finally:
            document.close()

    def bytes_without_annotation(self, annotation_xref: int) -> bytes:
        """Return a PDF with one native annotation removed."""

        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            for page in document:
                for annotation in page.annots() or ():
                    if int(annotation.xref) == int(annotation_xref):
                        page.delete_annot(annotation)
                        return self._serialize(document)
            raise ValueError("The annotation is no longer available.")
        finally:
            document.close()

    @staticmethod
    def _serialize(document: pymupdf.Document) -> bytes:
        return document.tobytes(
            garbage=4,
            clean=True,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            use_objstms=1,
        )

    @staticmethod
    def _save_document_atomic(
        document: pymupdf.Document,
        path: str | Path,
        **save_options: object,
    ) -> None:
        """Save through a sibling temporary file and replace the target.

        A failed or interrupted PyMuPDF save must never leave a truncated PDF
        at the user's original path.  ``os.replace`` is atomic on the local
        filesystems supported by the desktop application.
        """

        target = Path(path)
        temporary_name: str | None = None
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)
        try:
            document.save(str(temporary_path), **save_options)
            PdfEngine._validate_saved_pdf(
                temporary_path,
                expected_page_count=document.page_count,
            )
            if target.exists():
                try:
                    temporary_path.chmod(target.stat().st_mode & 0o777)
                except OSError:
                    pass
            os.replace(temporary_path, target)
        except BaseException:
            try:
                temporary_path.unlink()
            except OSError:
                pass
            raise

    @staticmethod
    def _validate_saved_pdf(path: str | Path, *, expected_page_count: int) -> None:
        """Reopen and render representative pages before publishing a save."""

        verification = pymupdf.open(path)
        try:
            if verification.page_count != expected_page_count or verification.page_count < 1:
                raise ValueError("The saved PDF has an unexpected page count.")
            for page_index in dict.fromkeys(
                (0, verification.page_count // 2, verification.page_count - 1)
            ):
                page = verification[page_index]
                area = max(1.0, page.rect.width * page.rect.height)
                scale = min(0.35, max(0.05, math.sqrt(750_000 / area)))
                page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale),
                    alpha=False,
                    annots=True,
                )
        finally:
            verification.close()

    @staticmethod
    def _insert_visual(
        document: pymupdf.Document,
        page_index: int,
        bbox: tuple[float, float, float, float],
        payload: bytes,
        *,
        overlay: bool = True,
        rotation_degrees: float = 0.0,
    ) -> None:
        if not 0 <= page_index < document.page_count:
            return
        page = document[page_index]
        view_rect = pymupdf.Rect(bbox) & page.rect
        rect = PdfEngine._page_rect_from_view(page, view_rect)
        if rect.is_empty or rect.width < 1 or rect.height < 1:
            return
        # Placement rotations are expressed exactly as the user sees them.
        # PDF drawing commands use the unrotated page coordinate space, so
        # compensate for the page's /Rotate value before inserting the image.
        angle = (
            float(rotation_degrees) - float(page.rotation) + 180.0
        ) % 360.0 - 180.0
        nearest_quarter_turn = round(angle / 90.0) * 90.0
        if abs(angle - nearest_quarter_turn) < 0.01:
            # PDF handles quarter turns through the placement matrix. Keeping
            # the original stream avoids both JPEG transcoding and resampling.
            page.insert_image(
                rect,
                stream=payload,
                keep_proportion=True,
                overlay=overlay,
                rotate=int((-nearest_quarter_turn) % 360),
            )
            return
        page.insert_image(
            rect,
            stream=PdfEngine._rotated_visual_payload(payload, angle),
            keep_proportion=True,
            overlay=overlay,
        )

    @staticmethod
    def _rotated_visual_payload(payload: bytes, rotation_degrees: float) -> bytes:
        angle = float(rotation_degrees) % 360.0
        if min(angle, 360.0 - angle) < 0.01:
            return payload
        try:
            image = Image.open(BytesIO(payload)).convert("RGBA")
            image.load()
        except Exception:
            return payload
        rotated = image.rotate(
            -angle,
            expand=True,
            resample=Image.Resampling.BICUBIC,
            fillcolor=(255, 255, 255, 0),
        )
        output = BytesIO()
        rotated.save(output, format="PNG", optimize=True)
        return output.getvalue()

    @staticmethod
    def _rotated_signature_payload(signature: SignaturePlacement) -> bytes:
        """Compatibility wrapper retained for older callers and tests."""

        return PdfEngine._rotated_visual_payload(
            signature.png_bytes, signature.rotation_degrees
        )

    @staticmethod
    def _redaction_rect(run: TextRun, page_rect: pymupdf.Rect) -> pymupdf.Rect:
        rect = pymupdf.Rect(run.bbox)
        rect.x0 = max(page_rect.x0, rect.x0 - 0.35)
        rect.y0 = max(page_rect.y0, rect.y0 - 0.35)
        rect.x1 = min(page_rect.x1, rect.x1 + 0.35)
        rect.y1 = min(page_rect.y1, rect.y1 + 0.35)
        return rect

    def _insert_edit(self, page: pymupdf.Page, edit: TextEdit, ordinal: int) -> None:
        run = edit.run
        bold = run.bold if edit.bold is None else edit.bold
        italic = run.italic if edit.italic is None else edit.italic
        font_family = edit.font_family or run.font_name
        font_file = resolve_font(font_family, bold, italic)
        fallback_font_name = _builtin_pdf_font_name(font_family, bold, italic)
        simple_font = bool(font_file and _can_use_simple_font_encoding(edit.new_text))
        font_name = (
            self._font_resource_name(font_file, simple=simple_font)
            if font_file
            else fallback_font_name
        )
        font_size = max(3.0, float(edit.font_size))
        target_bbox = edit.bbox or run.bbox
        direction = _normalized_text_direction(run.direction)
        lines = edit.new_text.splitlines() or [edit.new_text]
        text_width = 0.0

        if font_file:
            try:
                font = pymupdf.Font(fontfile=font_file)
            except Exception:
                font_file = None
                font_name = fallback_font_name
            else:
                text_width = max(
                    (font.text_length(line, fontsize=font_size) for line in lines),
                    default=0.0,
                )
                if edit.fit_to_width:
                    available = self._text_axis_extent(target_bbox, direction)
                    if text_width > available:
                        font_size = max(3.0, font_size * available / text_width)
                        text_width = max(
                            (font.text_length(line, fontsize=font_size) for line in lines),
                            default=0.0,
                        )

        if not font_file:
            font_name = fallback_font_name
            font_file = None
            text_width = max(
                (
                    pymupdf.get_text_length(line, fontname=font_name, fontsize=font_size)
                    for line in lines
                ),
                default=0.0,
            )
            if edit.fit_to_width:
                available = self._text_axis_extent(target_bbox, direction)
                if text_width > available:
                    font_size = max(3.0, font_size * available / text_width)
                    text_width = max(
                        (
                            pymupdf.get_text_length(
                                line,
                                fontname=font_name,
                                fontsize=font_size,
                            )
                            for line in lines
                        ),
                        default=0.0,
                    )

        color = self._pdf_color(run.color if edit.color is None else edit.color)
        insertion_point = self._directed_insertion_point(run, target_bbox, font_size)
        angle = math.degrees(math.atan2(-direction[1], direction[0]))
        normalized_angle = (angle + 180.0) % 360.0 - 180.0
        morph = None
        if abs(normalized_angle) >= 0.001:
            morph = (insertion_point, pymupdf.Matrix(normalized_angle))
        page.insert_text(
            insertion_point,
            lines if len(lines) > 1 else edit.new_text,
            fontsize=font_size,
            lineheight=1.15,
            fontname=font_name,
            fontfile=font_file,
            set_simple=int(simple_font),
            color=color,
            morph=morph,
            overlay=True,
        )
        if edit.underline:
            normal = (-direction[1], direction[0])
            underline_offset = max(0.8, font_size * 0.08)
            line_step = font_size * 1.15
            for line_index, line in enumerate(lines):
                if not line:
                    continue
                if font_file:
                    try:
                        line_width = font.text_length(line, fontsize=font_size)
                    except Exception:
                        line_width = pymupdf.get_text_length(
                            line,
                            fontname=fallback_font_name,
                            fontsize=font_size,
                        )
                else:
                    line_width = pymupdf.get_text_length(
                        line,
                        fontname=font_name,
                        fontsize=font_size,
                    )
                normal_distance = line_index * line_step + underline_offset
                start = pymupdf.Point(
                    insertion_point.x + normal[0] * normal_distance,
                    insertion_point.y + normal[1] * normal_distance,
                )
                end = pymupdf.Point(
                    start.x + direction[0] * line_width,
                    start.y + direction[1] * line_width,
                )
                page.draw_line(
                    start,
                    end,
                    color=color,
                    width=max(0.45, font_size * 0.045),
                    overlay=True,
                )

    @staticmethod
    def _text_axis_extent(
        bbox: tuple[float, float, float, float],
        direction: tuple[float, float],
    ) -> float:
        width = max(0.0, bbox[2] - bbox[0])
        height = max(0.0, bbox[3] - bbox[1])
        return max(1.0, abs(direction[0]) * width + abs(direction[1]) * height)

    @staticmethod
    def _directed_insertion_point(
        run: TextRun,
        target_bbox: tuple[float, float, float, float],
        font_size: float,
    ) -> pymupdf.Point:
        """Move a baseline origin while retaining its direction and inset.

        PDF span rectangles are axis-aligned even for rotated text.  Working
        in the baseline / normal coordinate system preserves the exact origin
        for an unchanged box and also behaves predictably when that box is
        moved or resized.
        """

        direction = _normalized_text_direction(run.direction)
        normal = (-direction[1], direction[0])

        def minimum_projection(
            bbox: tuple[float, float, float, float],
            vector: tuple[float, float],
        ) -> float:
            x0, y0, x1, y1 = bbox
            return min(
                x * vector[0] + y * vector[1]
                for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))
            )

        origin = run.origin
        size_ratio = font_size / max(0.01, run.font_size)
        along_inset = (
            origin[0] * direction[0]
            + origin[1] * direction[1]
            - minimum_projection(run.bbox, direction)
        ) * size_ratio
        normal_inset = (
            origin[0] * normal[0]
            + origin[1] * normal[1]
            - minimum_projection(run.bbox, normal)
        ) * size_ratio
        along = minimum_projection(target_bbox, direction) + along_inset
        across = minimum_projection(target_bbox, normal) + normal_inset
        return pymupdf.Point(
            direction[0] * along + normal[0] * across,
            direction[1] * along + normal[1] * across,
        )

    def _insert_text_placement(
        self,
        page: pymupdf.Page,
        placement: TextPlacement,
        ordinal: int,
        prefix: str = "OPDFT",
    ) -> None:
        font_size = max(3.0, float(placement.font_size))
        font_file = resolve_font(placement.font_family, placement.bold, placement.italic)
        fallback_font_name = _builtin_pdf_font_name(
            placement.font_family,
            placement.bold,
            placement.italic,
        )
        simple_font = bool(font_file and _can_use_simple_font_encoding(placement.text))
        font_name = (
            self._font_resource_name(font_file, simple=simple_font)
            if font_file
            else fallback_font_name
        )
        if font_file:
            try:
                font = pymupdf.Font(fontfile=font_file)
            except Exception:
                font_file = None
                font = pymupdf.Font(fallback_font_name)
                font_name = fallback_font_name
        else:
            font = pymupdf.Font(fallback_font_name)
            font_name = fallback_font_name

        view_rect = pymupdf.Rect(placement.bbox) & page.rect
        rect = self._page_rect_from_view(page, view_rect)
        if rect.width < 1 or rect.height < 1:
            return
        page_rotation = int(page.rotation) % 360
        # PyMuPDF's textbox rotation is counter-clockwise in the unrotated
        # page coordinate system. Matching the page's clockwise /Rotate value
        # keeps newly entered text upright in the visible page.
        text_rotation = page_rotation
        color = self._pdf_color(placement.color)
        remaining = -1.0
        attempted_size = font_size
        while attempted_size >= 3.0:
            remaining = page.insert_textbox(
                rect,
                placement.text,
                fontsize=attempted_size,
                fontname=font_name,
                fontfile=font_file,
                set_simple=int(simple_font),
                color=color,
                lineheight=1.15,
                align=pymupdf.TEXT_ALIGN_LEFT,
                rotate=text_rotation,
                overlay=True,
            )
            if remaining >= 0:
                font_size = attempted_size
                break
            if attempted_size <= 3.0:
                break
            attempted_size = max(3.0, attempted_size * 0.88)

        if remaining < 0:
            page.insert_text(
                pymupdf.Point(rect.x0, rect.y0 + font_size),
                placement.text,
                fontsize=font_size,
                fontname=font_name,
                fontfile=font_file,
                set_simple=int(simple_font),
                color=color,
                rotate=text_rotation,
                overlay=True,
            )

        if placement.underline:
            baseline = view_rect.y0 + font_size
            line_step = font_size * 1.15
            for line in placement.text.splitlines() or [placement.text]:
                if baseline > view_rect.y1:
                    break
                try:
                    line_width = font.text_length(line, fontsize=font_size)
                except Exception:
                    line_width = pymupdf.get_text_length(line, fontname="helv", fontsize=font_size)
                underline_y = baseline + max(0.8, font_size * 0.08)
                start = self._mapped_point(
                    page,
                    pymupdf.Point(view_rect.x0, underline_y),
                    to_view=False,
                )
                end = self._mapped_point(
                    page,
                    pymupdf.Point(
                        min(view_rect.x1, view_rect.x0 + line_width),
                        underline_y,
                    ),
                    to_view=False,
                )
                page.draw_line(
                    start,
                    end,
                    color=color,
                    width=max(0.45, font_size * 0.045),
                    overlay=True,
                )
                baseline += line_step

    @staticmethod
    def _pdf_color(value: int) -> tuple[float, float, float]:
        return (
            ((value >> 16) & 255) / 255.0,
            ((value >> 8) & 255) / 255.0,
            (value & 255) / 255.0,
        )

    @staticmethod
    def _font_resource_name(font_file: str, *, simple: bool = False) -> str:
        checksum = zlib.crc32(font_file.encode("utf-8")) & 0xFFFFFFFF
        return f"OPDF{checksum:08x}{'S' if simple else 'U'}"

    @staticmethod
    def _recompress_images(document: pymupdf.Document, target_dpi: int, jpeg_quality: int) -> int:
        occurrences: dict[int, dict[str, float | int]] = {}
        for page_index, page in enumerate(document):
            for info in page.get_image_info(xrefs=True):
                xref = int(info.get("xref", 0))
                if xref <= 0:
                    continue
                bbox = pymupdf.Rect(info.get("bbox", (0, 0, 0, 0)))
                if bbox.is_empty:
                    continue
                target_width = max(1, round(bbox.width * target_dpi / 72))
                target_height = max(1, round(bbox.height * target_dpi / 72))
                entry = occurrences.setdefault(
                    xref,
                    {"page": page_index, "target_width": 1, "target_height": 1},
                )
                entry["target_width"] = max(int(entry["target_width"]), target_width)
                entry["target_height"] = max(int(entry["target_height"]), target_height)

        changed = 0
        for xref, occurrence in occurrences.items():
            try:
                extracted = document.extract_image(xref)
                if not extracted or extracted.get("smask", 0) or int(extracted.get("bpc", 8)) <= 1:
                    continue
                original = extracted["image"]
                image = Image.open(BytesIO(original))
                image.load()
            except Exception:
                continue

            target_width = min(image.width, int(occurrence["target_width"]))
            target_height = min(image.height, int(occurrence["target_height"]))
            scale = min(target_width / image.width, target_height / image.height, 1.0)
            if scale < 0.94:
                image = image.resize(
                    (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                    Image.Resampling.LANCZOS,
                )

            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                output = BytesIO()
                image.save(output, format="PNG", optimize=True)
            else:
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                output = BytesIO()
                image.save(output, format="JPEG", quality=jpeg_quality, optimize=True, progressive=True)
            replacement = output.getvalue()
            if len(replacement) >= len(original) * 0.98:
                continue
            try:
                document[int(occurrence["page"])].replace_image(xref, stream=replacement)
            except Exception:
                continue
            changed += 1
        return changed

    def _require_open(self) -> None:
        if self._source is None or self._original_bytes is None:
            raise RuntimeError("No PDF is open.")


def updated_edit(edit: TextEdit, **changes: object) -> TextEdit:
    return replace(edit, **changes)
