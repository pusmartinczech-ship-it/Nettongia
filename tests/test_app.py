from pathlib import Path

from openpdf_editor.app import _finish_local_crash_log, _start_local_crash_log
from openpdf_editor.crash_trace import record_signature_trace


def test_empty_crash_log_is_removed_after_clean_exit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path, stream, previous_hook = _start_local_crash_log()
    assert path is not None
    assert stream is not None
    assert path.exists()

    _finish_local_crash_log(path, stream, previous_hook, clean_exit=True)
    assert not path.exists()


def test_nonempty_crash_log_is_retained(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path, stream, previous_hook = _start_local_crash_log()
    assert path is not None
    assert stream is not None
    stream.write("diagnostic\n")

    _finish_local_crash_log(path, stream, previous_hook)
    contents = path.read_text(encoding="utf-8")
    assert "NETTONGIA_TRACE" in contents
    assert contents.endswith("diagnostic\n")


def test_previous_crash_log_survives_the_next_clean_start(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = tmp_path / "OpenPDF Editor"
    root.mkdir()
    (root / "crash.log").write_text("previous native crash\n", encoding="utf-8")

    path, stream, previous_hook = _start_local_crash_log()

    assert path == root / "crash.log"
    assert (root / "crash.previous.log").read_text(encoding="utf-8") == (
        "previous native crash\n"
    )
    _finish_local_crash_log(path, stream, previous_hook, clean_exit=True)
    assert not path.exists()
    assert (root / "crash.previous.log").exists()


def test_signature_crash_trace_is_synchronous_and_content_free(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path, stream, previous_hook = _start_local_crash_log()
    assert path is not None

    assert record_signature_trace(
        "typed_draw_started",
        mode="typed",
        text_length=10,
        document_text="classified PDF text",
        signature_text="Private Name",
    )

    contents = path.read_text(encoding="utf-8")
    assert '"phase":"typed_draw_started"' in contents
    assert '"mode":"typed"' in contents
    assert '"text_length":10' in contents
    assert "classified PDF text" not in contents
    assert "Private Name" not in contents
    _finish_local_crash_log(path, stream, previous_hook)


def test_clean_exit_removes_trace_only_log(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path, stream, previous_hook = _start_local_crash_log()
    assert path is not None

    record_signature_trace("dialog_opening", context="field")
    assert path.exists()

    _finish_local_crash_log(path, stream, previous_hook, clean_exit=True)
    assert not path.exists()
