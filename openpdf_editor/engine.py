from __future__ import annotations

import math
import os
import re
import secrets
import tempfile
import zlib
from dataclasses import dataclass, field, replace
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs

from PIL import Image, ImageDraw, ImageFont, ImageStat

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
DOCUMENT_MARK_STREAM_TAG = b"/NettongiaDocumentMark BMC"
DOCUMENT_MARK_STREAM_PATTERN = re.compile(
    rb"/NettongiaDocumentMark\s+BMC.*?EMC", re.DOTALL
)


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
    source_bboxes: tuple[tuple[float, float, float, float], ...] = ()
    alpha: int = 255

    @property
    def bold(self) -> bool:
        return bool(self.flags & 16) or "bold" in self.font_name.lower()

    @property
    def italic(self) -> bool:
        return bool(self.flags & 2) or any(x in self.font_name.lower() for x in ("italic", "oblique"))

    @property
    def is_ocr(self) -> bool:
        return self.alpha == 0


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
    wrap_text: bool = True


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
class DocumentMarksSpec:
    """Header, footer and text-watermark settings for a whole document."""

    header_left: str = ""
    header_center: str = ""
    header_right: str = ""
    footer_left: str = ""
    footer_center: str = ""
    footer_right: str = ""
    font_family: str = "Arial"
    font_size: float = 9.0
    color: int = 0
    margin: float = 24.0
    watermark_text: str = ""
    watermark_font_size: float = 54.0
    watermark_color: int = 0x6F7782
    watermark_opacity: float = 0.18
    watermark_rotation: float = -45.0
    watermark_overlay: bool = False
    page_mode: str = "all"
    skip_first_page: bool = False
    document_title: str = ""


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


class ImageDeletionError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


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


@dataclass(frozen=True)
class FormFieldInfo:
    """A detached description of one editable AcroForm widget."""

    xref: int
    page_index: int
    name: str
    label: str
    type_code: int
    type_name: str
    value: str
    choices: tuple[str, ...]
    bbox: tuple[float, float, float, float]
    read_only: bool
    required: bool
    multiline: bool
    checked: bool
    on_value: str


@dataclass(frozen=True)
class FormFieldSpec:
    """Validated settings for a new interactive AcroForm field."""

    type_code: int
    name: str
    label: str = ""
    value: str = ""
    choices: tuple[str, ...] = ()
    read_only: bool = False
    required: bool = False
    multiline: bool = False


@dataclass(frozen=True)
class FormAccessibilityIssue:
    page_index: int
    field_name: str
    code: str


