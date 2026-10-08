import os
import time
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from asn1crypto import keys as asn1_keys
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QApplication
from pyhanko.sign.timestamps import DummyTimeStamper

from openpdf_editor.dialogs import CertificateSignatureDialog
from openpdf_editor.digital_signature_coordinator import (
    DigitalSignatureCoordinator,
    SignatureContext,
)
from openpdf_editor.digital_signature_worker import (
    CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE,
    prepare_signature_job,
    read_signature_result,
    run_signature_job,
    validate_timestamp_url,
    _verify_revocation_store,
)
from openpdf_editor.engine import PdfEngine, TextPlacement
from openpdf_editor.inspection_worker import inspect_document
from openpdf_editor.recovery import RecoverySnapshot


def _certificate(path: Path, password: str = "test-password") -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        (
            x509.NameAttribute(x509.NameOID.COMMON_NAME, "Nettongia Test Signer"),
            x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, "Nettongia Tests"),
            x509.NameAttribute(x509.NameOID.COUNTRY_NAME, "CZ"),
        )
    )
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(2)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"nettongia-test",
            key,
            certificate,
            None,
            serialization.BestAvailableEncryption(password.encode("utf-8")),
        )
    )


def _dummy_timestamper() -> DummyTimeStamper:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        (x509.NameAttribute(x509.NameOID.COMMON_NAME, "Nettongia Test TSA"),)
    )
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(3)
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage((x509.ExtendedKeyUsageOID.TIME_STAMPING,)),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    certificate_der = certificate.public_bytes(serialization.Encoding.DER)
    key_der = key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return DummyTimeStamper(
        asn1_x509.Certificate.load(certificate_der),
        asn1_keys.PrivateKeyInfo.load(key_der),
    )


def _certificate_with_crl(path: Path) -> tuple[bytes, bytes]:
    """Create a private CA, an end-entity signing certificate, and a valid CRL."""
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signer_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Nettongia Test CA")])
    signer_name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Nettongia CRL Signer")])
    now = datetime.now(timezone.utc)
    root = (
        x509.CertificateBuilder().subject_name(root_name).issuer_name(root_name)
        .public_key(root_key.public_key()).serial_number(100)
        .not_valid_before(now - timedelta(days=2)).not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False,
            key_encipherment=False, data_encipherment=False, key_agreement=False,
            key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False,
        ), critical=True)
        .sign(root_key, hashes.SHA256())
    )
    leaf = (
        x509.CertificateBuilder().subject_name(signer_name).issuer_name(root_name)
        .public_key(signer_key.public_key()).serial_number(101)
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=90))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True,
            key_encipherment=False, data_encipherment=False, key_agreement=False,
            key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False,
        ), critical=True)
        .add_extension(x509.CRLDistributionPoints((x509.DistributionPoint(
            full_name=(x509.UniformResourceIdentifier("http://localhost.test/crl"),),
            relative_name=None, reasons=None, crl_issuer=None,
        ),)), critical=False)
        .sign(root_key, hashes.SHA256())
    )
    crl = (
        x509.CertificateRevocationListBuilder().issuer_name(root_name)
        .last_update(now - timedelta(hours=1)).next_update(now + timedelta(days=7))
        .add_extension(x509.CRLNumber(1), critical=False)
        .sign(root_key, hashes.SHA256())
    )
    path.write_bytes(pkcs12.serialize_key_and_certificates(
        b"nettongia-test", signer_key, leaf, [root],
        serialization.BestAvailableEncryption(b"test-password"),
    ))
    return root.public_bytes(serialization.Encoding.DER), crl.public_bytes(serialization.Encoding.DER)


def _snapshot(*, signature_field: bool = True, pdf_bytes: bytes | None = None) -> RecoverySnapshot:
    if pdf_bytes is None:
        document = pymupdf.open()
        page = document.new_page(width=420, height=300)
        if signature_field:
            widget = pymupdf.Widget()
            widget.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
            widget.field_name = "ApprovalSignature"
            widget.rect = pymupdf.Rect(40, 210, 260, 270)
            page.add_widget(widget)
        pdf_bytes = document.tobytes()
        document.close()
    return RecoverySnapshot(
        pdf_bytes=pdf_bytes,
        edits=(),
        inserted_texts=(
            TextPlacement(
                key="signed-worker-text",
                page_index=0,
                bbox=(40, 40, 360, 90),
                text="Content included before signing",
                font_size=14,
            ),
        ),
        signatures=(),
        inserted_images=(),
        deleted_images=(),
        document_path=None,
        save_target_path=None,
        current_page=0,
        render_scale=1.0,
    )


