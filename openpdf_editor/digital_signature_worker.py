from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pymupdf
from pyhanko.keys import load_certs_from_pemder
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import signers
from pyhanko.sign.fields import SigFieldSpec, SigSeedSubFilter
from pyhanko.sign.timestamps import HTTPTimeStamper
from pyhanko.sign.validation.dss import DocumentSecurityStore, NoDSSFoundError
from pyhanko.stamp import TextStampStyle
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.fetchers.aiohttp_fetchers import AIOHttpFetcherBackend

from .engine import PdfEngine
from .inspection_worker import inspect_document
from .recovery import (
    RecoverySnapshot,
    read_recovery_snapshot,
    validate_recovery_assets,
    validate_recovery_pages,
    write_recovery_snapshot,
)


SIGNATURE_JOB_FORMAT = "nettongia-certificate-signature"
SIGNATURE_JOB_SCHEMA_VERSION = 1
MAX_DESCRIPTOR_BYTES = 1024 * 1024
MAX_CERTIFICATE_BYTES = 16 * 1024 * 1024
MAX_TIMESTAMP_URL_LENGTH = 2048
TIMESTAMP_REQUEST_TIMEOUT_SECONDS = 15
CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE = "NETTONGIA_CERTIFICATE_PASSWORD"


@dataclass(frozen=True)
class SignatureWriteResult:
    field_name: str
    signer_name: str
    certificate_sha256: str
    timestamp_status: str
    revocation_status: str = "not_requested"


def _revocation_context() -> ValidationContext:
    """Fetch revocation evidence using explicit trust roots and short requests."""
    import certifi

    trust_roots = tuple(load_certs_from_pemder((certifi.where(),)))
    if not trust_roots:
        raise ValueError(
            "No trusted certificate authorities are available for revocation checks."
        )
    return ValidationContext(
        trust_roots=trust_roots,
        allow_fetching=True,
        revocation_mode="hard-fail",
        fetcher_backend=AIOHttpFetcherBackend(per_request_timeout=10),
    )


def _verify_revocation_store(path: Path, field_name: str) -> None:
    """Reject a claimed LT copy if the signed PDF has no real revocation evidence."""
    with path.open("rb") as stream:
        reader = PdfFileReader(stream)
        signatures = [
            signature for signature in reader.embedded_signatures
            if signature.field_name == field_name
        ]
        if (
            len(signatures) != 1
            or str(signatures[0].sig_object.get("/SubFilter")) != "/ETSI.CAdES.detached"
        ):
            raise ValueError("The signed copy does not contain the requested PAdES signature.")
        try:
            dss = DocumentSecurityStore.read_dss(reader)
        except NoDSSFoundError as exc:
            raise ValueError("No document security store was saved with the signature.") from exc
        vri_key = DocumentSecurityStore.sig_content_identifier(
            signatures[0].sig_object["/Contents"]
        )
        vri_ref = (dss.vri_entries or {}).get(vri_key)
        vri = vri_ref.get_object() if vri_ref is not None else {}
        if not (dss.ocsps or dss.crls) or not (vri.get("/OCSP") or vri.get("/CRL")):
            raise ValueError(
                "No usable revocation responses were embedded. The signed copy was not saved."
            )


def _validate_text(name: str, value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"Invalid signature field: {name}.")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"Invalid signature field: {name}.")
    return value