class PdfEngine:
    def __init__(self) -> None:
        self.path: Path | None = None
        self._original_bytes: bytes | None = None
        self._source: pymupdf.Document | None = None
        self._runs: dict[int, list[TextRun]] = {}
        self._image_runs: dict[int, list[ImageRun]] = {}
        self._image_occurrences: dict[int, set[str]] | None = None
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
        self._image_occurrences = None
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

    def form_fields(self) -> list[FormFieldInfo]:
        """Return supported AcroForm widgets without retaining PDF proxies."""

        self._require_open()
        result: list[FormFieldInfo] = []
        supported = {
            pymupdf.PDF_WIDGET_TYPE_TEXT,
            pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
            pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
            pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
            pymupdf.PDF_WIDGET_TYPE_LISTBOX,
            pymupdf.PDF_WIDGET_TYPE_SIGNATURE,
        }
        for page_index in range(self._source.page_count):
            page = self._source[page_index]
            for widget in page.widgets() or ():
                field_type = int(widget.field_type or 0)
                if field_type not in supported:
                    continue
                value = str(widget.field_value or "")
                on_value = ""
                checked = False
                if field_type in (
                    pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                    pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
                ):
                    on_value = str(widget.on_state() or "Yes")
                    checked = value not in ("", "Off") and value == on_value
                rect = self._view_rect(page, widget.rect)
                choices = tuple(str(item) for item in (widget.choice_values or ()))
                flags = int(widget.field_flags or 0)
                result.append(
                    FormFieldInfo(
                        xref=int(widget.xref),
                        page_index=page_index,
                        name=str(widget.field_name or ""),
                        label=str(widget.field_label or ""),
                        type_code=field_type,
                        type_name=str(widget.field_type_string or "Form field"),
                        value=value,
                        choices=choices,
                        bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                        read_only=bool(flags & pymupdf.PDF_FIELD_IS_READ_ONLY),
                        required=bool(flags & pymupdf.PDF_FIELD_IS_REQUIRED),
                        multiline=bool(
                            field_type == pymupdf.PDF_WIDGET_TYPE_TEXT
                            and flags & (1 << 12)
                        ),
                        checked=checked,
                        on_value=on_value,
                    )
                )
        return result

    def bytes_with_form_value(self, field_xref: int, value: str | bool) -> bytes:
        """Return a PDF with one supported AcroForm widget value changed."""

        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            for page in document:
                for widget in page.widgets() or ():
                    if int(widget.xref) != int(field_xref):
                        continue
                    flags = int(widget.field_flags or 0)
                    if flags & pymupdf.PDF_FIELD_IS_READ_ONLY:
                        raise ValueError("This form field is read-only.")
                    field_type = int(widget.field_type or 0)
                    if field_type == pymupdf.PDF_WIDGET_TYPE_TEXT:
                        text = str(value)
                        if len(text) > 10_000:
                            raise ValueError("The form value is too long.")
                        widget.field_value = text
                    elif field_type in (
                        pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                        pymupdf.PDF_WIDGET_TYPE_LISTBOX,
                    ):
                        text = str(value)
                        choices = tuple(str(item) for item in (widget.choice_values or ()))
                        if choices and text not in choices:
                            raise ValueError("The selected form value is unavailable.")
                        widget.field_value = text
                    elif field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                        widget.field_value = str(widget.on_state() or "Yes") if bool(value) else "Off"
                    elif field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                        if not bool(value):
                            raise ValueError("A radio button can only be selected.")
                        widget.field_value = str(widget.on_state() or "Yes")
                    else:
                        raise ValueError("This form field type is not editable.")
                    widget.update()
                    return self._serialize(document)
            raise ValueError("The form field is no longer available.")
        finally:
            document.close()

    def bytes_with_cleared_form_values(self) -> bytes:
        """Return a PDF with editable AcroForm values reset to an empty state."""

        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        changed = False
        try:
            for page in document:
                for widget in page.widgets() or ():
                    flags = int(widget.field_flags or 0)
                    if flags & pymupdf.PDF_FIELD_IS_READ_ONLY:
                        continue
                    field_type = int(widget.field_type or 0)
                    if field_type in (
                        pymupdf.PDF_WIDGET_TYPE_TEXT,
                        pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                        pymupdf.PDF_WIDGET_TYPE_LISTBOX,
                    ):
                        # PyMuPDF intentionally ignores an empty assignment.
                        # Generate a visually blank appearance with one space,
                        # then store the canonical AcroForm value as empty.
                        widget.field_value = " "
                        widget.update()
                        document.xref_set_key(widget.xref, "V", "()")
                    elif field_type in (
                        pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                        pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
                    ):
                        widget.field_value = "Off"
                    else:
                        continue
                    if field_type not in (
                        pymupdf.PDF_WIDGET_TYPE_TEXT,
                        pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                        pymupdf.PDF_WIDGET_TYPE_LISTBOX,
                    ):
                        widget.update()
                    changed = True
            if not changed:
                raise ValueError("This document has no editable form values.")
            return self._serialize(document)
        finally:
            document.close()

    def bytes_with_new_form_field(
        self,
        page_index: int,
        bbox: tuple[float, float, float, float],
        spec: FormFieldSpec,
    ) -> bytes:
        """Return a PDF with one new native AcroForm widget."""

        if not 0 <= page_index < self.page_count:
            raise IndexError("The page is unavailable.")
        supported = {
            pymupdf.PDF_WIDGET_TYPE_TEXT,
            pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
            pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
            pymupdf.PDF_WIDGET_TYPE_LISTBOX,
            pymupdf.PDF_WIDGET_TYPE_SIGNATURE,
        }
        if int(spec.type_code) not in supported:
            raise ValueError("This form field type cannot be created.")
        name = spec.name.strip()
        if not name or len(name) > 200 or any(ord(char) < 32 for char in name):
            raise ValueError("Enter a valid form field name.")
        if len(spec.label) > 500 or len(spec.value) > 10_000:
            raise ValueError("The form field text is too long.")
        choices = tuple(item.strip() for item in spec.choices if item.strip())
        if spec.type_code in (
            pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
            pymupdf.PDF_WIDGET_TYPE_LISTBOX,
        ) and len(choices) < 2:
            raise ValueError("Choice fields require at least two values.")

        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            for page in document:
                for existing in page.widgets() or ():
                    if (
                        str(existing.field_name or "") == name
                        and int(existing.field_type or 0) != int(spec.type_code)
                    ):
                        raise ValueError(
                            "A field with this name already exists with a different type."
                        )
            page = document[page_index]
            view_rect = pymupdf.Rect(bbox) & page.rect
            if view_rect.is_empty or view_rect.width < 4.0 or view_rect.height < 4.0:
                raise ValueError("The selected form field area is too small.")
            widget = pymupdf.Widget()
            widget.field_type = int(spec.type_code)
            widget.field_name = name
            widget.field_label = spec.label.strip() or name
            widget.rect = self._page_rect_from_view(page, view_rect)
            widget.border_color = (0.25, 0.45, 0.75)
            widget.border_width = 1.0
            widget.fill_color = (1.0, 1.0, 1.0)
            widget.text_color = (0.0, 0.0, 0.0)
            widget.text_font = "Helv"
            widget.text_fontsize = 11
            flags = pymupdf.PDF_FIELD_IS_READ_ONLY if spec.read_only else 0
            if spec.required:
                flags |= pymupdf.PDF_FIELD_IS_REQUIRED
            if spec.type_code == pymupdf.PDF_WIDGET_TYPE_TEXT:
                if spec.multiline:
                    flags |= pymupdf.PDF_TX_FIELD_IS_MULTILINE
                widget.field_value = spec.value
            elif spec.type_code == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                widget.text_font = "ZaDb"
                widget.text_fontsize = 0
                if spec.value.lower() in {"1", "true", "yes", "on", "checked"}:
                    widget.field_value = True
            elif spec.type_code in (
                pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                pymupdf.PDF_WIDGET_TYPE_LISTBOX,
            ):
                widget.choice_values = list(choices)
                widget.field_value = spec.value if spec.value in choices else choices[0]
            widget.field_flags = flags
            page.add_widget(widget)
            return self._serialize(document)
        finally:
            document.close()

    def bytes_without_form_field(self, field_xref: int) -> bytes:
        """Return a PDF with one form widget removed."""

        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            for page in document:
                for widget in page.widgets() or ():
                    if int(widget.xref) == int(field_xref):
                        page.delete_widget(widget)
                        return self._serialize(document)
            raise ValueError("The form field is no longer available.")
        finally:
            document.close()

    def bytes_with_form_label(self, field_xref: int, label: str) -> bytes:
        """Set the PDF alternate field name used by assistive technology."""
        label = label.strip()
        if not label or len(label) > 500 or any(ord(char) < 32 for char in label):
            raise ValueError("Enter a descriptive form field label (up to 500 characters).")
        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            for page in document:
                for widget in page.widgets() or ():
                    if widget.xref == field_xref:
                        widget.field_label = label
                        widget.update()
                        return self._serialize(document)
            raise ValueError("The form field is no longer available.")
        finally:
            document.close()

    def bytes_with_form_tab_order(self, page_index: int, ordered_xrefs: Iterable[int]) -> bytes:
        """Order widgets in /Annots and request annotation-order keyboard traversal."""
        if not 0 <= page_index < self.page_count:
            raise IndexError("The page is unavailable.")
        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            page = document[page_index]
            editable_types = {
                pymupdf.PDF_WIDGET_TYPE_TEXT,
                pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
                pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                pymupdf.PDF_WIDGET_TYPE_LISTBOX,
                pymupdf.PDF_WIDGET_TYPE_SIGNATURE,
            }
            current = [
                widget.xref for widget in page.widgets() or ()
                if int(widget.field_type or 0) in editable_types
            ]
            ordered = list(ordered_xrefs)
            if len(ordered) != len(current) or set(ordered) != set(current):
                raise ValueError("The tab order must contain each supported field on this page exactly once.")
            widget_xrefs = set(current)
            annotations = [xref for xref, _type, _id in page.annot_xrefs()]
            widget_iter = iter(ordered)
            reordered = [next(widget_iter) if xref in widget_xrefs else xref for xref in annotations]
            document.xref_set_key(
                page.xref, "Annots", "[" + " ".join(f"{xref} 0 R" for xref in reordered) + "]"
            )
            document.xref_set_key(page.xref, "Tabs", "/A")
            return self._serialize(document)
        finally:
            document.close()

    def form_accessibility_issues(self) -> list[FormAccessibilityIssue]:
        """Check form labels, keyboard order, and basic native PDF structures."""
        self._require_open()
        issues: list[FormAccessibilityIssue] = []
        catalog = self._source.pdf_catalog()
        fields_type, _ = self._source.xref_get_key(catalog, "AcroForm/Fields")
        for page_index, page in enumerate(self._source):
            widgets = list(page.widgets() or ())
            if not widgets:
                continue
            if fields_type not in ("array", "xref"):
                issues.append(FormAccessibilityIssue(page_index, "", "registry"))
            if len(widgets) > 1 and self._source.xref_get_key(page.xref, "Tabs") != ("name", "/A"):
                issues.append(FormAccessibilityIssue(page_index, "", "tab_order"))
            for widget in widgets:
                name = str(widget.field_name or "")
                label = str(widget.field_label or "").strip()
                if not label or (label == name and re.fullmatch(r"field_\d+", name)):
                    issues.append(FormAccessibilityIssue(page_index, name, "label"))
                appearance_type, appearance = self._source.xref_get_key(widget.xref, "AP/N")
                if appearance_type not in ("xref", "dict") or appearance in ("null", "<<>>"):
                    issues.append(FormAccessibilityIssue(page_index, name, "appearance"))
        return issues

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
                            alpha=int(span.get("alpha", 255)),
                        )
                    )
        runs = self._merge_paragraph_runs(runs)
        self._runs[page_index] = runs
        return runs

    @staticmethod
    def _merge_paragraph_runs(runs: list[TextRun]) -> list[TextRun]:
        """Merge conservative, uniformly styled PDF blocks into editable paragraphs."""

        by_block: dict[int, list[TextRun]] = {}
        for run in runs:
            by_block.setdefault(run.block_index, []).append(run)
        result: list[TextRun] = []
        for block_runs in by_block.values():
            ordered = sorted(
                block_runs,
                key=lambda item: (item.line_index, item.span_index),
            )
            line_indices = sorted({item.line_index for item in ordered})
            first = ordered[0]
            # OCR lines were grouped using their spatial layout above. A second
            # paragraph pass can join unrelated columns and discard line breaks.
            if any(item.is_ocr for item in ordered):
                result.extend(ordered)
                continue
            horizontal = first.direction[0] > 0.999 and abs(first.direction[1]) < 0.001
            uniform = all(
                item.font_name == first.font_name
                and abs(item.font_size - first.font_size) <= 0.35
                and item.color == first.color
                and item.flags == first.flags
                and item.alpha == first.alpha
                and abs(item.direction[0] - first.direction[0]) < 0.001
                and abs(item.direction[1] - first.direction[1]) < 0.001
                for item in ordered
            )
            line_groups = [
                sorted(
                    (item for item in ordered if item.line_index == line_index),
                    key=lambda item: item.bbox[0],
                )
                for line_index in line_indices
            ]
            line_texts = [PdfEngine._joined_line_text(line) for line in line_groups]
            list_like = any(
                PdfEngine._looks_like_list_item(text)
                for text in line_texts
            )
            table_like = any(
                any(
                    later.bbox[0] - earlier.bbox[2] > first.font_size * 1.5
                    for earlier, later in zip(line, line[1:])
                )
                for line in line_groups
            )
            line_boxes = [
                (
                    min(item.bbox[0] for item in line),
                    min(item.bbox[1] for item in line),
                    max(item.bbox[2] for item in line),
                    max(item.bbox[3] for item in line),
                )
                for line in line_groups
            ]
            spacing_ok = all(
                -first.font_size * 0.25
                <= later[1] - earlier[3]
                <= first.font_size * 1.5
                for earlier, later in zip(line_boxes, line_boxes[1:])
            )
            body_left = line_boxes[1][0] if len(line_boxes) > 1 else line_boxes[0][0]
            alignment_ok = all(
                abs(box[0] - body_left) <= first.font_size * 2.0
                for box in line_boxes[1:]
            )
            if (
                len(line_indices) < 2
                or not horizontal
                or not uniform
                or list_like
                or table_like
                or not spacing_ok
                or not alignment_ok
            ):
                result.extend(ordered)
                continue
            bbox = (
                min(item.bbox[0] for item in ordered),
                min(item.bbox[1] for item in ordered),
                max(item.bbox[2] for item in ordered),
                max(item.bbox[3] for item in ordered),
            )
            result.append(
                replace(
                    first,
                    text=PdfEngine._joined_paragraph_text(line_texts),
                    bbox=bbox,
                    source_bboxes=tuple(item.bbox for item in ordered),
                )
            )
        return sorted(result, key=lambda item: (item.block_index, item.line_index, item.span_index))

    @staticmethod
    def _joined_line_text(line: list[TextRun]) -> str:
        text = ""
        previous: TextRun | None = None
        for run in line:
            if (
                previous is not None
                and text
                and not text[-1].isspace()
                and run.text
                and not run.text[0].isspace()
                and run.bbox[0] - previous.bbox[2] > run.font_size * 0.12
            ):
                text += " "
            text += run.text
            previous = run
        return text

    @staticmethod
    def _joined_paragraph_text(lines: list[str]) -> str:
        result = ""
        for line in lines:
            value = line.strip()
            if not value:
                continue
            if result.endswith(("-", "\u00ad")) and value[0].islower():
                result = result[:-1] + value
            else:
                result = value if not result else f"{result} {value}"
        return result

    @staticmethod
    def _looks_like_list_item(text: str) -> bool:
        stripped = text.lstrip()
        if stripped.startswith(("•", "◦", "▪", "- ", "– ", "— ")):
            return True
        head = stripped.split(" ", 1)[0]
        return bool(head.rstrip(".)").isdigit() and head.endswith((".", ")")))

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
            xref = int(info.get("xref", 0))
            smask = masks.get(xref, 0)
            # delete_image leaves an invisible 1-pixel placeholder in the PDF.
            # Do not offer that placeholder as an editable original on reopen.
            if (
                int(info.get("width", 0)) == 1
                and int(info.get("height", 0)) == 1
                and smask > 0
                and pymupdf.Pixmap(self._source, smask).samples == b"\0"
            ):
                continue
            runs.append(
                ImageRun(
                    key=f"image:{page_index}:{occurrence}",
                    page_index=page_index,
                    bbox=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                    xref=xref,
                    width=int(info.get("width", 0)),
                    height=int(info.get("height", 0)),
                    smask=smask,
                    rotation_degrees=(
                        self._image_rotation(info.get("transform"))
                        + float(page.rotation)
                        + 180.0
                    ) % 360.0 - 180.0,
                )
            )
        self._image_runs[page_index] = runs
        return runs

    def validate_image_deletions(self, deleted_images: Iterable[ImageDeletion]) -> None:
        """Prevent an image shared by other occurrences from being removed globally."""
        deletions = tuple(deleted_images)
        if not deletions:
            return
        selected = set()
        for deletion in deletions:
            run = deletion.run
            if not 0 <= run.page_index < self.page_count or run not in self.image_runs(
                run.page_index
            ):
                raise ImageDeletionError("missing", "The original image is no longer available.")
            if run.xref <= 0:
                raise ImageDeletionError(
                    "inline", "This PDF contains an inline image that cannot be removed safely."
                )
            selected.add(run.key)

        if self._image_occurrences is None:
            occurrences: dict[int, set[str]] = {}
            for page_index in range(self.page_count):
                for run in self.image_runs(page_index):
                    occurrences.setdefault(run.xref, set()).add(run.key)
            self._image_occurrences = occurrences
        for deletion in deletions:
            if self._image_occurrences[deletion.run.xref] - selected:
                raise ImageDeletionError(
                    "shared",
                    "This image is reused elsewhere in the PDF. Removing it would also "
                    "erase other copies; individual removal is not supported yet."
                )

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
        deleted_images = tuple(deleted_images)
        self.validate_image_deletions(deleted_images)
        document = pymupdf.open(stream=self._original_bytes, filetype="pdf")
        # Replacing the image object with a transparent pixel preserves text,
        # vector artwork, and other images beneath its painted area. PyMuPDF's
        # replacement affects every use of an xref, hence the validation above.
        xref_pages = {deletion.run.xref: deletion.run.page_index for deletion in deleted_images}
        for xref, page_index in xref_pages.items():
            document[page_index].delete_image(xref)

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
                source_bboxes = tuple(
                    (
                        mapped.x0,
                        mapped.y0,
                        mapped.x1,
                        mapped.y1,
                    )
                    for bbox in run.source_bboxes
                    for mapped in (self._page_rect_from_view(page, bbox),)
                )
                page_run = replace(
                    run,
                    bbox=(run_bbox.x0, run_bbox.y0, run_bbox.x1, run_bbox.y1),
                    origin=(run_origin.x, run_origin.y),
                    direction=self._mapped_direction(page, run.direction, to_view=False),
                    source_bboxes=source_bboxes,
                )
                target_bbox = None
                if edit.bbox is not None:
                    target = self._page_rect_from_view(page, edit.bbox)
                    target_bbox = (target.x0, target.y0, target.x1, target.y1)
                page_edit = replace(edit, run=page_run, bbox=target_bbox)
                page_space_edits.append(page_edit)
                # Remove only the original text operators. A transparent
                # redaction preserves vector fills and images behind the text
                # instead of replacing colored backgrounds with a white box.
                source_rects = page_run.source_bboxes or (page_run.bbox,)
                if not page_run.is_ocr:
                    for source_bbox in source_rects:
                        rect = self._redaction_rect(
                            replace(page_run, bbox=source_bbox),
                            page.cropbox,
                        )
                        page.add_redact_annot(rect, fill=False, cross_out=False)
            if any(not edit.run.is_ocr for edit in page_space_edits):
                page.apply_redactions(images=0, graphics=0, text=0)

            ocr_patches: list[tuple[pymupdf.Rect, bytes]] = []
            table_cells = None
            for edit in page_space_edits:
                page_run = edit.run
                if not page_run.is_ocr:
                    continue
                for source_bbox in page_run.source_bboxes or (page_run.bbox,):
                    rect = self._redaction_rect(
                        replace(page_run, bbox=source_bbox),
                        page.cropbox,
                    )
                    if table_cells is None:
                        from .ocr_worker import _scanned_table_cells

                        table_cells = [cell for _, cells in _scanned_table_cells(page) for cell in cells]
                    center = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
                    cell = next(
                        (candidate for candidate in table_cells
                         if candidate.contains(center)
                         and candidate.intersects(rect)
                         and rect.height <= candidate.height + 3),
                        None,
                    )
                    patch = self._ocr_scan_patch(
                        page, cell if cell is not None else rect,
                        fill_cell=cell is not None,
                    )
                    if patch is not None:
                        ocr_patches.append(patch)
                    page.add_redact_annot(rect, fill=False, cross_out=False)
            if any(edit.run.is_ocr for edit in page_space_edits):
                # Remove the invisible search layer without modifying the scan
                # image. Overlay transparent, locally repaired pixels for the
                # photographed lettering before inserting replacement text.
                page.apply_redactions(images=0, graphics=0, text=0)
                for patch_rect, patch_bytes in ocr_patches:
                    page.insert_image(
                        patch_rect, stream=patch_bytes, overlay=True,
                        keep_proportion=False,
                    )

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
        encryption_password: str | None = None,
    ) -> None:
        document = self.build_document(
            edits,
            signatures,
            inserted_images,
            deleted_images,
            inserted_texts,
        )
        try:
            encryption_options: dict[str, object] = {}
            if encryption_password is not None:
                if not encryption_password:
                    raise ValueError("The PDF password cannot be empty.")
                if len(encryption_password) > 40:
                    raise ValueError("The PDF password cannot exceed 40 characters.")
                encryption_options = {
                    "encryption": pymupdf.PDF_ENCRYPT_AES_256,
                    "owner_pw": secrets.token_urlsafe(30),
                    "user_pw": encryption_password,
                    "validation_password": encryption_password,
                }
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
                **encryption_options,
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
                    "producer": "Nettongia PDF Editor 0.20.0",
                }
            )
            for _ in range(page_count):
                document.new_page(width=float(width), height=float(height))
            return PdfEngine._serialize(document)
        finally:
            document.close()

    @staticmethod
    def _document_mark_xrefs(document: pymupdf.Document) -> set[int]:
        marked: set[int] = set()
        for page in document:
            for xref in page.get_contents() or ():
                try:
                    stream = document.xref_stream(int(xref))
                except Exception:
                    continue
                if DOCUMENT_MARK_STREAM_PATTERN.search(stream):
                    marked.add(int(xref))
        return marked

    @classmethod
    def _remove_document_marks(cls, document: pymupdf.Document) -> int:
        marked = cls._document_mark_xrefs(document)
        for xref in marked:
            stream = document.xref_stream(xref)
            document.update_stream(
                xref,
                DOCUMENT_MARK_STREAM_PATTERN.sub(b"", stream),
            )
        return len(marked)

    def has_document_marks(self) -> bool:
        self._require_open()
        return bool(self._document_mark_xrefs(self._source))

    def bytes_without_document_marks(self) -> bytes:
        """Remove page decorations previously created by Nettongia."""

        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            self._remove_document_marks(document)
            return self._serialize(document)
        finally:
            document.close()

    @staticmethod
    def _mark_new_page_streams(
        document: pymupdf.Document,
        page: pymupdf.Page,
        previous: set[int],
    ) -> None:
        for xref in set(int(item) for item in (page.get_contents() or ())) - previous:
            stream = document.xref_stream(xref)
            if not DOCUMENT_MARK_STREAM_PATTERN.search(stream):
                document.update_stream(
                    xref,
                    DOCUMENT_MARK_STREAM_TAG + b"\n" + stream + b"\nEMC\n",
                )

    @staticmethod
    def _expanded_document_mark_text(
        text: str,
        *,
        page_number: int,
        page_count: int,
        title: str,
    ) -> str:
        values = {
            "page": str(page_number),
            "pages": str(page_count),
            "date": date.today().isoformat(),
            "title": title,
        }
        expanded = text
        for token, value in values.items():
            expanded = expanded.replace("{" + token + "}", value)
        return expanded

    @classmethod
    def _insert_page_mark_text(
        cls,
        page: pymupdf.Page,
        text: str,
        view_rect: pymupdf.Rect,
        *,
        align: int,
        spec: DocumentMarksSpec,
    ) -> None:
        if not text:
            return
        font_file = resolve_font(spec.font_family)
        fallback = _builtin_pdf_font_name(spec.font_family, False, False)
        simple = bool(font_file and _can_use_simple_font_encoding(text))
        font_name = (
            cls._font_resource_name(font_file, simple=simple)
            if font_file
            else fallback
        )
        page.insert_textbox(
            cls._page_rect_from_view(page, view_rect),
            text,
            fontsize=float(spec.font_size),
            fontname=font_name,
            fontfile=font_file,
            set_simple=int(simple),
            color=cls._pdf_color(spec.color),
            align=align,
            rotate=int(page.rotation) % 360,
            overlay=True,
        )

    @staticmethod
    def _watermark_png(spec: DocumentMarksSpec, text: str) -> tuple[bytes, float, float]:
        font_file = resolve_font(spec.font_family)
        pixel_size = max(12, round(spec.watermark_font_size * 4.0))

        def load_font(size: int):
            try:
                return (
                    ImageFont.truetype(font_file, size)
                    if font_file
                    else ImageFont.truetype("DejaVuSans.ttf", size)
                )
            except (OSError, ValueError):
                return ImageFont.load_default()

        # A very long watermark at a large point size must not allocate an
        # unbounded RGBA bitmap. Lower only its raster resolution; its PDF
        # dimensions remain based on the requested point size below.
        for _ in range(3):
            font = load_font(pixel_size)
            probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            bounds = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font)
            width = max(1, bounds[2] - bounds[0])
            height = max(1, bounds[3] - bounds[1])
            padding = max(8, pixel_size // 10)
            raster_width = width + padding * 2
            raster_height = height + padding * 2
            reduction = min(
                1.0,
                8192.0 / raster_width,
                math.sqrt(8_000_000.0 / (raster_width * raster_height)),
            )
            if reduction >= 0.99 or pixel_size <= 12:
                break
            pixel_size = max(12, int(pixel_size * reduction * 0.96))
        render_scale = pixel_size / float(spec.watermark_font_size)
        image = Image.new(
            "RGBA",
            (width + padding * 2, height + padding * 2),
            (0, 0, 0, 0),
        )
        alpha = max(1, min(255, round(spec.watermark_opacity * 255)))
        color = (
            (spec.watermark_color >> 16) & 255,
            (spec.watermark_color >> 8) & 255,
            spec.watermark_color & 255,
            alpha,
        )
        ImageDraw.Draw(image).text(
            (padding - bounds[0], padding - bounds[1]),
            text,
            font=font,
            fill=color,
        )
        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return (
            output.getvalue(),
            image.width / render_scale,
            image.height / render_scale,
        )

    def bytes_with_document_marks(self, spec: DocumentMarksSpec) -> bytes:
        """Replace Nettongia headers, footers and watermark in the PDF."""

        texts = (
            spec.header_left,
            spec.header_center,
            spec.header_right,
            spec.footer_left,
            spec.footer_center,
            spec.footer_right,
            spec.watermark_text,
        )
        if not any(value.strip() for value in texts):
            raise ValueError("Enter header, footer, or watermark text.")
        if any(len(value) > 1000 for value in texts[:6]) or len(texts[6]) > 250:
            raise ValueError("Document mark text is too long.")
        if spec.page_mode not in {"all", "odd", "even"}:
            raise ValueError("The page selection is invalid.")
        if not 4.0 <= spec.font_size <= 36.0:
            raise ValueError("Header and footer font size must be between 4 and 36 points.")
        if not 8.0 <= spec.watermark_font_size <= 240.0:
            raise ValueError("Watermark font size must be between 8 and 240 points.")
        if not 0.01 <= spec.watermark_opacity <= 1.0:
            raise ValueError("Watermark opacity must be between 1 and 100 percent.")
        if not 0.0 <= spec.margin <= 144.0:
            raise ValueError("The page margin is invalid.")
        if not 0 <= spec.color <= 0xFFFFFF or not 0 <= spec.watermark_color <= 0xFFFFFF:
            raise ValueError("The selected color is invalid.")

        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            if self._remove_document_marks(document):
                # Reopen the cleaned document before inserting replacements.
                # MuPDF may otherwise retain the old merged content stream in
                # the page cache and discard newly appended operators.
                cleaned = self._serialize(document)
                document.close()
                document = pymupdf.open(stream=cleaned, filetype="pdf")
            metadata = document.metadata or {}
            title = spec.document_title.strip() or str(metadata.get("title") or "")
            page_count = document.page_count
            for page_index, page in enumerate(document):
                page_number = page_index + 1
                if spec.skip_first_page and page_index == 0:
                    continue
                if spec.page_mode == "odd" and page_number % 2 == 0:
                    continue
                if spec.page_mode == "even" and page_number % 2 == 1:
                    continue
                previous = set(int(item) for item in (page.get_contents() or ()))
                expanded = [
                    self._expanded_document_mark_text(
                        value.strip(),
                        page_number=page_number,
                        page_count=page_count,
                        title=title,
                    )
                    for value in texts
                ]
                visible = page.rect
                margin = min(float(spec.margin), visible.width / 4, visible.height / 4)
                third = max(1.0, (visible.width - margin * 2) / 3.0)
                line_height = max(12.0, float(spec.font_size) * 1.55)
                header_top = margin
                footer_bottom = visible.height - margin
                for column, align in enumerate(
                    (pymupdf.TEXT_ALIGN_LEFT, pymupdf.TEXT_ALIGN_CENTER, pymupdf.TEXT_ALIGN_RIGHT)
                ):
                    x0 = margin + column * third
                    x1 = margin + (column + 1) * third
                    self._insert_page_mark_text(
                        page,
                        expanded[column],
                        pymupdf.Rect(x0, header_top, x1, header_top + line_height),
                        align=align,
                        spec=spec,
                    )
                    self._insert_page_mark_text(
                        page,
                        expanded[column + 3],
                        pymupdf.Rect(x0, footer_bottom - line_height, x1, footer_bottom),
                        align=align,
                        spec=spec,
                    )
                watermark = expanded[6]
                if watermark:
                    payload, width, height = self._watermark_png(spec, watermark)
                    available_width = visible.width * 0.82
                    available_height = visible.height * 0.55
                    fit = min(1.0, available_width / width, available_height / height)
                    width *= fit
                    height *= fit
                    radians = math.radians(spec.watermark_rotation)
                    outer_width = abs(width * math.cos(radians)) + abs(height * math.sin(radians))
                    outer_height = abs(width * math.sin(radians)) + abs(height * math.cos(radians))
                    center = pymupdf.Point(
                        (visible.x0 + visible.x1) / 2,
                        (visible.y0 + visible.y1) / 2,
                    )
                    bbox = (
                        center.x - outer_width / 2,
                        center.y - outer_height / 2,
                        center.x + outer_width / 2,
                        center.y + outer_height / 2,
                    )
                    self._insert_visual(
                        document,
                        page_index,
                        bbox,
                        payload,
                        overlay=bool(spec.watermark_overlay),
                        rotation_degrees=float(spec.watermark_rotation),
                    )
                self._mark_new_page_streams(
                    document, document[page_index], previous
                )
            return self._serialize(document)
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
        page_spec: str | None = None,
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
            if page_spec is not None:
                pages = self.parse_page_selection(page_spec, source.page_count)
                source.select(pages)
            count = source.page_count
            document.insert_pdf(source, start_at=after_page + 1)
            return self._serialize(document), count
        finally:
            source.close()
            document.close()

    @staticmethod
    def parse_page_selection(spec: str, page_count: int) -> list[int]:
        """Parse one-based comma separated pages and inclusive ranges in document order."""
        if page_count < 1 or not spec.strip():
            raise ValueError("Enter a page number or range, for example 1,3-5.")
        pages: set[int] = set()
        for part in spec.split(","):
            bounds = part.strip().split("-")
            if len(bounds) > 2 or not bounds[0].strip().isdigit() or (
                len(bounds) == 2 and bounds[1].strip() and not bounds[1].strip().isdigit()
            ):
                raise ValueError("Invalid page range. Use numbers such as 1,3-5 or 1-.")
            first = int(bounds[0].strip())
            last = (
                int(bounds[1].strip()) if bounds[1].strip() else page_count
            ) if len(bounds) == 2 else first
            if first < 1 or last > page_count or first > last:
                raise ValueError(
                    f"Page range must be within 1-{page_count} and in ascending order."
                )
            pages.update(range(first - 1, last))
        return sorted(pages)

    def save_page_selection(
        self,
        path: str | Path,
        pages: list[int],
        edits: Iterable[TextEdit] = (),
        signatures: Iterable[SignaturePlacement] = (),
        inserted_images: Iterable[ImagePlacement] = (),
        deleted_images: Iterable[ImageDeletion] = (),
        inserted_texts: Iterable[TextPlacement] = (),
    ) -> None:
        if not pages or len(set(pages)) != len(pages) or any(
            page < 0 or page >= self.page_count for page in pages
        ):
            raise ValueError("Select at least one valid page without duplicates.")
        document = self.build_document(
            edits, signatures, inserted_images, deleted_images, inserted_texts
        )
        try:
            document.select(pages)
            self._save_document_atomic(
                document, path, garbage=2, deflate=True, use_objstms=1
            )
        finally:
            document.close()

    def save_page_groups(
        self,
        groups: list[tuple[Path, list[int]]],
        edits: Iterable[TextEdit] = (),
        signatures: Iterable[SignaturePlacement] = (),
        inserted_images: Iterable[ImagePlacement] = (),
        deleted_images: Iterable[ImageDeletion] = (),
        inserted_texts: Iterable[TextPlacement] = (),
    ) -> None:
        """Compose pending edits once before writing several independent parts."""
        if not groups or any(
            not pages or len(set(pages)) != len(pages)
            or any(page < 0 or page >= self.page_count for page in pages)
            for _, pages in groups
        ):
            raise ValueError("Select at least one valid page per part.")
        targets = [target.resolve() for target, _ in groups]
        if len(set(targets)) != len(targets) or any(
            target.exists() for target in targets
        ):
            raise FileExistsError("An output file already exists or a filename is duplicated.")
        composed = self.build_document(
            edits, signatures, inserted_images, deleted_images, inserted_texts
        )
        try:
            payload = composed.tobytes(garbage=2, deflate=True, use_objstms=1)
        finally:
            composed.close()
        created: list[Path] = []
        try:
            for target, pages in groups:
                part = pymupdf.open(stream=payload, filetype="pdf")
                try:
                    part.select(pages)
                    self._save_document_atomic(
                        part, target, garbage=2, deflate=True, use_objstms=1
                    )
                    created.append(target)
                finally:
                    part.close()
        except Exception:
            for target in created:
                target.unlink(missing_ok=True)
            raise

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

    def bytes_with_pages_cropped(
        self,
        page_indices: Iterable[int],
        margins: tuple[float, float, float, float],
    ) -> bytes:
        """Inset selected page CropBoxes by visible left, top, right and bottom margins.

        Cropping is intentionally non-destructive: content outside the new CropBox
        remains in the PDF and can be restored with Undo before saving.  Margins are
        expressed in points in the page's displayed orientation, so a rotated page
        behaves exactly as it appears on screen.
        """

        pages = sorted(set(int(index) for index in page_indices))
        if not pages or any(index < 0 or index >= self.page_count for index in pages):
            raise ValueError("Select at least one valid page to crop.")
        try:
            left, top, right, bottom = (float(value) for value in margins)
        except (TypeError, ValueError):
            raise ValueError("Crop margins must be valid numbers.") from None
        if any(not math.isfinite(value) or value < 0 for value in (left, top, right, bottom)):
            raise ValueError("Crop margins cannot be negative.")
        if not any(value > 0 for value in (left, top, right, bottom)):
            raise ValueError("Enter at least one crop margin.")

        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            for page_index in pages:
                page = document[page_index]
                visible = page.rect
                remaining_width = float(visible.width) - left - right
                remaining_height = float(visible.height) - top - bottom
                if remaining_width < 36.0 or remaining_height < 36.0:
                    raise ValueError(
                        f"Crop margins leave page {page_index + 1} smaller than 12.7 mm."
                    )

                # Page.derotation_matrix maps the normalized, displayed page
                # rectangle into coordinates relative to the current CropBox.
                # Translate that local rectangle back into MediaBox coordinates
                # before assigning the next CropBox. This also supports PDFs that
                # were already cropped before opening them in Nettongia.
                view_rect = pymupdf.Rect(
                    left,
                    top,
                    float(visible.width) - right,
                    float(visible.height) - bottom,
                )
                local_rect = view_rect * page.derotation_matrix
                current = page.cropbox
                cropped = pymupdf.Rect(
                    current.x0 + local_rect.x0,
                    current.y0 + local_rect.y0,
                    current.x0 + local_rect.x1,
                    current.y0 + local_rect.y1,
                )
                page.set_cropbox(cropped)
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

    @staticmethod
    def _pdf_matrix_text(matrix: pymupdf.Matrix) -> str:
        return " ".join(
            f"{value:.9g}"
            for value in (
                matrix.a,
                matrix.b,
                matrix.c,
                matrix.d,
                matrix.e,
                matrix.f,
            )
        )

    @classmethod
    def _wrap_page_contents_with_matrix(
        cls,
        document: pymupdf.Document,
        page: pymupdf.Page,
        matrix: pymupdf.Matrix,
    ) -> None:
        """Transform one page without mutating content streams shared by other pages."""

        contents = [int(xref) for xref in (page.get_contents() or ())]
        prefix = document.get_new_xref()
        document.update_object(prefix, "<<>>")
        document.update_stream(
            prefix,
            f"q\n{cls._pdf_matrix_text(matrix)} cm\n".encode("ascii"),
        )
        suffix = document.get_new_xref()
        document.update_object(suffix, "<<>>")
        document.update_stream(suffix, b"\nQ\n")
        references = [prefix, *contents, suffix]
        document.xref_set_key(
            page.xref,
            "Contents",
            "[" + " ".join(f"{xref} 0 R" for xref in references) + "]",
        )

    @classmethod
    def _transform_pdf_coordinate_array(
        cls,
        document: pymupdf.Document,
        xref: int,
        key: str,
        matrix: pymupdf.Matrix,
        *,
        rectangle: bool = False,
    ) -> bool:
        value_type, raw_value = document.xref_get_key(xref, key)
        if value_type != "array":
            return False
        numbers = [
            float(value)
            for value in re.findall(
                r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?",
                raw_value,
            )
        ]
        if len(numbers) < 4 or len(numbers) % 2:
            return False
        points = [
            pymupdf.Point(numbers[index], numbers[index + 1]) * matrix
            for index in range(0, len(numbers), 2)
        ]
        if rectangle:
            xs = [point.x for point in points]
            ys = [point.y for point in points]
            values = (min(xs), min(ys), max(xs), max(ys))
        else:
            values = tuple(
                coordinate
                for point in points
                for coordinate in (point.x, point.y)
            )
        document.xref_set_key(
            xref,
            key,
            "[" + " ".join(f"{value:.9g}" for value in values) + "]",
        )
        return True

    @classmethod
    def _transform_annotation_geometry(
        cls,
        document: pymupdf.Document,
        xref: int,
        matrix: pymupdf.Matrix,
    ) -> None:
        cls._transform_pdf_coordinate_array(
            document, xref, "Rect", matrix, rectangle=True
        )
        for key in ("QuadPoints", "Vertices", "L", "CL"):
            cls._transform_pdf_coordinate_array(document, xref, key, matrix)
        ink_type, ink_value = document.xref_get_key(xref, "InkList")
        if ink_type == "array":
            strokes: list[str] = []
            for raw_stroke in re.findall(r"\[([^\[\]]+)\]", ink_value):
                numbers = [
                    float(value)
                    for value in re.findall(
                        r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?",
                        raw_stroke,
                    )
                ]
                if len(numbers) < 4 or len(numbers) % 2:
                    continue
                points = [
                    pymupdf.Point(numbers[index], numbers[index + 1]) * matrix
                    for index in range(0, len(numbers), 2)
                ]
                strokes.append(
                    "["
                    + " ".join(
                        f"{coordinate:.9g}"
                        for point in points
                        for coordinate in (point.x, point.y)
                    )
                    + "]"
                )
            if strokes:
                document.xref_set_key(xref, "InkList", "[" + " ".join(strokes) + "]")
        popup_type, popup_value = document.xref_get_key(xref, "Popup")
        if popup_type == "xref":
            try:
                popup_xref = int(popup_value.split()[0])
            except (TypeError, ValueError, IndexError):
                popup_xref = 0
            if popup_xref > 0:
                cls._transform_pdf_coordinate_array(
                    document, popup_xref, "Rect", matrix, rectangle=True
                )

    def bytes_with_pages_resized(
        self,
        page_indices: Iterable[int],
        target_width: float,
        target_height: float,
        mode: str = "fit",
    ) -> bytes:
        """Resize selected pages and optionally scale their visible content.

        ``fit`` scales content proportionally to fit and centres it. ``canvas``
        preserves its visual size and only changes the centred page canvas.
        Existing page rotation is baked into the transformed content so the
        displayed orientation remains unchanged while the new physical page size
        has an unambiguous width and height.
        """

        pages = sorted(set(int(index) for index in page_indices))
        if not pages or any(index < 0 or index >= self.page_count for index in pages):
            raise ValueError("Select at least one valid page to resize.")
        try:
            width = float(target_width)
            height = float(target_height)
        except (TypeError, ValueError):
            raise ValueError("Page dimensions must be valid numbers.") from None
        if (
            not math.isfinite(width)
            or not math.isfinite(height)
            or width < 36.0
            or height < 36.0
            or width > 14_400.0
            or height > 14_400.0
        ):
            raise ValueError("Page dimensions must be between 12.7 and 5080 mm.")
        if mode not in {"fit", "canvas"}:
            raise ValueError("Unknown page resize mode.")

        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        page_set = set(pages)
        # Link rectangles belong to their source pages, while internal target
        # points belong to destination pages. Capture both before geometry changes.
        page_links = [page.get_links() for page in document]
        table_of_contents = document.get_toc(simple=False)
        transformations: dict[int, tuple[pymupdf.Matrix, pymupdf.Matrix]] = {}
        try:
            for page_index in pages:
                page = document[page_index]
                old_width = float(page.rect.width)
                old_height = float(page.rect.height)
                if old_width <= 0 or old_height <= 0:
                    raise ValueError(f"Page {page_index + 1} has invalid dimensions.")
                scale = (
                    min(width / old_width, height / old_height)
                    if mode == "fit"
                    else 1.0
                )
                offset_x = (width - old_width * scale) / 2.0
                offset_y = (height - old_height * scale) / 2.0
                visible_transform = pymupdf.Matrix(
                    scale, 0.0, 0.0, scale, offset_x, offset_y
                )
                old_rotation = pymupdf.Matrix(page.rotation_matrix)
                old_pdf_to_view = pymupdf.Matrix(page.transformation_matrix) * old_rotation
                new_pdf_to_view = pymupdf.Matrix(1.0, 0.0, 0.0, -1.0, 0.0, height)
                content_transform = (
                    old_pdf_to_view * visible_transform * ~new_pdf_to_view
                )
                transformations[page_index] = (old_rotation, visible_transform)

                annotation_xrefs = [
                    annotation.xref for annotation in (page.annots() or ())
                ]
                widget_xrefs = [widget.xref for widget in (page.widgets() or ())]
                for xref in (*annotation_xrefs, *widget_xrefs):
                    self._transform_annotation_geometry(
                        document, xref, content_transform
                    )
                self._wrap_page_contents_with_matrix(
                    document, page, content_transform
                )
                page.set_rotation(0)
                document.xref_set_key(page.xref, "UserUnit", "1")
                target_box = pymupdf.Rect(0.0, 0.0, width, height)
                page.set_mediabox(target_box)
                page.set_cropbox(target_box)

                for xref in annotation_xrefs:
                    annotation = page.load_annot(xref)
                    if annotation is None:
                        continue
                    annotation.update()
                for xref in widget_xrefs:
                    widget = page.load_widget(xref)
                    if widget is None:
                        continue
                    widget.update()

            for source_index, links in enumerate(page_links):
                page = document[source_index]
                for link in links:
                    changed = False
                    if source_index in page_set and link.get("from") is not None:
                        rotation, transform = transformations[source_index]
                        link["from"] = pymupdf.Rect(link["from"]) * rotation * transform
                        changed = True
                    destination_value = link.get("page", -1)
                    destination = (
                        int(destination_value)
                        if isinstance(destination_value, (int, float))
                        else -1
                    )
                    target = link.get("to")
                    if destination in page_set and target is not None:
                        rotation, transform = transformations[destination]
                        link["to"] = pymupdf.Point(target) * rotation * transform
                        changed = True
                    if changed and int(link.get("xref", 0)) > 0:
                        page.update_link(link)

            toc_changed = False
            for entry in table_of_contents:
                if len(entry) < 4 or not isinstance(entry[3], dict):
                    continue
                destination = int(entry[2]) - 1
                target = entry[3].get("to")
                if destination not in page_set or target is None:
                    continue
                rotation, transform = transformations[destination]
                entry[3]["to"] = pymupdf.Point(target) * rotation * transform
                toc_changed = True
            if toc_changed:
                document.set_toc(table_of_contents)

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

        return self.bytes_with_text_markup(
            page_index, bbox, "highlight", content=content, author=author
        )

    def bytes_with_text_markup(
        self,
        page_index: int,
        bbox: tuple[float, float, float, float],
        style: str,
        *,
        content: str = "",
        author: str = "",
        line_bboxes: Iterable[tuple[float, float, float, float]] | None = None,
    ) -> bytes:
        """Create a native text markup annotation in visible page coordinates."""

        if not 0 <= page_index < self.page_count:
            raise IndexError("The page is unavailable.")
        if style not in {"highlight", "underline", "strikeout"}:
            raise ValueError("Unsupported text markup style.")
        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            page = document[page_index]
            quads = []
            for box in tuple(line_bboxes) if line_bboxes is not None else (bbox,):
                view_rect = pymupdf.Rect(box) & page.rect
                if view_rect.is_empty or view_rect.width < 0.5 or view_rect.height < 0.5:
                    raise ValueError("The selected text area is unavailable.")
                # Preserve corner order on rotated pages and individual
                # baselines on multi-line paragraphs.
                quads.append(pymupdf.Quad(
                    self._mapped_point(page, view_rect.top_left, to_view=False),
                    self._mapped_point(page, view_rect.top_right, to_view=False),
                    self._mapped_point(page, view_rect.bottom_left, to_view=False),
                    self._mapped_point(page, view_rect.bottom_right, to_view=False),
                ))
            if not quads:
                raise ValueError("The selected text area is unavailable.")
            annotation = {
                "highlight": page.add_highlight_annot,
                "underline": page.add_underline_annot,
                "strikeout": page.add_strikeout_annot,
            }[style](quads)
            annotation.set_info(
                title=author.strip(),
                content=content.strip(),
                subject=f"Nettongia {style}",
            )
            annotation.set_colors(stroke={
                "highlight": (1.0, 0.82, 0.0),
                "underline": (0.10, 0.42, 0.85),
                "strikeout": (0.85, 0.16, 0.19),
            }[style])
            annotation.update(opacity=0.45 if style == "highlight" else 1.0)
            return self._serialize(document)
        finally:
            document.close()

    def bytes_with_redaction(
        self,
        page_index: int,
        bbox: tuple[float, float, float, float],
    ) -> bytes:
        """Permanently remove page content inside a visible rectangle.

        The rectangle uses the same rotated, on-screen coordinate system as
        rendering and selection.  Overlapping annotations and form widgets
        are removed as well so their values or comments cannot remain hidden
        behind the black rectangle.
        """

        if not 0 <= page_index < self.page_count:
            raise IndexError("The page is unavailable.")
        document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
        try:
            page = document[page_index]
            view_rect = pymupdf.Rect(bbox) & page.rect
            if view_rect.is_empty or view_rect.width < 1.0 or view_rect.height < 1.0:
                raise ValueError("The selected redaction area is too small.")
            page_rect = self._page_rect_from_view(page, view_rect)

            annotations = list(page.annots() or ())
            if any(item.type[0] == pymupdf.PDF_ANNOT_REDACT for item in annotations):
                raise ValueError(
                    "This page already contains unapplied redaction marks. "
                    "Remove them before creating a permanent redaction."
                )
            for annotation in annotations:
                if not (pymupdf.Rect(annotation.rect) & page_rect).is_empty:
                    page.delete_annot(annotation)
            for widget in list(page.widgets() or ()):
                if not (pymupdf.Rect(widget.rect) & page_rect).is_empty:
                    page.delete_widget(widget)

            page.add_redact_annot(
                page_rect,
                fill=(0.0, 0.0, 0.0),
                cross_out=False,
            )
            applied = page.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,
            )
            if not applied:
                raise RuntimeError("The redaction could not be applied.")
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
        *,
        validation_password: str | None = None,
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
                password=validation_password,
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
    def _validate_saved_pdf(
        path: str | Path,
        *,
        expected_page_count: int,
        password: str | None = None,
    ) -> None:
        """Reopen and render representative pages before publishing a save."""

        verification = pymupdf.open(path)
        try:
            if verification.needs_pass and (
                password is None or not verification.authenticate(password)
            ):
                raise ValueError("The saved PDF could not be unlocked for validation.")
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
    def wrapped_text_height(
        text: str,
        width: float,
        font_family: str,
        font_size: float,
        bold: bool = False,
        italic: bool = False,
    ) -> float:
        """Return a conservative textbox height using the PDF font metrics."""

        size = max(3.0, float(font_size))
        usable_width = max(1.0, float(width) - 1.0)
        font_file = resolve_font(font_family, bold, italic)
        fallback = _builtin_pdf_font_name(font_family, bold, italic)
        try:
            font = (
                pymupdf.Font(fontfile=font_file)
                if font_file
                else pymupdf.Font(fallback)
            )
        except Exception:
            font = pymupdf.Font("helv")

        lines = PdfEngine._wrapped_text_lines(text, usable_width, font, size)
        return max(1, len(lines)) * size * 1.15 + 5.0

    @staticmethod
    def _wrapped_text_lines(
        text: str,
        width: float,
        font: pymupdf.Font,
        font_size: float,
    ) -> list[str]:
        """Wrap text with the same font metrics used for PDF composition."""

        def length(value: str) -> float:
            return float(font.text_length(value, fontsize=font_size))

        lines: list[str] = []
        for paragraph in text.split("\n"):
            if not paragraph:
                lines.append("")
                continue
            current = ""
            for word in paragraph.split(" "):
                candidate = word if not current else f"{current} {word}"
                if current and length(candidate) > width:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
                while current and length(current) > width:
                    split_at = len(current) - 1
                    while split_at > 1 and length(current[:split_at]) > width:
                        split_at -= 1
                    lines.append(current[:split_at])
                    current = current[split_at:]
            if current:
                lines.append(current)
        return lines or [""]

    @staticmethod
    def _redaction_rect(run: TextRun, page_rect: pymupdf.Rect) -> pymupdf.Rect:
        rect = pymupdf.Rect(run.bbox)
        rect.x0 = max(page_rect.x0, rect.x0 - 0.35)
        rect.y0 = max(page_rect.y0, rect.y0 - 0.35)
        rect.x1 = min(page_rect.x1, rect.x1 + 0.35)
        rect.y1 = min(page_rect.y1, rect.y1 + 0.35)
        return rect

    @staticmethod
    def _ocr_scan_patch(
        page: pymupdf.Page, source_rect: pymupdf.Rect, *, fill_cell: bool = False
    ) -> tuple[pymupdf.Rect, bytes] | None:
        """Repair recognized ink locally without changing the original image.

        The transparent overlay only covers pixels that differ substantially
        from the estimated background. Unrecognized texture is left alone.
        """

        rect = pymupdf.Rect(source_rect) & page.rect
        if rect.is_empty:
            return None
        margin = 14.0
        clip = pymupdf.Rect(
            rect.x0 - margin, rect.y0 - margin,
            rect.x1 + margin, rect.y1 + margin,
        ) & page.rect
        # Bound the memory and CPU cost for unexpectedly large OCR blocks.
        scale = min(2.0, math.sqrt(900_000 / max(1.0, clip.width * clip.height)))
        scale = max(0.5, scale)
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale), clip=clip,
            alpha=False, annots=False,
        )
        if pixmap.width < 2 or pixmap.height < 2:
            return None
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        pixels = image.load()
        overlay = Image.new("RGBA", image.size)
        repaired = overlay.load()
        changed = False
        x0 = max(0, math.ceil(rect.x0 * scale - pixmap.x))
        x1 = min(pixmap.width, math.ceil(rect.x1 * scale - pixmap.x))
        y0 = max(0, math.ceil(rect.y0 * scale - pixmap.y))
        y1 = min(pixmap.height, math.ceil(rect.y1 * scale - pixmap.y))
        if x1 <= x0 or y1 <= y0:
            return None

        if fill_cell:
            # Within a ruled cell the entire interior belongs to this one
            # text item. A uniform scan background removes faint remnants
            # outside the OCR glyph bounds without touching the ruling lines.
            background = tuple(int(v) for v in ImageStat.Stat(
                image.crop((x0, y0, x1, y1))
            ).median)
            overlay.paste((*background, 255), (x0, y0, x1, y1))
            output = BytesIO()
            overlay.save(output, format="PNG")
            return pymupdf.Rect(
                pixmap.x / scale, pixmap.y / scale,
                (pixmap.x + pixmap.width) / scale,
                (pixmap.y + pixmap.height) / scale,
            ), output.getvalue()

        upper = max(0, y0 - 1 - round(margin * scale * 0.7))
        lower = min(pixmap.height - 1, y1 + round(margin * scale * 0.7))
        left = max(0, x0 - 1 - round(margin * scale * 0.7))
        right = min(pixmap.width - 1, x1 + round(margin * scale * 0.7))
        for y in range(y0, y1):
            vertical_weight = (y - upper) / max(1, lower - upper)
            for x in range(x0, x1):
                horizontal_weight = (x - left) / max(1, right - left)
                top, bottom = pixels[x, upper], pixels[x, lower]
                side_left, side_right = pixels[left, y], pixels[right, y]
                vertical = tuple(
                    top[c] * (1 - vertical_weight) + bottom[c] * vertical_weight
                    for c in range(3)
                )
                horizontal = tuple(
                    side_left[c] * (1 - horizontal_weight)
                    + side_right[c] * horizontal_weight
                    for c in range(3)
                )
                # Prefer samples along the long edge of a text line: its top
                # and bottom normally contain fewer neighboring letters.
                background = tuple(round(value) for value in vertical)
                if max(abs(top[c] - bottom[c]) for c in range(3)) > 45:
                    # A border can itself cross printed artwork; in that
                    # case use the perpendicular estimate as a fallback.
                    background = tuple(round(value) for value in horizontal)
                original = pixels[x, y]
                if max(abs(original[c] - background[c]) for c in range(3)) >= 30:
                    repaired[x, y] = (*background, 255)
                    changed = True

        if not changed:
            return None

        output = BytesIO()
        overlay.save(output, format="PNG")
        patch_rect = pymupdf.Rect(
            pixmap.x / scale, pixmap.y / scale,
            (pixmap.x + pixmap.width) / scale,
            (pixmap.y + pixmap.height) / scale,
        )
        return patch_rect, output.getvalue()

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
                    can_wrap = (
                        edit.wrap_text
                        and direction[0] > 0.999
                        and abs(direction[1]) < 0.001
                        and text_width > available
                    )
                    if text_width > available and not can_wrap:
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
                can_wrap = (
                    edit.wrap_text
                    and direction[0] > 0.999
                    and abs(direction[1]) < 0.001
                    and text_width > available
                )
                if text_width > available and not can_wrap:
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
        wrapped = bool(
            edit.wrap_text
            and direction[0] > 0.999
            and abs(direction[1]) < 0.001
            and text_width > self._text_axis_extent(target_bbox, direction)
        )
        if wrapped:
            attempted_size = font_size
            remaining = -1.0
            while attempted_size >= 3.0:
                remaining = page.insert_textbox(
                    pymupdf.Rect(target_bbox),
                    edit.new_text,
                    fontsize=attempted_size,
                    lineheight=1.15,
                    fontname=font_name,
                    fontfile=font_file,
                    set_simple=int(simple_font),
                    color=color,
                    align=pymupdf.TEXT_ALIGN_LEFT,
                    overlay=True,
                )
                if remaining >= 0:
                    font_size = attempted_size
                    break
                if attempted_size <= 3.0:
                    break
                attempted_size = max(3.0, attempted_size * 0.88)
            if remaining < 0:
                wrapped = False
        if not wrapped:
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
            if wrapped:
                try:
                    underline_font = (
                        pymupdf.Font(fontfile=font_file)
                        if font_file
                        else pymupdf.Font(font_name)
                    )
                except Exception:
                    underline_font = pymupdf.Font("helv")
                lines = self._wrapped_text_lines(
                    edit.new_text,
                    self._text_axis_extent(target_bbox, direction),
                    underline_font,
                    font_size,
                )
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
