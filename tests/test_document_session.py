from pathlib import Path

from openpdf_editor.document_session import DocumentSession, DocumentWriteContext


def test_new_document_session_is_dirty_until_saved() -> None:
    session = DocumentSession()
    session.activate(None, save_target_path=None, already_saved=False)

    assert session.document_generation == 1
    assert session.content_revision == 1
    assert session.has_unsaved_changes(is_open=True, history_index=0)

    target = Path("new-document.pdf")
    assert session.saved(target, history_index=0)
    assert session.document_path == target
    assert session.save_target_path == target
    assert not session.has_unsaved_changes(is_open=True, history_index=0)


def test_background_save_of_older_revision_keeps_session_dirty() -> None:
    output = Path("edited.pdf")
    session = DocumentSession()
    session.activate(Path("source.pdf"), save_target_path=None, already_saved=True)
    snapshot_revision = session.content_revision

    session.content_changed(history_index=1)

    assert not session.saved(
        output,
        history_index=1,
        snapshot_revision=snapshot_revision,
    )
    assert session.document_path == output
    assert session.save_target_path == output
    assert session.saved_history_index is None
    assert session.has_unsaved_changes(is_open=True, history_index=1)


def test_undo_past_saved_state_invalidates_saved_marker() -> None:
    session = DocumentSession(saved_history_index=3)

    session.content_changed(history_index=2)

    assert session.saved_history_index is None
    assert session.content_revision == 1


def test_close_resets_identity_and_invalidates_pending_snapshots() -> None:
    session = DocumentSession()
    session.activate(
        Path("source.pdf"),
        save_target_path=Path("target.pdf"),
        already_saved=True,
    )
    generation = session.document_generation
    revision = session.content_revision

    session.close()

    assert session.document_path is None
    assert session.save_target_path is None
    assert session.saved_history_index is None
    assert session.snapshot_matches(
        document_generation=generation,
        content_revision=revision,
    ) == (False, False)


def test_write_context_keeps_snapshot_identity_and_options() -> None:
    session = DocumentSession(document_generation=4, content_revision=9)
    context = DocumentWriteContext(
        path=Path("output.pdf"),
        document_generation=4,
        content_revision=9,
        compression_profile="lossless",
        show_confirmation=True,
        update_document_identity=False,
    )

    assert context.matches(session) == (True, True)
    assert context.compression_profile == "lossless"
    assert context.show_confirmation
    assert not context.update_document_identity

    session.revision_changed()
    assert context.matches(session) == (True, False)
