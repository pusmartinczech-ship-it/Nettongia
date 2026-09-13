from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import pymupdf
except ImportError:  # PyMuPDF before 1.24
    import fitz as pymupdf


INSPECTION_FORMAT = "openpdf-editor-document-inspection"
INSPECTION_SCHEMA_VERSION = 1
MAX_DESCRIPTOR_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DocumentInspectionReport:
    page_count: int
    pdf_format: str
    encrypted_source: bool
    digital_signature_fields: int
    signed_digital_signatures: int
    other_form_fields: int
    xfa_forms: bool
    annotations: int
    embedded_files: int
    optional_content_groups: int
    javascript: bool
    portfolio: bool
    tagged_pdf: bool
    oversized_pages: int
    representative_pages_rendered: int

    @property
    def warning_codes(self) -> tuple[str, ...]:
        warnings: list[str] = []
        if self.signed_digital_signatures:
            warnings.append("digital_signatures")
        if self.other_form_fields or self.xfa_forms:
            warnings.append("forms")
        if self.javascript:
            warnings.append("javascript")
        if self.embedded_files:
            warnings.append("attachments")
        if self.optional_content_groups:
            warnings.append("layers")
        if self.portfolio:
            warnings.append("portfolio")
        if self.encrypted_source:
            warnings.append("encryption_removed")
        if self.oversized_pages:
            warnings.append("oversized_pages")
        if self.tagged_pdf:
            warnings.append("tagged_pdf")
        return tuple(warnings)

    @property
    def compatibility_level(self) -> str:
        """Return the user-facing risk tier for editing and rewriting this PDF."""

        if (
            self.signed_digital_signatures
            or self.xfa_forms
            or self.javascript
            or self.portfolio
        ):
            return "high_risk"
        if self.warning_codes:
            return "possible_changes"
        return "safe"


