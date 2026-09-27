from __future__ import annotations

import json
import logging
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
INSPECTION_SCHEMA_VERSION = 2
MAX_DESCRIPTOR_BYTES = 1024 * 1024
MAX_SIGNATURES = 64
MAX_SIGNATURE_TEXT = 2048


@dataclass(frozen=True)
class DigitalSignatureReport:
    field_name: str
    signer_name: str
    certificate_subject: str
    certificate_issuer: str
    certificate_serial: str
    certificate_valid_from: str
    certificate_valid_to: str
    certificate_sha256: str
    signing_time: str
    digest_algorithm: str
    signature_algorithm: str
    integrity_status: str
    trust_status: str
    coverage_status: str
    modification_status: str
    timestamp_status: str
    error: str = ""
    revocation_evidence: str = "absent"


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
    digital_signatures: tuple[DigitalSignatureReport, ...] = ()
    signature_validation_available: bool = False
    signature_validation_error: str = ""

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


def _safe_signature_text(value: object, *, limit: int = MAX_SIGNATURE_TEXT) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _iso_datetime(value: object) -> str:
    if value is None:
        return ""
    try:
        return _safe_signature_text(value.isoformat(), limit=80)
    except AttributeError:
        return _safe_signature_text(value, limit=80)


def _certificate_common_name(certificate: object) -> str:
    try:
        native = certificate.subject.native
        return _safe_signature_text(native.get("common_name") or "")
    except (AttributeError, TypeError):
        return ""


def _certificate_validity(certificate: object) -> tuple[str, str]:
    try:
        validity = certificate["tbs_certificate"]["validity"].native
        return (
            _iso_datetime(validity.get("not_before")),
            _iso_datetime(validity.get("not_after")),
        )
    except (KeyError, TypeError, ValueError):
        return "", ""


def _inspect_digital_signatures(
    path: str | Path,
) -> tuple[tuple[DigitalSignatureReport, ...], bool, str]:
    """Validate embedded signatures without network access or mutable trust state."""

    try:
        import certifi
        from pyhanko.keys import load_certs_from_pemder
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko.sign.validation.dss import DocumentSecurityStore
        from pyhanko_certvalidator import ValidationContext
    except ImportError:
        return (), False, ""

    # An untrusted signer is an expected result, not an application failure.
    logging.getLogger("pyhanko_certvalidator").setLevel(logging.CRITICAL)
    logging.getLogger("pyhanko.sign.validation").setLevel(logging.CRITICAL)
    try:
        trust_roots = tuple(load_certs_from_pemder((certifi.where(),)))
    except (OSError, ValueError):
        trust_roots = ()
    reports: list[DigitalSignatureReport] = []
    try:
        source = open(path, "rb")
    except OSError as exc:
        return (), True, _safe_signature_text(exc)
    with source:
        try:
            reader = PdfFileReader(source)
            signatures = tuple(reader.embedded_signatures)[:MAX_SIGNATURES]
        except BaseException as exc:
            return (), True, _safe_signature_text(exc)
        try:
            dss = DocumentSecurityStore.read_dss(reader)
            vri_entries = dss.vri_entries or {}
        except Exception:
            vri_entries = {}
        for signature in signatures:
            revocation_evidence = "absent"
            try:
                vri_key = DocumentSecurityStore.sig_content_identifier(
                    signature.sig_object["/Contents"]
                )
                vri_ref = vri_entries.get(vri_key)
                vri = vri_ref.get_object() if vri_ref is not None else {}
                if vri.get("/OCSP") or vri.get("/CRL"):
                    revocation_evidence = "embedded"
            except Exception:
                pass
            certificate = getattr(signature, "signer_cert", None)
            valid_from, valid_to = _certificate_validity(certificate)
            subject = _safe_signature_text(
                getattr(getattr(certificate, "subject", None), "human_friendly", "")
            )
            issuer = _safe_signature_text(
                getattr(getattr(certificate, "issuer", None), "human_friendly", "")
            )
            common_name = _certificate_common_name(certificate) or subject
            serial = ""
            fingerprint = ""
            try:
                serial = f"{int(certificate.serial_number):X}"
                fingerprint = _safe_signature_text(
                    certificate.sha256_fingerprint, limit=160
                )
            except (AttributeError, TypeError, ValueError):
                pass
            signing_time = _iso_datetime(
                getattr(signature, "self_reported_timestamp", None)
            )
            digest_algorithm = _safe_signature_text(
                getattr(signature, "md_algorithm", ""), limit=80
            )
            signature_algorithm = ""
            try:
                signature_algorithm = _safe_signature_text(
                    signature.signer_info["signature_algorithm"]["algorithm"].native,
                    limit=120,
                )
            except (KeyError, TypeError, ValueError):
                pass

            integrity = "error"
            trust = "unknown"
            coverage = "unknown"
            modification = "unknown"
            timestamp = "absent"
            error = ""
            try:
                status = validate_pdf_signature(
                    signature,
                    signer_validation_context=ValidationContext(
                        trust_roots=trust_roots,
                        allow_fetching=False,
                    ),
                )
                integrity = (
                    "valid"
                    if bool(getattr(status, "intact", False))
                    and bool(getattr(status, "valid", False))
                    else "invalid"
                )
                trust = (
                    "trusted"
                    if bool(getattr(status, "trusted", False))
                    else "untrusted"
                )
                coverage = _safe_signature_text(
                    getattr(
                        getattr(status, "coverage", None), "name", "unknown"
                    ).lower(),
                    limit=80,
                )
                modification = _safe_signature_text(
                    getattr(
                        getattr(status, "modification_level", None),
                        "name",
                        "unknown",
                    ).lower(),
                    limit=80,
                )
                signing_time = _iso_datetime(
                    getattr(status, "signer_reported_dt", None)
                ) or signing_time
                digest_algorithm = _safe_signature_text(
                    getattr(status, "md_algorithm", digest_algorithm), limit=80
                )
                signature_algorithm = _safe_signature_text(
                    getattr(status, "pkcs7_signature_mechanism", signature_algorithm),
                    limit=120,
                )
                timestamp_status = getattr(status, "timestamp_validity", None)
                if timestamp_status is not None:
                    if not (
                        bool(getattr(timestamp_status, "intact", False))
                        and bool(getattr(timestamp_status, "valid", False))
                    ):
                        timestamp = "invalid"
                    elif bool(getattr(timestamp_status, "trusted", False)):
                        timestamp = "trusted"
                    else:
                        timestamp = "untrusted"
            except BaseException as exc:
                error = _safe_signature_text(exc)

            reports.append(
                DigitalSignatureReport(
                    field_name=_safe_signature_text(
                        getattr(signature, "field_name", ""), limit=256
                    ),
                    signer_name=common_name,
                    certificate_subject=subject,
                    certificate_issuer=issuer,
                    certificate_serial=serial,
                    certificate_valid_from=valid_from,
                    certificate_valid_to=valid_to,
                    certificate_sha256=fingerprint,
                    signing_time=signing_time,
                    digest_algorithm=digest_algorithm,
                    signature_algorithm=signature_algorithm,
                    integrity_status=integrity,
                    trust_status=trust,
                    coverage_status=coverage,
                    modification_status=modification,
                    timestamp_status=timestamp,
                    error=error,
                    revocation_evidence=revocation_evidence,
                )
            )
    return tuple(reports), True, ""


