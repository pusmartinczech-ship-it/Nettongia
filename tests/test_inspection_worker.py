import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers
from pyhanko.sign.fields import SigFieldSpec, append_signature_field

from openpdf_editor.engine import PdfEngine
from openpdf_editor.dialogs import CertificateSignatureDialog
from openpdf_editor.inspection_worker import (
    DocumentInspectionReport,
    INSPECTION_FORMAT,
    inspect_document,
    prepare_inspection_job,
    read_inspection_result,
    run_inspection_job,
)
from openpdf_editor.main_window import MainWindow

SAMPLES = Path(
    os.environ.get("OPENPDF_TEST_SAMPLES", Path(__file__).resolve().parents[2] / "upload")
)


def _feature_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    for index, field_type in enumerate(
        (pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.PDF_WIDGET_TYPE_SIGNATURE)
    ):
        widget = pymupdf.Widget()
        widget.field_name = f"field-{index}"
        widget.field_type = field_type
        widget.rect = pymupdf.Rect(50, 50 + index * 50, 220, 82 + index * 50)
        page.add_widget(widget)
    page.add_text_annot((260, 100), "Review note")
    document.embfile_add("note.txt", b"attachment")
    document.add_ocg("Layer 1")
    document.xref_set_key(document.pdf_catalog(), "Collection", "<< /Type /Collection >>")
    document.xref_set_key(
        document.pdf_catalog(), "StructTreeRoot", "<< /Type /StructTreeRoot >>"
    )
    document.save(path)
    document.close()


def _signed_pdf(path: Path, certificate_path: Path) -> None:
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
        .serial_number(1)
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
    certificate_path.write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"nettongia-test",
            key,
            certificate,
            None,
            serialization.BestAvailableEncryption(b"test"),
        )
    )
    source = path.with_name("unsigned.pdf")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 100), "Signed test")
    document.save(source, deflate=False)
    document.close()
    signer = signers.SimpleSigner.load_pkcs12(certificate_path, passphrase=b"test")
    with source.open("rb") as input_stream:
        writer = IncrementalPdfFileWriter(input_stream)
        append_signature_field(
            writer,
            SigFieldSpec(
                sig_field_name="ApprovalSignature",
                box=(72, 600, 300, 680),
                on_page=0,
            ),
        )
        with path.open("wb") as output_stream:
            signers.sign_pdf(
                writer,
                signers.PdfSignatureMetadata(field_name="ApprovalSignature"),
                signer=signer,
                output=output_stream,
            )


def _application() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("OpenPDF Editor Tests")
    app.setApplicationName("OpenPDF Editor Tests")
    return app


def _wait_until(app: QApplication, predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QEventLoop.AllEvents, 25)
        time.sleep(0.005)
    assert predicate()


def test_inspector_reports_pdf_features_and_safe_render(tmp_path: Path) -> None:
    source = tmp_path / "features.pdf"
    _feature_pdf(source)

    report = inspect_document(source)

    assert report.digital_signature_fields == 1
    assert report.signed_digital_signatures == 0
    assert report.other_form_fields == 1
    assert report.annotations == 1
    assert report.embedded_files == 1
    assert report.optional_content_groups == 1
    assert report.portfolio
    assert report.tagged_pdf
    assert report.representative_pages_rendered == 1
    assert "forms" in report.warning_codes
    assert report.compatibility_level == "high_risk"


def test_inspector_separates_signature_integrity_from_certificate_trust(
    tmp_path: Path,
) -> None:
    source = tmp_path / "signed.pdf"
    _signed_pdf(source, tmp_path / "test-certificate.p12")

    report = inspect_document(source)

    assert report.signature_validation_available
    assert report.signed_digital_signatures == 1
    assert len(report.digital_signatures) == 1
    signature = report.digital_signatures[0]
    assert signature.field_name == "ApprovalSignature"
    assert signature.signer_name == "Nettongia Test Signer"
    assert signature.integrity_status == "valid"
    assert signature.trust_status == "untrusted"
    assert signature.coverage_status == "entire_file"
    assert signature.modification_status == "none"
    assert signature.timestamp_status == "absent"
    assert signature.digest_algorithm == "sha256"


