from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DocumentSession:
    """Identity and revision state for the active PDF document."""

    document_path: Path | None = None
    save_target_path: Path | None = None
    saved_history_index: int | None = None
    document_generation: int = 0
    content_revision: int = 0

    def has_unsaved_changes(self, *, is_open: bool, history_index: int) -> bool:
        return is_open and (
            self.saved_history_index is None
            or self.saved_history_index != history_index
        )

    def activate(
        self,
        document_path: Path | None,
        *,
        save_target_path: Path | None,
        already_saved: bool,
    ) -> None:
        self.document_generation += 1
        self.content_revision += 1
        self.document_path = document_path
        self.save_target_path = save_target_path
        self.saved_history_index = 0 if already_saved else None

    def close(self) -> None:
        self.document_generation += 1
        self.content_revision += 1
        self.document_path = None
        self.save_target_path = None
        self.saved_history_index = None

    def content_changed(self, *, history_index: int) -> None:
        if (
            self.saved_history_index is not None
            and self.saved_history_index > history_index
        ):
            self.saved_history_index = None
        self.content_revision += 1

    def revision_changed(self) -> None:
        self.content_revision += 1

    def saved(
        self,
        path: Path,
        *,
        history_index: int,
        snapshot_revision: int | None = None,
    ) -> bool:
        """Record a save and report whether it contains the current revision."""

        self.document_path = path
        self.save_target_path = path
        current_snapshot = (
            snapshot_revision is None
            or snapshot_revision == self.content_revision
        )
        self.saved_history_index = history_index if current_snapshot else None
        return current_snapshot

    def snapshot_matches(
        self,
        *,
        document_generation: int,
        content_revision: int,
    ) -> tuple[bool, bool]:
        return (
            document_generation == self.document_generation,
            content_revision == self.content_revision,
        )


@dataclass(frozen=True)
class DocumentWriteContext:
    """Immutable identity of one asynchronous document-write request."""

    path: Path
    document_generation: int
    content_revision: int
    compression_profile: str | None = None
    show_confirmation: bool = False
    update_document_identity: bool = True

    def matches(self, session: DocumentSession) -> tuple[bool, bool]:
        return session.snapshot_matches(
            document_generation=self.document_generation,
            content_revision=self.content_revision,
        )