def _two_signature_field_snapshot() -> RecoverySnapshot:
    document = pymupdf.open()
    page = document.new_page(width=420, height=300)
    for index, name in enumerate(("ApprovalSignature", "ReviewSignature")):
        widget = pymupdf.Widget()
        widget.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
        widget.field_name = name
        widget.rect = pymupdf.Rect(40 + index * 180, 210, 200 + index * 180, 270)
        page.add_widget(widget)
    pdf_bytes = document.tobytes()
    document.close()
    return replace(_snapshot(pdf_bytes=pdf_bytes), inserted_texts=())


def test_worker_signs_materialized_copy_without_serializing_password(
    tmp_path: Path, monkeypatch
) -> None:
    password = "test-password"
    certificate = tmp_path / "signer.p12"
    output = tmp_path / "signed-copy.pdf"
    _certificate(certificate, password)
    job, result_path = prepare_signature_job(
        tmp_path / "job",
        _snapshot(),
        output,
        certificate,
        field_name="ApprovalSignature",
        create_field=False,
        reason="Approved",
        location="Ostrava",
    )
    assert password not in job.read_text(encoding="utf-8")
    assert password.encode() not in (job.parent / "snapshot.openpdf-recovery").read_bytes()
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, password)

    assert run_signature_job(job) == 0
    assert CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE not in os.environ
    result, error = read_signature_result(result_path)
    assert error is None
    assert result is not None
    assert result.field_name == "ApprovalSignature"
    assert result.signer_name == "Nettongia Test Signer"
    with pymupdf.open(output) as document:
        assert "Content included before signing" in document[0].get_text()
    report = inspect_document(output)
    signature = report.digital_signatures[0]
    assert signature.integrity_status == "valid"
    assert signature.revocation_evidence == "absent"
    assert signature.field_name == "ApprovalSignature"