def validate_timestamp_url(value: object) -> str:
    """Validate an optional RFC 3161 endpoint without retaining credentials."""
    url = _validate_text(
        "timestamp_url", value, maximum=MAX_TIMESTAMP_URL_LENGTH
    ).strip()
    if not url:
        return ""
    if any(character.isspace() for character in url):
        raise ValueError("The timestamp server address must not contain spaces.")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The timestamp server address is invalid.") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("The timestamp server must use a valid HTTPS address.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(
            "The timestamp server address must not contain sign-in credentials."
        )
    if parsed.fragment:
        raise ValueError("The timestamp server address must not contain a fragment.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("The timestamp server port is invalid.")
    return url


def prepare_signature_job(
    workspace: str | Path,
    snapshot: RecoverySnapshot,
    output_path: str | Path,
    certificate_path: str | Path,
    *,
    field_name: str,
    create_field: bool,
    visible: bool = False,
    page_index: int = 0,
    reason: str = "",
    location: str = "",
    contact_info: str = "",
    timestamp_url: str = "",
    embed_revocation_info: bool = False,
) -> tuple[Path, Path]:
    output = Path(output_path)
    certificate = Path(certificate_path)
    if output.suffix.lower() != ".pdf":
        raise ValueError("The signed document target must be a PDF.")
    if certificate.suffix.lower() not in {".p12", ".pfx"}:
        raise ValueError("Choose a PKCS#12 certificate file (.p12 or .pfx).")
    if not certificate.is_file():
        raise ValueError("The certificate file does not exist.")
    if certificate.stat().st_size > MAX_CERTIFICATE_BYTES:
        raise ValueError("The certificate file is too large.")
    field_name = _validate_text("field_name", field_name, maximum=256).strip()
    if not field_name:
        raise ValueError("The signature field name is empty.")
    if type(visible) is not bool or (visible and not create_field):
        raise ValueError("A visible signature requires a new signature field.")
    if type(page_index) is not int or page_index < 0 or (not visible and page_index):
        raise ValueError("The visible signature page is invalid.")
    reason = _validate_text("reason", reason, maximum=512).strip()
    location = _validate_text("location", location, maximum=512).strip()
    contact_info = _validate_text("contact_info", contact_info, maximum=512).strip()
    timestamp_url = validate_timestamp_url(timestamp_url)
    if type(embed_revocation_info) is not bool or (
        embed_revocation_info and not timestamp_url
    ):
        raise ValueError("Revocation embedding requires a timestamp server.")

    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    snapshot_path = root / "snapshot.openpdf-recovery"
    result_path = root / "result.json"
    job_path = root / "job.json"
    write_recovery_snapshot(snapshot_path, snapshot)
    descriptor = {
        "format": SIGNATURE_JOB_FORMAT,
        "schema_version": SIGNATURE_JOB_SCHEMA_VERSION,
        "snapshot_path": str(snapshot_path),
        "output_path": str(output),
        "certificate_path": str(certificate),
        "result_path": str(result_path),
        "field_name": field_name,
        "create_field": bool(create_field),
        "visible": visible,
        "page_index": page_index,
        "reason": reason,
        "location": location,
        "contact_info": contact_info,
        "timestamp_url": timestamp_url,
        "embed_revocation_info": embed_revocation_info,
    }
    encoded = json.dumps(
        descriptor, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(encoded) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The signature job is too large.")
    job_path.write_bytes(encoded)
    return job_path, result_path


def _read_job(path: str | Path) -> dict[str, Any]:
    data = Path(path).read_bytes()
    if len(data) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The signature job is too large.")
    try:
        job = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The signature job is damaged.") from exc
    if not isinstance(job, dict) or job.get("format") != SIGNATURE_JOB_FORMAT:
        raise ValueError("The signature job format is invalid.")
    if job.get("schema_version") != SIGNATURE_JOB_SCHEMA_VERSION:
        raise ValueError("The signature job version is not supported.")
    for key in ("snapshot_path", "output_path", "certificate_path", "result_path"):
        value = job.get(key)
        if not isinstance(value, str) or not value or len(value) > 32_768:
            raise ValueError(f"Invalid signature field: {key}.")
    output = Path(job["output_path"])
    certificate = Path(job["certificate_path"])
    if output.suffix.lower() != ".pdf":
        raise ValueError("The signed document target must be a PDF.")
    if certificate.suffix.lower() not in {".p12", ".pfx"}:
        raise ValueError("The certificate file type is invalid.")
    if not certificate.is_file() or certificate.stat().st_size > MAX_CERTIFICATE_BYTES:
        raise ValueError("The certificate file is unavailable or too large.")
    if type(job.get("create_field")) is not bool:
        raise ValueError("The signature-field option is invalid.")
    if type(job.get("visible", False)) is not bool or (
        job.get("visible", False) and not job["create_field"]
    ):
        raise ValueError("The visible signature option is invalid.")
    if type(job.get("page_index", 0)) is not int or job.get("page_index", 0) < 0:
        raise ValueError("The signature page number is invalid.")
    if not job.get("visible", False) and job.get("page_index", 0):
        raise ValueError("An invisible signature cannot select a page.")
    job["field_name"] = _validate_text(
        "field_name", job.get("field_name"), maximum=256
    ).strip()
    if not job["field_name"]:
        raise ValueError("The signature field name is empty.")
    for key in ("reason", "location", "contact_info"):
        job[key] = _validate_text(key, job.get(key, ""), maximum=512).strip()
    job["timestamp_url"] = validate_timestamp_url(job.get("timestamp_url", ""))
    if type(job.get("embed_revocation_info", False)) is not bool or (
        job.get("embed_revocation_info", False) and not job["timestamp_url"]
    ):
        raise ValueError("Revocation embedding requires a timestamp server.")
    job["embed_revocation_info"] = job.get("embed_revocation_info", False)
    return job


def _write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    finally:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass


def read_signature_result(
    path: str | Path,
) -> tuple[SignatureWriteResult | None, str | None]:
    data = Path(path).read_bytes()
    if len(data) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The signature result is too large.")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The signature result is damaged.") from exc
    if not isinstance(payload, dict) or payload.get("format") != SIGNATURE_JOB_FORMAT:
        raise ValueError("The signature result is invalid.")
    if payload.get("status") == "failed":
        return None, str(payload.get("error") or "Digital signing failed.")
    if payload.get("status") != "succeeded" or not isinstance(
        payload.get("result"), dict
    ):
        raise ValueError("The signature result status is invalid.")
    try:
        result = SignatureWriteResult(**payload["result"])
    except (TypeError, ValueError) as exc:
        raise ValueError("The signature result is invalid.") from exc
    for value in asdict(result).values():
        if not isinstance(value, str) or len(value) > 2048:
            raise ValueError("The signature result contains invalid text.")
    if result.timestamp_status not in {"absent", "trusted", "untrusted"}:
        raise ValueError("The signature result contains an invalid timestamp status.")
    if result.revocation_status not in {"not_requested", "embedded"}:
        raise ValueError("The signature result contains an invalid revocation status.")
    return result, None


def run_signature_job(job_path: str | Path) -> int:
    result_path: Path | None = None
    signed_temporary: Path | None = None
    engine = PdfEngine()
    try:
        job = _read_job(job_path)
        result_path = Path(job["result_path"])
        password = os.environ.pop(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "")
        if not password:
            raise ValueError("The certificate password is missing.")
        snapshot = read_recovery_snapshot(job["snapshot_path"])
        validate_recovery_assets(snapshot)
        output = Path(job["output_path"])
        if snapshot.document_path:
            try:
                same_as_source = output.resolve(strict=False) == Path(
                    snapshot.document_path
                ).resolve(strict=False)
            except OSError:
                same_as_source = os.path.normcase(
                    os.path.abspath(output)
                ) == os.path.normcase(os.path.abspath(snapshot.document_path))
            if same_as_source:
                raise ValueError(
                    "Certificate signing must not overwrite the open document."
                )
        source_path = Path(job["snapshot_path"]).with_name("source.pdf")
        source_path.write_bytes(snapshot.pdf_bytes)
        source_report = inspect_document(source_path)
        existing_signatures = source_report.digital_signatures
        if source_report.signed_digital_signatures != len(existing_signatures):
            raise ValueError(
                "Every existing signature must be available for verification."
            )
        signing_input_path = source_path
        if existing_signatures:
            if any(
                (
                    snapshot.edits,
                    snapshot.signatures,
                    snapshot.inserted_images,
                    snapshot.deleted_images,
                    snapshot.inserted_texts,
                )
            ):
                raise ValueError(
                    "Save or discard document changes before adding another signature."
                )
            if any(
                signature.integrity_status != "valid"
                for signature in existing_signatures
            ):
                raise ValueError(
                    "Every existing signature must pass integrity verification."
                )
        else:
            engine.load_bytes(snapshot.pdf_bytes)
            validate_recovery_pages(snapshot, engine.page_count)
            materialized_path = Path(job["snapshot_path"]).with_name("materialized.pdf")
            engine.save(
                materialized_path,
                snapshot.edits,
                snapshot.signatures,
                snapshot.inserted_images,
                snapshot.deleted_images,
                snapshot.inserted_texts,
            )
            signing_input_path = materialized_path
        signer = signers.SimpleSigner.load_pkcs12(
            job["certificate_path"], passphrase=password.encode("utf-8")
        )
        if signer is None:
            raise ValueError("The certificate password is incorrect or the file is invalid.")

        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".pdf", dir=output.parent
        )
        signed_temporary = Path(temporary_name)
        metadata = signers.PdfSignatureMetadata(
            field_name=job["field_name"],
            reason=job["reason"] or None,
            location=job["location"] or None,
            contact_info=job["contact_info"] or None,
            subfilter=(SigSeedSubFilter.PADES if job["embed_revocation_info"] else None),
            embed_validation_info=job["embed_revocation_info"],
            validation_context=(
                _revocation_context() if job["embed_revocation_info"] else None
            ),
        )
        visible_box = None
        if job["visible"]:
            with pymupdf.open(signing_input_path) as document:
                page_index = job["page_index"]
                if page_index >= document.page_count:
                    raise ValueError("The visible signature page does not exist.")
                page = document[page_index]
                page_box = page.cropbox
                if page_box.width < 136 or page_box.height < 98:
                    raise ValueError("The selected page is too small for a visible signature.")
                # CropBox is expressed in PDF coordinates for the target field.
                right = int(page_box.x1) - 18
                bottom = int(page_box.y0) + 18
                visible_box = (
                    right - min(190, int(page_box.width) - 36),
                    bottom,
                    right,
                    bottom + 62,
                )
        new_field_spec = (
            SigFieldSpec(
                sig_field_name=job["field_name"],
                on_page=job["page_index"] if job["visible"] else 0,
                box=visible_box,
            )
            if job["create_field"]
            else None
        )
        timestamper = (
            HTTPTimeStamper(
                job["timestamp_url"],
                https=True,
                timeout=TIMESTAMP_REQUEST_TIMEOUT_SECONDS,
            )
            if job["timestamp_url"]
            else None
        )
        with signing_input_path.open("rb") as source, os.fdopen(
            descriptor, "w+b"
        ) as target:
            writer = IncrementalPdfFileWriter(source)
            pdf_signer = signers.PdfSigner(
                metadata,
                signer=signer,
                timestamper=timestamper,
                new_field_spec=new_field_spec,
                stamp_style=(
                    TextStampStyle(
                        stamp_text="Digitally signed\n%(ts)s",
                        border_width=1,
                    )
                    if job["visible"] else None
                ),
            )
            pdf_signer.sign_pdf(
                writer,
                existing_fields_only=not job["create_field"],
                output=target,
            )
            target.flush()
            os.fsync(target.fileno())

        report = inspect_document(signed_temporary)
        signature = next(
            (
                item
                for item in report.digital_signatures
                if item.field_name == job["field_name"]
            ),
            None,
        )
        if signature is None or signature.integrity_status != "valid":
            raise ValueError("The completed digital signature failed verification.")
        expected_existing = Counter(
            (item.field_name, item.certificate_sha256)
            for item in existing_signatures
        )
        verified_existing = Counter(
            (item.field_name, item.certificate_sha256)
            for item in report.digital_signatures
            if item.field_name != job["field_name"]
            and item.integrity_status == "valid"
        )
        if existing_signatures and not expected_existing <= verified_existing:
            raise ValueError(
                "At least one existing digital signature was not preserved."
            )
        expected_signature_count = len(existing_signatures) + 1
        if (
            len(report.digital_signatures) != expected_signature_count
            or report.signed_digital_signatures != expected_signature_count
        ):
            raise ValueError("The signed copy contains an unexpected signature count.")
        if job["timestamp_url"] and signature.timestamp_status not in {
            "trusted",
            "untrusted",
        }:
            raise ValueError("The timestamp server did not return a valid timestamp.")
        if job["embed_revocation_info"]:
            _verify_revocation_store(signed_temporary, job["field_name"])
        if job["visible"]:
            with pymupdf.open(signed_temporary) as document:
                page = document[job["page_index"]]
                widgets = [
                    widget for widget in (page.widgets() or ())
                    if widget.field_name == job["field_name"]
                ]
                if len(widgets) != 1:
                    raise ValueError("The visible signature field is missing.")
                widget = widgets[0]
                appearance_type, _appearance_value = document.xref_get_key(
                    widget.xref, "AP/N"
                )
                if (
                    widget.rect.is_empty
                    or not page.rect.contains(widget.rect * page.rotation_matrix)
                    or appearance_type != "xref"
                ):
                    raise ValueError("The visible signature appearance was not saved.")
        os.replace(signed_temporary, output)
        signed_temporary = None
        _write_json_atomic(
            result_path,
            {
                "format": SIGNATURE_JOB_FORMAT,
                "status": "succeeded",
                "result": asdict(
                    SignatureWriteResult(
                        field_name=signature.field_name,
                        signer_name=signature.signer_name,
                        certificate_sha256=signature.certificate_sha256,
                        timestamp_status=signature.timestamp_status,
                        revocation_status=(
                            "embedded" if job["embed_revocation_info"] else "not_requested"
                        ),
                    )
                ),
            },
        )
        return 0
    except Exception as exc:
        if result_path is not None:
            try:
                _write_json_atomic(
                    result_path,
                    {
                        "format": SIGNATURE_JOB_FORMAT,
                        "status": "failed",
                        "error": str(exc),
                    },
                )
            except OSError:
                pass
        return 1
    finally:
        os.environ.pop(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, None)
        engine.close()
        if signed_temporary is not None:
            try:
                signed_temporary.unlink(missing_ok=True)
            except OSError:
                pass


def main() -> int:
    import sys

    if len(sys.argv) != 2:
        return 2
    return run_signature_job(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
