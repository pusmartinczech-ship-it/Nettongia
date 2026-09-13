import json
import zipfile
from pathlib import Path

from openpdf_editor.diagnostics import (
    BUNDLE_FORMAT,
    DEFAULT_MAX_LOG_BYTES,
    OperationLog,
    build_diagnostic_bundle,
    file_size_bucket,
)


def test_operation_log_is_bounded_and_drops_sensitive_fields(tmp_path: Path) -> None:
    path = tmp_path / "operation-log.jsonl"
    log = OperationLog(path, max_bytes=2048, max_records=12)

    for page in range(80):
        assert log.record(
            "page_moved",
            operation="page_move",
            outcome="succeeded",
            from_page=page,
            to_page=page + 1,
            document_path=r"C:\Users\Martin\secret.pdf",
            document_text="confidential customer text",
            reason=r"C:\private\worker-error.txt",
        )
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "format": "openpdf-editor-operation-log",
                    "version": 1,
                    "timestamp_utc": r"C:\Users\Martin\secret.pdf",
                    "session_id": "customer-name",
                    "event": "page_moved",
                    "details": {"outcome": "succeeded"},
                }
            )
            + "\n"
        )

    assert path.stat().st_size <= 2048
    records = log.records()
    assert 1 <= len(records) <= 12
    serialized = json.dumps(records)
    assert "Martin" not in serialized
    assert "secret.pdf" not in serialized
    assert "confidential" not in serialized
    assert "worker-error" not in serialized
    assert "customer-name" not in serialized
    assert records[-1]["details"]["to_page"] == 80


def test_diagnostic_bundle_contains_only_fixed_anonymized_members(tmp_path: Path) -> None:
    log = OperationLog(tmp_path / "operations.jsonl")
    assert log.record(
        "document_opened",
        operation="open",
        outcome="succeeded",
        page_count=14,
        file_size_bucket="10_50_mib",
    )
    crash_path = tmp_path / "crash.log"
    crash_path.write_text(
        r"Traceback C:\Users\Martin\customer\secret.pdf customer text",
        encoding="utf-8",
    )
    target = tmp_path / "diagnostics.zip"

    result = build_diagnostic_bundle(
        target,
        operation_log=log,
        session_snapshot={
            "document_open": True,
            "page_count": 14,
            "current_page": 3,
            "file_size_bucket": "10_50_mib",
            "language": "cs",
            "theme": "dark",
            "unsaved_changes": True,
            "pending_text_edits": 2,
            "document_path": r"C:\Users\Martin\customer\secret.pdf",
            "document_text": "customer text",
        },
        crash_path=crash_path,
    )

    assert result.path == target
    assert result.size_bytes == target.stat().st_size
    assert result.operation_records == 1
    with zipfile.ZipFile(target) as archive:
        assert sorted(archive.namelist()) == [
            "crash-summary.json",
            "manifest.json",
            "operations.json",
            "session.json",
            "system.json",
        ]
        assert archive.testzip() is None
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == BUNDLE_FORMAT
        assert "raw crash-log contents" in " ".join(manifest["privacy"]["excluded"])
        crash = json.loads(archive.read("crash-summary.json"))
        assert crash["present"] is True
        combined = b"\n".join(archive.read(name) for name in archive.namelist())
        assert b"Martin" not in combined
        assert b"secret.pdf" not in combined
        assert b"customer text" not in combined


def test_file_size_buckets_do_not_reveal_exact_sizes() -> None:
    assert file_size_bucket(0) == "empty"
    assert file_size_bucket(500_000) == "under_1_mib"
    assert file_size_bucket(2_000_000) == "1_10_mib"
    assert file_size_bucket(20_000_000) == "10_50_mib"
    assert file_size_bucket(100_000_000) == "50_200_mib"
    assert file_size_bucket(300_000_000) == "over_200_mib"
    assert DEFAULT_MAX_LOG_BYTES == 256 * 1024