def test_inspector_detects_tampered_signed_content(tmp_path: Path) -> None:
    source = tmp_path / "signed.pdf"
    _signed_pdf(source, tmp_path / "test-certificate.p12")
    payload = source.read_bytes()
    original = b"5369676e65642074657374"
    changed = b"5469676e65642074657374"
    assert payload.count(original) == 1
    source.write_bytes(payload.replace(original, changed, 1))

    signature = inspect_document(source).digital_signatures[0]

    assert signature.integrity_status == "invalid"


def test_signature_panel_shows_integrity_and_trust_separately(tmp_path: Path) -> None:
    app = _application()
    source = tmp_path / "signed.pdf"
    _signed_pdf(source, tmp_path / "test-certificate.p12")
    report = inspect_document(source)
    engine = PdfEngine()
    engine.open(source)
    window = MainWindow()
    window._activate_document(engine, source, already_saved=True)
    window._cancel_document_inspection()
    window._inspection_report = report
    window.language_code = "cs"
    window._retranslate_ui()
    window.show_digital_signatures()

    assert window.right_sidebar.isExpanded()
    assert window.right_sidebar.currentIndex() == window.digital_signatures_tool_index
    assert window.digital_signatures_list.count() == 1
    assert "Nettongia Test Signer" in window.digital_signatures_list.item(0).text()
    details = window.digital_signature_details.toPlainText()
    assert "Kryptografická integrita je v pořádku" in details
    assert "není v dodaném úložišti důvěryhodný" in details
    assert "SHA-256" in details

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_clean_signed_document_allows_an_additional_certificate_signature(
    tmp_path: Path,
) -> None:
    app = _application()
    source = tmp_path / "signed.pdf"
    _signed_pdf(source, tmp_path / "test-certificate.p12")
    engine = PdfEngine()
    engine.open(source)
    window = MainWindow()
    window._activate_document(engine, source, already_saved=True)
    window._cancel_document_inspection()
    window._inspection_report = inspect_document(source)
    window._update_actions()

    assert not window.has_unsaved_changes
    assert window.sign_with_certificate_action.isEnabled()

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_window_starts_certificate_signing_as_a_separate_copy(
    tmp_path: Path, monkeypatch
) -> None:
    app = _application()
    source = tmp_path / "unsigned-field.pdf"
    _feature_pdf(source)
    certificate = tmp_path / "signer.p12"
    certificate.write_bytes(b"test-certificate-placeholder")
    output = tmp_path / "signed-copy.pdf"
    engine = PdfEngine()
    engine.open(source)
    window = MainWindow()
    window._activate_document(engine, source, already_saved=True)
    window._cancel_document_inspection()
    window._inspection_report = inspect_document(source)
    window._update_actions()
    assert window.sign_with_certificate_action.isEnabled()

    monkeypatch.setattr(
        CertificateSignatureDialog, "exec", lambda _dialog: QDialog.Accepted
    )
    monkeypatch.setattr(
        CertificateSignatureDialog,
        "signature_settings",
        lambda _dialog: {
            "certificate_path": str(certificate),
            "certificate_password": "secret-test-password",
            "field_name": "field-1",
            "create_field": True,
            "visible": True,
            "page_index": 0,
            "reason": "Approved",
            "location": "Ostrava",
            "contact_info": "",
            "timestamp_url": "https://tsa.example.com/rfc3161",
        },
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(output), "PDF"),
    )
    calls = []
    monkeypatch.setattr(
        window._digital_signature_coordinator,
        "start",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert window.sign_with_certificate()
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[1].output_path == output
    assert args[2] == str(certificate)
    assert args[3] == "secret-test-password"
    assert kwargs["field_name"] == "field-1"
    assert kwargs["create_field"]
    assert kwargs["visible"]
    assert kwargs["page_index"] == 0
    assert kwargs["timestamp_url"] == "https://tsa.example.com/rfc3161"
    assert window.document_path == source

    if window._digital_signature_progress is not None:
        window._digital_signature_progress.close()
        window._digital_signature_progress.deleteLater()
        window._digital_signature_progress = None
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_compatibility_level_distinguishes_three_risk_tiers() -> None:
    values = dict(
        page_count=1,
        pdf_format="PDF 1.7",
        encrypted_source=False,
        digital_signature_fields=0,
        signed_digital_signatures=0,
        other_form_fields=0,
        xfa_forms=False,
        annotations=0,
        embedded_files=0,
        optional_content_groups=0,
        javascript=False,
        portfolio=False,
        tagged_pdf=False,
        oversized_pages=0,
        representative_pages_rendered=1,
    )

    assert DocumentInspectionReport(**values).compatibility_level == "safe"
    assert (
        DocumentInspectionReport(**(values | {"embedded_files": 1})).compatibility_level
        == "possible_changes"
    )
    assert (
        DocumentInspectionReport(**(values | {"xfa_forms": True})).compatibility_level
        == "high_risk"
    )


def test_inspection_job_round_trip_is_validated(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    _feature_pdf(source)
    job_path, result_path = prepare_inspection_job(
        tmp_path / "job", source.read_bytes(), encrypted_source=True
    )

    assert run_inspection_job(job_path) == 0
    report, error = read_inspection_result(result_path)

    assert error is None
    assert report is not None
    assert report.encrypted_source
    assert report.page_count == 1


def test_inspection_result_rejects_invalid_counts(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps(
            {
                "format": INSPECTION_FORMAT,
                "status": "succeeded",
                "report": {
                    "page_count": -1,
                    "pdf_format": "PDF",
                    "encrypted_source": False,
                    "digital_signature_fields": 0,
                    "signed_digital_signatures": 0,
                    "other_form_fields": 0,
                    "xfa_forms": False,
                    "annotations": 0,
                    "embedded_files": 0,
                    "optional_content_groups": 0,
                    "javascript": False,
                    "portfolio": False,
                    "tagged_pdf": False,
                    "oversized_pages": 0,
                    "representative_pages_rendered": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        read_inspection_result(result)
    except ValueError as exc:
        assert "invalid count" in str(exc)
    else:
        raise AssertionError("invalid inspection result was accepted")


def test_window_inspection_runs_outside_gui_process_and_keeps_ui_responsive(
    tmp_path: Path,
) -> None:
    app = _application()
    source = tmp_path / "features.pdf"
    _feature_pdf(source)
    engine = PdfEngine()
    engine.open(source)
    window = MainWindow()
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))

    window._activate_document(engine, source, already_saved=True)
    assert window._inspection_process is not None
    assert window.compatibility_action.isEnabled()
    assert not window.save_action.isEnabled()
    assert not window._confirm_document_write_compatibility()
    _wait_until(app, lambda: window._inspection_process is None)

    assert heartbeat == [True]
    assert window._inspection_error is None
    assert window._inspection_report is not None
    assert window._inspection_report.digital_signature_fields == 1
    assert window.save_action.isEnabled()
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize(
    "file_name",
    (
        "33-E00-01EKFA2A22_2018-03-16_CZ.pdf",
        "KS_Teil_2_2_01_KS26_ROB-KUKA_Projektspezifische_Vorgaben.pdf",
        "LV-15D_150026_________00_____ZSB_AFO_210_BLATT_001.pdf",
    ),
)
def test_supplied_reference_pdf_passes_isolated_inspection(
    tmp_path: Path, file_name: str
) -> None:
    source = SAMPLES / file_name
    if not source.is_file():
        pytest.skip("supplied regression PDF is not available")
    job_path, result_path = prepare_inspection_job(
        tmp_path / "job", source.read_bytes(), encrypted_source=False
    )

    assert run_inspection_job(job_path) == 0
    report, error = read_inspection_result(result_path)

    assert error is None
    assert report is not None
    assert report.page_count >= 1
    assert report.representative_pages_rendered in {1, 2, 3}


def test_digital_signature_warning_requires_explicit_confirmation(monkeypatch) -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300))
    window = MainWindow()
    window._activate_document(engine, None, already_saved=True)
    window._cancel_document_inspection()
    window._inspection_report = DocumentInspectionReport(
        page_count=1,
        pdf_format="PDF 1.7",
        encrypted_source=False,
        digital_signature_fields=1,
        signed_digital_signatures=1,
        other_form_fields=0,
        xfa_forms=False,
        annotations=0,
        embedded_files=0,
        optional_content_groups=0,
        javascript=False,
        portfolio=False,
        tagged_pdf=False,
        oversized_pages=0,
        representative_pages_rendered=1,
    )
    answers = iter((QMessageBox.Cancel, QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: next(answers))

    assert not window._confirm_document_write_compatibility()
    assert window._confirm_document_write_compatibility()
    assert window._compatibility_risk_acknowledged

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
