from __future__ import annotations

import json
import os
import threading
from hashlib import sha256
from datetime import datetime, timezone
from typing import TextIO

from PySide6.QtCore import QtMsgType, qInstallMessageHandler


TRACE_FORMAT = "nettongia-local-crash-trace"
TRACE_VERSION = 1

_SIGNATURE_PHASES = {
    "dialog_initialized",
    "mode_changed",
    "accept_requested",
    "signature_data_started",
    "drawn_crop_started",
    "drawn_crop_finished",
    "typed_metrics_started",
    "typed_metrics_ready",
    "typed_image_allocated",
    "typed_painter_started",
    "typed_draw_started",
    "typed_draw_finished",
    "png_encode_started",
    "png_encode_finished",
    "field_request_received",
    "field_resolved",
    "preview_visual_added",
    "preview_value_stored",
    "dialog_opening",
    "dialog_cancelled",
    "dialog_accepted",
    "payload_ready",
    "bbox_ready",
    "state_captured",
    "state_appended",
    "state_push_started",
    "state_push_finished",
    "notice_started",
    "notice_finished",
    "free_placement_started",
    "free_placement_ready",
    "handled_error",
}
_INTEGER_DETAILS = {
    "page_index",
    "history_index",
    "image_width",
    "image_height",
    "payload_bytes",
    "signature_count",
    "text_length",
}
_BOOLEAN_DETAILS = {"read_only", "required", "frozen"}
_ENUM_DETAILS = {
    "mode": {"drawn", "typed", "unknown"},
    "context": {"field", "free", "unknown"},
    "outcome": {"started", "succeeded", "failed", "cancelled"},
    "severity": {"debug", "info", "warning", "critical", "fatal", "unknown"},
}

_lock = threading.RLock()
_stream: TextIO | None = None
_previous_qt_handler = None


def _timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_record(kind: str, details: dict[str, object]) -> bool:
    with _lock:
        stream = _stream
        if stream is None:
            return False
        record = {
            "format": TRACE_FORMAT,
            "version": TRACE_VERSION,
            "timestamp_utc": _timestamp(),
            "kind": kind,
            "details": details,
        }
        try:
            stream.write(
                "NETTONGIA_TRACE "
                + json.dumps(record, ensure_ascii=True, separators=(",", ":"))
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
            return True
        except (OSError, ValueError):
            return False


def record_signature_trace(phase: str, **details: object) -> bool:
    """Write one content-free signature breadcrumb to the raw local crash log."""

    if phase not in _SIGNATURE_PHASES:
        return False
    safe: dict[str, object] = {"phase": phase}
    for key, value in details.items():
        if key in _INTEGER_DETAILS and isinstance(value, int) and not isinstance(value, bool):
            safe[key] = max(-1, min(value, 100_000_000))
        elif key in _BOOLEAN_DETAILS and isinstance(value, bool):
            safe[key] = value
        elif key in _ENUM_DETAILS and isinstance(value, str) and value in _ENUM_DETAILS[key]:
            safe[key] = value
    return _write_record("signature", safe)


def _qt_severity(message_type: QtMsgType) -> str:
    return {
        QtMsgType.QtDebugMsg: "debug",
        QtMsgType.QtInfoMsg: "info",
        QtMsgType.QtWarningMsg: "warning",
        QtMsgType.QtCriticalMsg: "critical",
        QtMsgType.QtFatalMsg: "fatal",
    }.get(message_type, "unknown")


def _qt_message_handler(message_type, context, message) -> None:
    # Keep Qt diagnostics useful for matching repeated failures without writing
    # message text, which could theoretically contain document-derived values.
    encoded = str(message).encode("utf-8", errors="replace")
    _write_record(
        "qt_message",
        {
            "severity": _qt_severity(message_type),
            "message_length": len(encoded),
            "message_sha256": sha256(encoded).hexdigest(),
        },
    )
    previous = _previous_qt_handler
    if previous is not None:
        previous(message_type, context, message)


def install_crash_trace(stream: TextIO, *, frozen: bool) -> None:
    global _stream, _previous_qt_handler
    with _lock:
        _stream = stream
        _previous_qt_handler = qInstallMessageHandler(_qt_message_handler)
    _write_record("session", {"phase": "started", "frozen": bool(frozen)})


def uninstall_crash_trace() -> None:
    global _stream, _previous_qt_handler
    with _lock:
        previous = _previous_qt_handler
        _previous_qt_handler = None
        qInstallMessageHandler(previous)
        _stream = None
