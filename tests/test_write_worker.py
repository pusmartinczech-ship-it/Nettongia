from pathlib import Path

import pymupdf
import pytest

from openpdf_editor.engine import PdfEngine, TextPlacement
from openpdf_editor.recovery import RecoverySnapshot
from openpdf_editor.write_worker import (
    prepare_write_job,
    read_write_result,
    run_write_job,
)


def _snapshot(*, page_index: int = 0) -> RecoverySnapshot:
    return RecoverySnapshot(
        pdf_bytes=PdfEngine.blank_document_bytes(420, 300),
        edits=(),
        inserted_texts=(
            TextPlacement(
                key="worker-text",
                page_index=page_index,
                bbox=(50, 60, 360, 130),
                text="Isolated worker output",
                font_size=18,
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


def test_write_worker_protocol_produces_editable_pdf(tmp_path: Path) -> None:
    output = tmp_path / "worker-output.pdf"
    job, result_path = prepare_write_job(
        tmp_path / "job",
        _snapshot(),
        output,
        None,
    )

    assert run_write_job(job) == 0
    result, error = read_write_result(result_path)
    assert result is None
    assert error is None
    with pymupdf.open(output) as document:
        assert "Isolated worker output" in document[0].get_text()


def test_write_worker_reports_invalid_snapshot_without_partial_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "invalid-output.pdf"
    job, result_path = prepare_write_job(
        tmp_path / "job",
        _snapshot(page_index=4),
        output,
        None,
    )

    assert run_write_job(job) == 1
    result, error = read_write_result(result_path)
    assert result is None
    assert error
    assert not output.exists()


def test_prepare_write_job_rejects_invalid_profile_and_extension(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="profile"):
        prepare_write_job(tmp_path / "a", _snapshot(), tmp_path / "a.pdf", "unknown")
    with pytest.raises(ValueError, match="must be a PDF"):
        prepare_write_job(tmp_path / "b", _snapshot(), tmp_path / "a.txt", None)
