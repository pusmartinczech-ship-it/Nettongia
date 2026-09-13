from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .engine import CompressionResult, PdfEngine
from .recovery import (
    RecoverySnapshot,
    read_recovery_snapshot,
    validate_recovery_assets,
    validate_recovery_pages,
    write_recovery_snapshot,
)


WRITE_JOB_FORMAT = "openpdf-editor-document-write"
WRITE_JOB_SCHEMA_VERSION = 1
MAX_JOB_BYTES = 1024 * 1024
COMPRESSION_PROFILES = {"lossless", "balanced", "strong"}


def prepare_write_job(
    workspace: str | Path,
    snapshot: RecoverySnapshot,
    output_path: str | Path,
    compression_profile: str | None,
) -> tuple[Path, Path]:
    """Create a validated, non-executable job package for a child process."""

    if (
        compression_profile is not None
        and compression_profile not in COMPRESSION_PROFILES
    ):
        raise ValueError("The compression profile is invalid.")
    output = Path(output_path)
    if output.suffix.lower() != ".pdf":
        raise ValueError("The document write target must be a PDF.")
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    snapshot_path = root / "snapshot.openpdf-recovery"
    result_path = root / "result.json"
    job_path = root / "job.json"
    write_recovery_snapshot(snapshot_path, snapshot)
    descriptor = {
        "format": WRITE_JOB_FORMAT,
        "schema_version": WRITE_JOB_SCHEMA_VERSION,
        "snapshot_path": str(snapshot_path),
        "output_path": str(output),
        "result_path": str(result_path),
        "compression_profile": compression_profile,
    }
    encoded = json.dumps(
        descriptor,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > MAX_JOB_BYTES:
        raise ValueError("The document write job is too large.")
    job_path.write_bytes(encoded)
    return job_path, result_path


def _read_job(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    data = source.read_bytes()
    if len(data) > MAX_JOB_BYTES:
        raise ValueError("The document write job is too large.")
    try:
        job = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The document write job is damaged.") from exc
    if not isinstance(job, dict):
        raise ValueError("The document write job is invalid.")
    if job.get("format") != WRITE_JOB_FORMAT:
        raise ValueError("The document write job format is invalid.")
    if job.get("schema_version") != WRITE_JOB_SCHEMA_VERSION:
        raise ValueError("The document write job version is not supported.")
    for key in ("snapshot_path", "output_path", "result_path"):
        value = job.get(key)
        if not isinstance(value, str) or not value or len(value) > 32_768:
            raise ValueError(f"Invalid document write field: {key}.")
    profile = job.get("compression_profile")
    if profile is not None and profile not in COMPRESSION_PROFILES:
        raise ValueError("The compression profile is invalid.")
    output = Path(job["output_path"])
    if output.suffix.lower() != ".pdf":
        raise ValueError("The document write target must be a PDF.")
    return job


def _write_result(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
    finally:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass


def read_write_result(path: str | Path) -> tuple[CompressionResult | None, str | None]:
    source = Path(path)
    data = source.read_bytes()
    if len(data) > MAX_JOB_BYTES:
        raise ValueError("The document write result is too large.")
    try:
        result = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The document write result is damaged.") from exc
    if not isinstance(result, dict) or result.get("format") != WRITE_JOB_FORMAT:
        raise ValueError("The document write result is invalid.")
    if result.get("status") == "failed":
        message = result.get("error")
        return None, str(message or "The document write process failed.")
    if result.get("status") != "succeeded":
        raise ValueError("The document write result status is invalid.")
    compression = result.get("compression")
    if compression is None:
        return None, None
    if not isinstance(compression, dict):
        raise ValueError("The compression result is invalid.")
    try:
        values = (
            int(compression["original_size"]),
            int(compression["output_size"]),
            int(compression["recompressed_images"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("The compression result is invalid.") from exc
    if any(value < 0 for value in values):
        raise ValueError("The compression result is invalid.")
    return CompressionResult(*values), None


def run_write_job(job_path: str | Path) -> int:
    """Run one save/compression job and return a process exit code."""

    result_path: Path | None = None
    engine = PdfEngine()
    try:
        job = _read_job(job_path)
        result_path = Path(job["result_path"])
        snapshot = read_recovery_snapshot(job["snapshot_path"])
        validate_recovery_assets(snapshot)
        engine.load_bytes(snapshot.pdf_bytes)
        validate_recovery_pages(snapshot, engine.page_count)
        profile = job.get("compression_profile")
        if profile is None:
            engine.save(
                job["output_path"],
                snapshot.edits,
                snapshot.signatures,
                snapshot.inserted_images,
                snapshot.deleted_images,
                snapshot.inserted_texts,
            )
            compression_payload = None
        else:
            result = engine.save_compressed(
                job["output_path"],
                profile,
                snapshot.edits,
                snapshot.signatures,
                snapshot.inserted_images,
                snapshot.deleted_images,
                snapshot.inserted_texts,
            )
            compression_payload = {
                "original_size": result.original_size,
                "output_size": result.output_size,
                "recompressed_images": result.recompressed_images,
            }
        _write_result(
            result_path,
            {
                "format": WRITE_JOB_FORMAT,
                "status": "succeeded",
                "compression": compression_payload,
            },
        )
        return 0
    except Exception as exc:
        if result_path is not None:
            try:
                _write_result(
                    result_path,
                    {
                        "format": WRITE_JOB_FORMAT,
                        "status": "failed",
                        "error": str(exc),
                    },
                )
            except OSError:
                pass
        return 1
    finally:
        engine.close()


def main() -> int:
    import sys

    if len(sys.argv) != 2:
        return 2
    return run_write_job(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
