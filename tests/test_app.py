from pathlib import Path

from openpdf_editor.app import _finish_local_crash_log, _start_local_crash_log


def test_empty_crash_log_is_removed_after_clean_exit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path, stream, previous_hook = _start_local_crash_log()
    assert path is not None
    assert stream is not None
    assert path.exists()

    _finish_local_crash_log(path, stream, previous_hook)
    assert not path.exists()


def test_nonempty_crash_log_is_retained(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path, stream, previous_hook = _start_local_crash_log()
    assert path is not None
    assert stream is not None
    stream.write("diagnostic\n")

    _finish_local_crash_log(path, stream, previous_hook)
    assert path.read_text(encoding="utf-8") == "diagnostic\n"


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
    _finish_local_crash_log(path, stream, previous_hook)
    assert not path.exists()
    assert (root / "crash.previous.log").exists()