def inspect_document(
    path: str | Path, *, encrypted_source: bool = False
) -> DocumentInspectionReport:
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

        (
            signature_reports,
            signature_validation_available,
            signature_validation_error,
        ) = _inspect_digital_signatures(path)
        if (
            signed_signatures
            and signature_validation_available
            and not signature_reports
            and not signature_validation_error
        ):
            signature_validation_error = (
                "Signed fields were detected, but their signature data could not be read."
            )
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
            digital_signatures=signature_reports,
            signature_validation_available=signature_validation_available,
            signature_validation_error=signature_validation_error,
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
        report_values = dict(result["report"])
        raw_signatures = report_values.pop("digital_signatures", ())
        if not isinstance(raw_signatures, (list, tuple)):
            raise TypeError("invalid signatures")
        report_values["digital_signatures"] = tuple(
            DigitalSignatureReport(**value) for value in raw_signatures
        )
        report = DocumentInspectionReport(**report_values)
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
        report.signature_validation_available,
    ):
        if type(value) is not bool:
            raise ValueError("The inspection report contains an invalid flag.")
    if len(report.digital_signatures) > MAX_SIGNATURES:
        raise ValueError("The inspection report contains too many signatures.")
    if (
        not isinstance(report.signature_validation_error, str)
        or len(report.signature_validation_error) > MAX_SIGNATURE_TEXT
    ):
        raise ValueError("The inspection report contains an invalid signature error.")
    allowed_statuses = {
        "integrity_status": {"valid", "invalid", "error"},
        "trust_status": {"trusted", "untrusted", "unknown"},
        "coverage_status": {
            "entire_file",
            "entire_revision",
            "contiguous_block_from_start",
            "unclear",
            "unknown",
        },
        "modification_status": {
            "none",
            "lta_updates",
            "form_filling",
            "annotations",
            "other",
            "unknown",
        },
        "timestamp_status": {"absent", "trusted", "untrusted", "invalid"},
        "revocation_evidence": {"absent", "embedded"},
    }
    for signature in report.digital_signatures:
        for field_name in (
            "field_name",
            "signer_name",
            "certificate_subject",
            "certificate_issuer",
            "certificate_serial",
            "certificate_valid_from",
            "certificate_valid_to",
            "certificate_sha256",
            "signing_time",
            "digest_algorithm",
            "signature_algorithm",
            "error",
        ):
            value = getattr(signature, field_name)
            if not isinstance(value, str) or len(value) > MAX_SIGNATURE_TEXT:
                raise ValueError("The inspection report contains invalid signature text.")
        for field_name, allowed in allowed_statuses.items():
            if getattr(signature, field_name) not in allowed:
                raise ValueError("The inspection report contains an invalid signature status.")
    return report, None


def main() -> int:
    import sys

    if len(sys.argv) != 2:
        return 2
    return run_inspection_job(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