def test_worker_can_create_invisible_signature_field(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = tmp_path / "signer.pfx"
    output = tmp_path / "signed-copy.pdf"
    _certificate(certificate)
    job, result_path = prepare_signature_job(
        tmp_path / "job",
        _snapshot(signature_field=False),
        output,
        certificate,
        field_name="NettongiaSignature1",
        create_field=True,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")

    assert run_signature_job(job) == 0
    result, error = read_signature_result(result_path)
    assert error is None and result is not None
    assert result.field_name == "NettongiaSignature1"
    assert inspect_document(output).digital_signatures[0].integrity_status == "valid"


def test_worker_places_visible_signature_on_selected_page(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = tmp_path / "signer.p12"
    output = tmp_path / "visible-signed.pdf"
    _certificate(certificate)
    document = pymupdf.open()
    document.new_page(width=420, height=300)
    document.new_page(width=420, height=300)
    snapshot = replace(_snapshot(pdf_bytes=document.tobytes()), inserted_texts=())
    document.close()
    job, result_path = prepare_signature_job(
        tmp_path / "job",
        snapshot,
        output,
        certificate,
        field_name="VisibleSignature",
        create_field=True,
        visible=True,
        page_index=1,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")

    assert run_signature_job(job) == 0
    result, error = read_signature_result(result_path)
    assert error is None and result is not None
    with pymupdf.open(output) as signed:
        assert not list(signed[0].widgets() or ())
        fields = list(signed[1].widgets() or ())
        assert len(fields) == 1
        assert fields[0].field_name == "VisibleSignature"
        assert fields[0].rect.width > 100 and fields[0].rect.height > 40
        assert fields[0].rect in signed[1].rect
        before = pymupdf.open(stream=snapshot.pdf_bytes, filetype="pdf")
        try:
            box = fields[0].rect
            signed_pix = signed[1].get_pixmap(clip=box, alpha=False)
            before_pix = before[1].get_pixmap(clip=box, alpha=False)
            assert signed_pix.samples != before_pix.samples
        finally:
            before.close()
    assert inspect_document(output).digital_signatures[0].integrity_status == "valid"


def test_worker_rejects_invalid_visible_page_without_replacing_target(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = tmp_path / "signer.p12"
    output = tmp_path / "existing.pdf"
    output.write_bytes(b"keep this file")
    _certificate(certificate)
    job, result_path = prepare_signature_job(
        tmp_path / "job", _snapshot(signature_field=False), output, certificate,
        field_name="VisibleSignature", create_field=True, visible=True, page_index=99,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")
    assert run_signature_job(job) == 1
    result, error = read_signature_result(result_path)
    assert result is None and "page does not exist" in error
    assert output.read_bytes() == b"keep this file"


def test_visible_signature_stays_on_cropped_page(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = tmp_path / "signer.p12"
    output = tmp_path / "cropped-signed.pdf"
    _certificate(certificate)
    document = pymupdf.open()
    page = document.new_page(width=420, height=300)
    page.set_cropbox(pymupdf.Rect(50, 60, 350, 240))
    page.set_rotation(90)
    snapshot = replace(_snapshot(pdf_bytes=document.tobytes()), inserted_texts=())
    document.close()
    job, result_path = prepare_signature_job(
        tmp_path / "job", snapshot, output, certificate,
        field_name="VisibleSignature", create_field=True, visible=True,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")

    assert run_signature_job(job) == 0
    result, error = read_signature_result(result_path)
    assert result is not None and error is None
    with pymupdf.open(output) as signed:
        widget = next(signed[0].widgets())
        assert signed[0].rect.contains(widget.rect * signed[0].rotation_matrix)
    assert inspect_document(output).digital_signatures[0].integrity_status == "valid"


@pytest.mark.parametrize(
    "url",
    (
        "http://tsa.example.com",
        "ftp://tsa.example.com",
        "https://user:secret@tsa.example.com",
        "https://tsa.example.com/path with spaces",
        "https://tsa.example.com/#fragment",
    ),
)
def test_timestamp_url_rejects_unsafe_addresses(url: str) -> None:
    with pytest.raises(ValueError):
        validate_timestamp_url(url)


def test_worker_embeds_and_verifies_requested_timestamp(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = tmp_path / "signer.p12"
    output = tmp_path / "timestamped-copy.pdf"
    _certificate(certificate)
    timestamper = _dummy_timestamper()
    monkeypatch.setattr(
        "openpdf_editor.digital_signature_worker.HTTPTimeStamper",
        lambda url, *, https, timeout: timestamper,
    )
    job, result_path = prepare_signature_job(
        tmp_path / "job",
        _snapshot(),
        output,
        certificate,
        field_name="ApprovalSignature",
        create_field=False,
        timestamp_url="https://tsa.example.com/rfc3161",
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")

    assert run_signature_job(job) == 0
    result, error = read_signature_result(result_path)
    assert error is None and result is not None
    assert result.timestamp_status in {"trusted", "untrusted"}
    signature = inspect_document(output).digital_signatures[0]
    assert signature.timestamp_status == result.timestamp_status


def test_revocation_option_requires_timestamp_and_rejects_missing_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = tmp_path / "signer.p12"
    output = tmp_path / "existing.pdf"
    output.write_bytes(b"existing copy")
    _certificate(certificate)
    with pytest.raises(ValueError, match="requires a timestamp server"):
        prepare_signature_job(
            tmp_path / "missing-tsa", _snapshot(), output, certificate,
            field_name="ApprovalSignature", create_field=False,
            embed_revocation_info=True,
        )
    timestamper = _dummy_timestamper()
    monkeypatch.setattr(
        "openpdf_editor.digital_signature_worker.HTTPTimeStamper",
        lambda url, *, https, timeout: timestamper,
    )
    # Trusting the test leaf as an anchor gives no issuer revocation evidence.
    from pyhanko_certvalidator import ValidationContext
    from pyhanko.sign import signers
    signer = signers.SimpleSigner.load_pkcs12(
        certificate, passphrase=b"test-password"
    )
    monkeypatch.setattr(
        "openpdf_editor.digital_signature_worker._revocation_context",
        lambda: ValidationContext(
            trust_roots=[signer.signing_cert, timestamper.tsa_cert],
            allow_fetching=False,
        ),
    )
    job, result_path = prepare_signature_job(
        tmp_path / "without-crl", _snapshot(), output, certificate,
        field_name="ApprovalSignature", create_field=False,
        timestamp_url="https://tsa.example.com/rfc3161", embed_revocation_info=True,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")
    assert run_signature_job(job) == 1
    result, error = read_signature_result(result_path)
    assert result is None and error
    assert output.read_bytes() == b"existing copy"


def test_worker_embeds_crl_and_verifies_pades_revision(
    tmp_path: Path, monkeypatch
) -> None:
    from pyhanko_certvalidator import ValidationContext

    certificate = tmp_path / "with-crl.p12"
    output = tmp_path / "pades-lt.pdf"
    root_der, crl_der = _certificate_with_crl(certificate)
    timestamper = _dummy_timestamper()
    monkeypatch.setattr(
        "openpdf_editor.digital_signature_worker.HTTPTimeStamper",
        lambda url, *, https, timeout: timestamper,
    )
    monkeypatch.setattr(
        "openpdf_editor.digital_signature_worker._revocation_context",
        lambda: ValidationContext(
            trust_roots=[asn1_x509.Certificate.load(root_der), timestamper.tsa_cert],
            crls=[crl_der], allow_fetching=False, revocation_mode="hard-fail",
        ),
    )
    job, result_path = prepare_signature_job(
        tmp_path / "with-crl", _snapshot(), output, certificate,
        field_name="ApprovalSignature", create_field=False,
        timestamp_url="https://tsa.example.com/rfc3161", embed_revocation_info=True,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")
    assert run_signature_job(job) == 0, read_signature_result(result_path)
    result, error = read_signature_result(result_path)
    assert error is None and result.revocation_status == "embedded"
    _verify_revocation_store(output, "ApprovalSignature")
    report = inspect_document(output)
    assert report.digital_signatures[0].integrity_status == "valid"
    assert report.digital_signatures[0].revocation_evidence == "embedded"
    with pymupdf.open(output) as pdf:
        assert pdf.xref_get_key(pdf.pdf_catalog(), "DSS/CRLs")[0] in {"array", "xref"}


def test_revocation_evidence_preserves_an_existing_signature(
    tmp_path: Path, monkeypatch
) -> None:
    from pyhanko_certvalidator import ValidationContext

    certificate = tmp_path / "signer.p12"
    first_output = tmp_path / "first.pdf"
    second_output = tmp_path / "second-with-evidence.pdf"
    root_der, crl_der = _certificate_with_crl(certificate)
    first_job, _first_result = prepare_signature_job(
        tmp_path / "first-job", _two_signature_field_snapshot(), first_output,
        certificate, field_name="ApprovalSignature", create_field=False,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")
    assert run_signature_job(first_job) == 0
    timestamper = _dummy_timestamper()
    monkeypatch.setattr(
        "openpdf_editor.digital_signature_worker.HTTPTimeStamper",
        lambda url, *, https, timeout: timestamper,
    )
    monkeypatch.setattr(
        "openpdf_editor.digital_signature_worker._revocation_context",
        lambda: ValidationContext(
            trust_roots=[asn1_x509.Certificate.load(root_der), timestamper.tsa_cert],
            crls=[crl_der], allow_fetching=False, revocation_mode="hard-fail",
        ),
    )
    second_job, second_result = prepare_signature_job(
        tmp_path / "second-job",
        replace(_snapshot(pdf_bytes=first_output.read_bytes()), inserted_texts=()),
        second_output, certificate, field_name="ReviewSignature", create_field=False,
        timestamp_url="https://tsa.example.com/rfc3161", embed_revocation_info=True,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")
    assert run_signature_job(second_job) == 0, read_signature_result(second_result)
    assert second_output.read_bytes().startswith(first_output.read_bytes())
    _verify_revocation_store(second_output, "ReviewSignature")
    with pytest.raises(ValueError, match="requested PAdES signature"):
        _verify_revocation_store(second_output, "ApprovalSignature")
    report = inspect_document(second_output)
    assert len(report.digital_signatures) == 2
    assert all(item.integrity_status == "valid" for item in report.digital_signatures)
    assert [item.revocation_evidence for item in report.digital_signatures] == [
        "absent", "embedded"
    ]


def test_wrong_password_does_not_replace_existing_target(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = tmp_path / "signer.p12"
    output = tmp_path / "existing.pdf"
    _certificate(certificate)
    original = b"existing target remains unchanged"
    output.write_bytes(original)
    job, result_path = prepare_signature_job(
        tmp_path / "job",
        _snapshot(),
        output,
        certificate,
        field_name="ApprovalSignature",
        create_field=False,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "wrong-password")

    assert run_signature_job(job) == 1
    result, error = read_signature_result(result_path)
    assert result is None and error
    assert output.read_bytes() == original


def test_worker_refuses_to_overwrite_open_document(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = tmp_path / "signer.p12"
    source = tmp_path / "open-document.pdf"
    _certificate(certificate)
    snapshot = _snapshot()
    source.write_bytes(snapshot.pdf_bytes)
    snapshot = replace(snapshot, document_path=str(source))
    job, result_path = prepare_signature_job(
        tmp_path / "job",
        snapshot,
        source,
        certificate,
        field_name="ApprovalSignature",
        create_field=False,
    )
    original = source.read_bytes()
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")

    assert run_signature_job(job) == 1
    result, error = read_signature_result(result_path)
    assert result is None
    assert error and "must not overwrite" in error
    assert source.read_bytes() == original


def test_worker_refuses_pending_changes_after_existing_certificate_signature(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = tmp_path / "signer.p12"
    first_output = tmp_path / "first.pdf"
    _certificate(certificate)
    first_job, _result_path = prepare_signature_job(
        tmp_path / "first-job",
        _snapshot(),
        first_output,
        certificate,
        field_name="ApprovalSignature",
        create_field=False,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")
    assert run_signature_job(first_job) == 0

    blocked_output = tmp_path / "blocked.pdf"
    second_job, second_result = prepare_signature_job(
        tmp_path / "second-job",
        _snapshot(pdf_bytes=first_output.read_bytes()),
        blocked_output,
        certificate,
        field_name="SecondSignature",
        create_field=True,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")
    assert run_signature_job(second_job) == 1
    result, error = read_signature_result(second_result)
    assert result is None
    assert error and "Save or discard" in error
    assert not blocked_output.exists()


def test_worker_appends_second_signature_and_preserves_first_revision(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = tmp_path / "signer.p12"
    first_output = tmp_path / "first.pdf"
    second_output = tmp_path / "second.pdf"
    _certificate(certificate)
    first_job, _first_result = prepare_signature_job(
        tmp_path / "first-job",
        _two_signature_field_snapshot(),
        first_output,
        certificate,
        field_name="ApprovalSignature",
        create_field=False,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")
    assert run_signature_job(first_job) == 0
    first_report = inspect_document(first_output)
    assert len(first_report.digital_signatures) == 1
    assert first_report.digital_signatures[0].integrity_status == "valid"

    second_snapshot = replace(
        _snapshot(pdf_bytes=first_output.read_bytes()), inserted_texts=()
    )
    second_job, second_result_path = prepare_signature_job(
        tmp_path / "second-job",
        second_snapshot,
        second_output,
        certificate,
        field_name="ReviewSignature",
        create_field=False,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")

    assert run_signature_job(second_job) == 0
    result, error = read_signature_result(second_result_path)
    assert error is None and result is not None
    assert result.field_name == "ReviewSignature"
    second_report = inspect_document(second_output)
    assert len(second_report.digital_signatures) == 2
    signatures = {item.field_name: item for item in second_report.digital_signatures}
    assert signatures["ApprovalSignature"].integrity_status == "valid"
    assert signatures["ReviewSignature"].integrity_status == "valid"


def test_worker_can_append_visible_field_after_existing_signature(
    tmp_path: Path, monkeypatch
) -> None:
    certificate = tmp_path / "signer.p12"
    first_output = tmp_path / "first.pdf"
    second_output = tmp_path / "second.pdf"
    _certificate(certificate)
    first_job, _first_result = prepare_signature_job(
        tmp_path / "first-job",
        replace(_snapshot(), inserted_texts=()),
        first_output,
        certificate,
        field_name="ApprovalSignature",
        create_field=False,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")
    assert run_signature_job(first_job) == 0

    second_snapshot = replace(
        _snapshot(pdf_bytes=first_output.read_bytes()), inserted_texts=()
    )
    second_job, _second_result = prepare_signature_job(
        tmp_path / "second-job",
        second_snapshot,
        second_output,
        certificate,
        field_name="NettongiaSignature2",
        create_field=True,
        visible=True,
    )
    monkeypatch.setenv(CERTIFICATE_PASSWORD_ENVIRONMENT_VARIABLE, "test-password")

    assert run_signature_job(second_job) == 0
    signatures = {
        item.field_name: item for item in inspect_document(second_output).digital_signatures
    }
    assert set(signatures) == {"ApprovalSignature", "NettongiaSignature2"}
    assert all(item.integrity_status == "valid" for item in signatures.values())
    with pymupdf.open(second_output) as document:
        visible = [
            widget for widget in document[0].widgets()
            if widget.field_name == "NettongiaSignature2"
        ]
        assert len(visible) == 1
        assert visible[0].rect.width > 100


def test_certificate_dialog_requires_file_and_password(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    certificate = tmp_path / "signer.p12"
    _certificate(certificate)
    dialog = CertificateSignatureDialog(
        ["ApprovalSignature"], "NettongiaSignature1"
    )
    assert not dialog.sign_button.isEnabled()
    dialog.certificate_edit.setText(str(certificate))
    assert not dialog.sign_button.isEnabled()
    dialog.password_edit.setText("test-password")
    assert dialog.sign_button.isEnabled()
    assert dialog.signature_settings()["field_name"] == "ApprovalSignature"
    dialog.target_combo.setCurrentIndex(dialog.target_combo.count() - 1)
    assert dialog.signature_settings()["create_field"] is True
    dialog.timestamp_box.setChecked(True)
    assert not dialog.sign_button.isEnabled()
    dialog.timestamp_edit.setText("http://tsa.example.com")
    assert not dialog.sign_button.isEnabled()
    dialog.timestamp_edit.setText("https://tsa.example.com")
    assert dialog.sign_button.isEnabled()
    assert dialog.signature_settings()["timestamp_url"] == "https://tsa.example.com"
    dialog.revocation_box.setChecked(True)
    assert dialog.signature_settings()["embed_revocation_info"] is True
    dialog.timestamp_box.setChecked(False)
    assert dialog.signature_settings()["embed_revocation_info"] is False
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_certificate_dialog_selects_visible_page(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = CertificateSignatureDialog(
        [], "NettongiaSignature1", page_count=3, current_page=1
    )
    assert not dialog.page_combo.isEnabled()
    dialog.target_combo.setCurrentIndex(dialog.target_combo.count() - 1)
    assert dialog.page_combo.isEnabled()
    assert dialog.signature_settings()["visible"] is True
    assert dialog.signature_settings()["page_index"] == 1
    dialog.page_combo.setCurrentIndex(2)
    assert dialog.signature_settings()["page_index"] == 2
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_coordinator_signs_in_child_process_and_cleans_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    app = QApplication.instance() or QApplication([])
    certificate = tmp_path / "signer.p12"
    output = tmp_path / "coordinated-signed.pdf"
    workspace = tmp_path / "signature-workspace"
    _certificate(certificate)
    monkeypatch.setattr(
        "openpdf_editor.digital_signature_coordinator.tempfile.mkdtemp",
        lambda **_kwargs: str(workspace),
    )
    coordinator = DigitalSignatureCoordinator()
    outcomes = []
    coordinator.completed.connect(outcomes.append)
    coordinator.start(
        _snapshot(),
        SignatureContext(output, 3, 5),
        certificate,
        "test-password",
        field_name="ApprovalSignature",
        create_field=False,
    )
    deadline = time.monotonic() + 15
    while coordinator.is_running and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
        time.sleep(0.005)

    assert not coordinator.is_running
    assert len(outcomes) == 1
    assert outcomes[0].error is None
    assert outcomes[0].result is not None
    assert output.is_file()
    assert not workspace.exists()
