from __future__ import annotations

import json
import os
import platform
import re
import sys
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pymupdf
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import qVersion

from . import __version__
from .branding import LEGACY_APP_NAME


LOG_FORMAT = "openpdf-editor-operation-log"
BUNDLE_FORMAT = "openpdf-editor-anonymized-diagnostics"
SCHEMA_VERSION = 1
DEFAULT_MAX_LOG_BYTES = 256 * 1024
DEFAULT_MAX_LOG_RECORDS = 512

_EVENTS = {
    "session_started",
    "document_opened",
    "document_closed",
    "state_changed",
    "page_deleted",
    "page_moved",
    "text_deleted",
    "visual_deleted",
    "ocr_started",
    "ocr_finished",
    "inspection_finished",
    "tile_render_failed",
    "document_write_started",
    "document_write_finished",
    "diagnostic_exported",
}
_INTEGER_DETAILS = {
    "page_count",
    "page_index",
    "from_page",
    "to_page",
    "history_index",
    "processed_pages",
    "words_inserted",
    "warning_count",
    "content_revision",
    "document_generation",
}
_BOOLEAN_DETAILS = {"restored", "encrypted", "copy"}
_ENUM_DETAILS = {
    "outcome": {"started", "succeeded", "failed", "cancelled", "discarded", "nothing"},
    "worker": {"inspection", "ocr", "tile", "write"},
    "reason": {"timeout", "process_error", "validation_error", "stale_result", "unknown"},
    "operation": {
        "open",
        "new",
        "page_delete",
        "page_move",
        "text_delete",
        "visual_delete",
        "save",
        "save_copy",
        "compress",
        "ocr",
        "export_diagnostics",
    },
    "file_size_bucket": {"empty", "under_1_mib", "1_10_mib", "10_50_mib", "50_200_mib", "over_200_mib"},
    "theme": {"automatic", "dark", "light"},
    "compatibility": {"unknown", "safe", "possible_changes", "high_risk", "failed"},
    "profile": {"none", "lossless", "balanced", "strong"},
}
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SESSION_ID_RE = re.compile(r"^[0-9a-f]{12}$")

_SNAPSHOT_INTEGER_KEYS = {
    "page_count",
    "current_page",
    "history_entries",
    "pending_text_edits",
    "pending_inserted_texts",
    "pending_images",
    "pending_signatures",
    "pending_image_deletions",
    "tile_cache_hits",
    "tile_cache_misses",
    "tile_cache_evictions",
}
_SNAPSHOT_BOOLEAN_KEYS = {"document_open", "unsaved_changes"}
_SNAPSHOT_ENUM_KEYS = {"theme", "language", "file_size_bucket", "compatibility"}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_size_bucket(size: int) -> str:
    size = max(0, int(size))
    if size == 0:
        return "empty"
    if size < 1024 * 1024:
        return "under_1_mib"
    if size < 10 * 1024 * 1024:
        return "1_10_mib"
    if size < 50 * 1024 * 1024:
        return "10_50_mib"
    if size < 200 * 1024 * 1024:
        return "50_200_mib"
    return "over_200_mib"


def error_reason(message: str | None) -> str:
    """Reduce a potentially sensitive worker error to a fixed diagnostic class."""

    lowered = (message or "").lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "validation" in lowered or "invalid" in lowered or "missing result" in lowered:
        return "validation_error"
    if "process" in lowered or "crash" in lowered or "exit" in lowered:
        return "process_error"
    return "unknown"


def default_diagnostics_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return base / LEGACY_APP_NAME


def default_operation_log_path() -> Path:
    return default_diagnostics_root() / "operation-log.jsonl"


def default_crash_log_path() -> Path:
    return default_diagnostics_root() / "crash.log"