def prepare_inspection_job(
    workspace: str | Path,
    source_bytes: bytes,
    *,
    encrypted_source: bool,
) -> tuple[Path, Path]:
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    source_path = root / "source.pdf"
    result_path = root / "result.json"
    job_path = root / "job.json"
    source_path.write_bytes(source_bytes)
    descriptor = {
        "format": INSPECTION_FORMAT,
        "schema_version": INSPECTION_SCHEMA_VERSION,
        "source_path": str(source_path),
        "result_path": str(result_path),
        "encrypted_source": bool(encrypted_source),
    }
    encoded = json.dumps(descriptor, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The inspection job is too large.")
    job_path.write_bytes(encoded)
    return job_path, result_path


def _read_job(path: str | Path) -> dict[str, Any]:
    data = Path(path).read_bytes()
    if len(data) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The inspection job is too large.")
    try:
        job = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The inspection job is damaged.") from exc
    if not isinstance(job, dict) or job.get("format") != INSPECTION_FORMAT:
        raise ValueError("The inspection job format is invalid.")
    if job.get("schema_version") != INSPECTION_SCHEMA_VERSION:
        raise ValueError("The inspection job version is not supported.")
    for key in ("source_path", "result_path"):
        if not isinstance(job.get(key), str) or not job[key] or len(job[key]) > 32_768:
            raise ValueError(f"Invalid inspection field: {key}.")
    if not isinstance(job.get("encrypted_source"), bool):
        raise ValueError("Invalid inspection field: encrypted_source.")
    return job


def _write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    finally:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass


def _catalog_has(document: pymupdf.Document, key: str) -> bool:
    try:
        value_type, _value = document.xref_get_key(document.pdf_catalog(), key)
        return value_type not in {"null", "none"}
    except (RuntimeError, TypeError, ValueError):
        return False


def _detect_javascript(document: pymupdf.Document) -> bool:
    try:
        catalog = document.xref_object(document.pdf_catalog(), compressed=False)
        if "/JavaScript" in catalog or "/JS" in catalog:
            return True
        value_type, value = document.xref_get_key(document.pdf_catalog(), "Names")
        if value_type == "xref":
            names_xref = int(str(value).split()[0])
            names = document.xref_object(names_xref, compressed=False)
            return "/JavaScript" in names or "/JS" in names
    except (IndexError, RuntimeError, TypeError, ValueError):
        pass
    return False


def _representative_pages(page_count: int) -> tuple[int, ...]:
    return tuple(dict.fromkeys((0, page_count // 2, page_count - 1)))


def inspect_document(path: str | Path, *, encrypted_source: bool = False) -> DocumentInspectionReport:
    document = pymupdf.open(path)
    try:
        if document.page_count < 1:
            raise ValueError("A PDF must contain at least one page.")
        signature_fields = 0
        signed_signatures = 0
        other_fields = 0
        annotations = 0
        oversized_pages = 0
        for page in document:
            rect = page.rect
            if rect.width > 4000 or rect.height > 4000 or rect.width * rect.height > 8_000_000:
                oversized_pages += 1
            widgets = page.widgets()
            if widgets is not None:
                for widget in widgets:
                    if widget.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
                        signature_fields += 1
                        if bool(getattr(widget, "is_signed", False)):
                            signed_signatures += 1
                    else:
                        other_fields += 1
            page_annotations = page.annots()
            if page_annotations is not None:
                annotations += sum(1 for _ in page_annotations)

        try:
            embedded_files = int(document.embfile_count())
        except (AttributeError, RuntimeError):
            embedded_files = 0
        try:
            optional_content_groups = len(document.get_ocgs())
        except (AttributeError, RuntimeError, TypeError):
            optional_content_groups = 0

        xfa_forms = False
        try:
            value_type, value = document.xref_get_key(document.pdf_catalog(), "AcroForm")
            if value_type == "xref":
                form_xref = int(str(value).split()[0])
                xfa_forms = "/XFA" in document.xref_object(form_xref, compressed=False)
        except (IndexError, RuntimeError, TypeError, ValueError):
            pass

        rendered = 0
        for page_index in _representative_pages(document.page_count):
            page = document[page_index]
            area = max(1.0, page.rect.width * page.rect.height)
            scale = min(0.5, max(0.05, math.sqrt(1_000_000 / area)))
            page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, annots=True)
            rendered += 1

        return DocumentInspectionReport(
            page_count=document.page_count,
            pdf_format=str(document.metadata.get("format") or "PDF"),
            encrypted_source=bool(encrypted_source),
            digital_signature_fields=signature_fields,
            signed_digital_signatures=signed_signatures,
            other_form_fields=other_fields,
            xfa_forms=xfa_forms,
            annotations=annotations,
            embedded_files=embedded_files,
            optional_content_groups=optional_content_groups,
            javascript=_detect_javascript(document),
            portfolio=_catalog_has(document, "Collection"),
            tagged_pdf=_catalog_has(document, "StructTreeRoot"),
            oversized_pages=oversized_pages,
            representative_pages_rendered=rendered,
        )
    finally:
        document.close()


def run_inspection_job(job_path: str | Path) -> int:
    result_path: Path | None = None
    try:
        job = _read_job(job_path)
        result_path = Path(job["result_path"])
        report = inspect_document(
            job["source_path"], encrypted_source=job["encrypted_source"]
        )
        _write_json_atomic(
            result_path,
            {"format": INSPECTION_FORMAT, "status": "succeeded", "report": asdict(report)},
        )
        return 0
    except BaseException as exc:
        if result_path is not None:
            try:
                _write_json_atomic(
                    result_path,
                    {"format": INSPECTION_FORMAT, "status": "failed", "error": str(exc)},
                )
            except OSError:
                pass
        return 1


def read_inspection_result(path: str | Path) -> tuple[DocumentInspectionReport | None, str | None]:
    data = Path(path).read_bytes()
    if len(data) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The inspection result is too large.")
    try:
        result = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The inspection result is damaged.") from exc
    if not isinstance(result, dict) or result.get("format") != INSPECTION_FORMAT:
        raise ValueError("The inspection result is invalid.")
    if result.get("status") == "failed":
        return None, str(result.get("error") or "Document inspection failed.")
    if result.get("status") != "succeeded" or not isinstance(result.get("report"), dict):
        raise ValueError("The inspection result status is invalid.")
    try:
        report = DocumentInspectionReport(**result["report"])
    except (TypeError, ValueError) as exc:
        raise ValueError("The inspection report is invalid.") from exc
    for value in (
        report.page_count,
        report.digital_signature_fields,
        report.signed_digital_signatures,
        report.other_form_fields,
        report.annotations,
        report.embedded_files,
        report.optional_content_groups,
        report.oversized_pages,
        report.representative_pages_rendered,
    ):
        if type(value) is not int or value < 0:
            raise ValueError("The inspection report contains an invalid count.")
    if not isinstance(report.pdf_format, str) or not report.pdf_format or len(report.pdf_format) > 100:
        raise ValueError("The inspection report contains an invalid PDF format.")
    for value in (
        report.encrypted_source,
        report.xfa_forms,
        report.javascript,
        report.portfolio,
        report.tagged_pdf,
    ):
        if type(value) is not bool:
            raise ValueError("The inspection report contains an invalid flag.")
    return report, None


def main() -> int:
    import sys

    if len(sys.argv) != 2:
        return 2
    return run_inspection_job(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