def _safe_details(details: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in details.items():
        if key in _INTEGER_DETAILS and isinstance(value, int) and not isinstance(value, bool):
            safe[key] = max(-1, min(value, 1_000_000_000))
        elif key in _BOOLEAN_DETAILS and isinstance(value, bool):
            safe[key] = value
        elif key == "language" and isinstance(value, str) and _LANGUAGE_RE.fullmatch(value):
            safe[key] = value
        elif key in _ENUM_DETAILS and isinstance(value, str) and value in _ENUM_DETAILS[key]:
            safe[key] = value
    return safe


class OperationLog:
    """Small local JSON-lines log with a strict privacy-safe field allowlist."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        max_bytes: int = DEFAULT_MAX_LOG_BYTES,
        max_records: int = DEFAULT_MAX_LOG_RECORDS,
    ) -> None:
        self.path = Path(path) if path is not None else default_operation_log_path()
        self.max_bytes = max(1024, int(max_bytes))
        self.max_records = max(10, int(max_records))
        self.session_id = uuid4().hex[:12]
        self._lock = threading.Lock()

    def record(self, event: str, **details: object) -> bool:
        if event not in _EVENTS:
            return False
        record = {
            "format": LOG_FORMAT,
            "version": SCHEMA_VERSION,
            "timestamp_utc": utc_timestamp(),
            "session_id": self.session_id,
            "event": event,
            "details": _safe_details(details),
        }
        payload = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("ab") as stream:
                    stream.write(payload)
                    stream.flush()
                if self.path.stat().st_size > self.max_bytes:
                    self._compact_locked()
            return True
        except OSError:
            return False

    def _compact_locked(self) -> None:
        lines = self.path.read_bytes().splitlines(keepends=True)
        retained: list[bytes] = []
        budget = max(1024, int(self.max_bytes * 0.75))
        used = 0
        for line in reversed(lines[-self.max_records :]):
            if retained and used + len(line) > budget:
                break
            retained.append(line)
            used += len(line)
        retained.reverse()
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(b"".join(retained))
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def records(self) -> list[dict[str, object]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        accepted: list[dict[str, object]] = []
        for line in lines[-self.max_records :]:
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                continue
            if (
                not isinstance(record, dict)
                or record.get("format") != LOG_FORMAT
                or record.get("version") != SCHEMA_VERSION
                or record.get("event") not in _EVENTS
                or not isinstance(record.get("timestamp_utc"), str)
                or _TIMESTAMP_RE.fullmatch(record["timestamp_utc"]) is None
                or not isinstance(record.get("session_id"), str)
                or _SESSION_ID_RE.fullmatch(record["session_id"]) is None
                or not isinstance(record.get("details"), dict)
            ):
                continue
            accepted.append(
                {
                    "timestamp_utc": record["timestamp_utc"],
                    "session_id": record["session_id"],
                    "event": record["event"],
                    "details": _safe_details(record["details"]),
                }
            )
        return accepted


def sanitize_session_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in snapshot.items():
        if key in _SNAPSHOT_INTEGER_KEYS and isinstance(value, int) and not isinstance(value, bool):
            safe[key] = max(-1, min(value, 1_000_000_000))
        elif key in _SNAPSHOT_BOOLEAN_KEYS and isinstance(value, bool):
            safe[key] = value
        elif key == "language" and isinstance(value, str) and _LANGUAGE_RE.fullmatch(value):
            safe[key] = value
        elif key in _SNAPSHOT_ENUM_KEYS and key != "language":
            if isinstance(value, str) and value in _ENUM_DETAILS[key]:
                safe[key] = value
    return safe


def diagnostic_field_inventory() -> dict[str, list[str]]:
    return {
        "included": [
            "bundle generation time and fixed member list",
            "application and diagnostics format versions and frozen-build flag",
            "operating-system family, release and CPU architecture",
            "Python, Qt, PySide6 and PyMuPDF versions",
            "interface language and appearance mode",
            "page count, current page and coarse PDF size bucket",
            "unsaved-state flag and counts of pending editor objects",
            "tile-cache counters",
            "bounded operation timestamps, random per-start session identifiers, event names and fixed detail categories",
            "presence of current/previous local crash logs and the largest coarse size bucket",
        ],
        "excluded": [
            "PDF files and rendered pages",
            "document text, images, annotations and metadata",
            "file names, folder paths and recent-file history",
            "user name, computer name, IP and hardware identifiers",
            "raw exception messages and raw crash-log contents",
        ],
    }


def _system_snapshot() -> dict[str, object]:
    return {
        "application_version": __version__,
        "diagnostics_schema": SCHEMA_VERSION,
        "operating_system": platform.system() or "unknown",
        "os_release": platform.release() or "unknown",
        "architecture": platform.machine() or "unknown",
        "python_version": platform.python_version(),
        "qt_version": qVersion(),
        "pyside_version": pyside_version,
        "pymupdf_version": getattr(pymupdf, "VersionBind", "unknown"),
        "frozen_application": bool(getattr(sys, "frozen", False)),
    }


def _crash_summary(crash_path: str | Path | None) -> dict[str, object]:
    path = Path(crash_path) if crash_path is not None else default_crash_log_path()
    previous = path.with_name("crash.previous.log")

    def size_or_zero(candidate: Path) -> int:
        try:
            return max(0, candidate.stat().st_size)
        except OSError:
            return 0

    current_size = size_or_zero(path)
    previous_size = size_or_zero(previous)
    return {
        "present": current_size > 0 or previous_size > 0,
        "current_run_present": current_size > 0,
        "previous_run_present": previous_size > 0,
        "size_bucket": file_size_bucket(max(current_size, previous_size)),
    }


@dataclass(frozen=True)
class DiagnosticBundleResult:
    path: Path
    size_bytes: int
    operation_records: int


def build_diagnostic_bundle(
    target: str | Path,
    *,
    operation_log: OperationLog,
    session_snapshot: dict[str, object],
    crash_path: str | Path | None = None,
) -> DiagnosticBundleResult:
    """Create an atomic ZIP containing only allowlisted anonymized diagnostics."""

    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    operations = operation_log.records()
    manifest = {
        "format": BUNDLE_FORMAT,
        "version": SCHEMA_VERSION,
        "generated_utc": utc_timestamp(),
        "files": [
            "manifest.json",
            "system.json",
            "session.json",
            "operations.json",
            "crash-summary.json",
        ],
        "privacy": diagnostic_field_inventory(),
    }
    members = {
        "manifest.json": manifest,
        "system.json": _system_snapshot(),
        "session.json": sanitize_session_snapshot(session_snapshot),
        "operations.json": {
            "format": LOG_FORMAT,
            "version": SCHEMA_VERSION,
            "records": operations,
        },
        "crash-summary.json": _crash_summary(crash_path),
    }
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name, value in members.items():
                archive.writestr(
                    name,
                    json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                )
        with zipfile.ZipFile(temporary, "r") as archive:
            if sorted(archive.namelist()) != sorted(members):
                raise ValueError("diagnostic archive member mismatch")
            if archive.testzip() is not None:
                raise ValueError("diagnostic archive integrity check failed")
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return DiagnosticBundleResult(destination, destination.stat().st_size, len(operations))
