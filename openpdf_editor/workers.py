from __future__ import annotations

from dataclasses import dataclass
from threading import Event

try:
    import pymupdf
except ImportError:  # PyMuPDF before 1.24
    import fitz as pymupdf
from PySide6.QtCore import QObject, QRunnable, Signal

from .engine import (
    ImageDeletion,
    ImagePlacement,
    PdfEngine,
    SignaturePlacement,
    TextEdit,
    TextPlacement,
)
from .recovery import RecoveryCancelled, RecoverySnapshot, write_recovery_snapshot


@dataclass(frozen=True)
class RenderedTile:
    """One RGB page tile positioned in target-scale scene pixels."""

    requested_rect: tuple[int, int, int, int]
    x: int
    y: int
    width: int
    height: int
    stride: int
    samples: bytes


class TileRenderSignals(QObject):
    tile_ready = Signal(int, object)
    finished = Signal(int)
    failed = Signal(int, str)


class TileRenderTask(QRunnable):
    """Render target-resolution page regions from a private PDF snapshot."""

    def __init__(
        self,
        request_id: int,
        source_bytes: bytes,
        page_index: int,
        scale: float,
        tile_rects: tuple[tuple[int, int, int, int], ...],
        edits: tuple[TextEdit, ...] = (),
        signatures: tuple[SignaturePlacement, ...] = (),
        inserted_images: tuple[ImagePlacement, ...] = (),
        deleted_images: tuple[ImageDeletion, ...] = (),
        inserted_texts: tuple[TextPlacement, ...] = (),
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.source_bytes = bytes(source_bytes)
        self.page_index = page_index
        self.scale = min(4.0, max(0.25, float(scale)))
        self.tile_rects = tile_rects
        self.edits = edits
        self.signatures = signatures
        self.inserted_images = inserted_images
        self.deleted_images = deleted_images
        self.inserted_texts = inserted_texts
        self.signals = TileRenderSignals()
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:  # noqa: D401 - QRunnable entry point
        if self._cancelled.is_set():
            return
        engine: PdfEngine | None = None
        document = None
        try:
            has_mutations = any(
                (
                    self.edits,
                    self.signatures,
                    self.inserted_images,
                    self.deleted_images,
                    self.inserted_texts,
                )
            )
            if has_mutations:
                engine = PdfEngine()
                engine.load_bytes(self.source_bytes)
                if self._cancelled.is_set():
                    return
                document = engine.build_document(
                    self.edits,
                    self.signatures,
                    self.inserted_images,
                    self.deleted_images,
                    self.inserted_texts,
                )
                # build_document() returns an independent snapshot.  Release
                # the engine's second PyMuPDF handle before rasterising tiles;
                # keeping both handles alive is costly on large PDFs.
                engine.close()
                engine = None
            else:
                # The overwhelmingly common browsing path needs only one PDF
                # handle.  Previously load_bytes() opened the source and
                # build_document() opened it again even though there were no
                # pending edits.
                document = pymupdf.open(stream=self.source_bytes, filetype="pdf")
            if self._cancelled.is_set():
                return
            page = document[self.page_index]
            matrix = pymupdf.Matrix(self.scale, self.scale)
            for requested_rect in self.tile_rects:
                if self._cancelled.is_set():
                    return
                x0, y0, x1, y1 = requested_rect
                clip = pymupdf.Rect(
                    x0 / self.scale,
                    y0 / self.scale,
                    x1 / self.scale,
                    y1 / self.scale,
                ).intersect(page.rect)
                if clip.is_empty:
                    continue
                pixmap = page.get_pixmap(
                    matrix=matrix,
                    clip=clip,
                    alpha=False,
                    annots=True,
                )
                if self._cancelled.is_set():
                    return
                self.signals.tile_ready.emit(
                    self.request_id,
                    RenderedTile(
                        requested_rect=requested_rect,
                        x=pixmap.x,
                        y=pixmap.y,
                        width=pixmap.width,
                        height=pixmap.height,
                        stride=pixmap.stride,
                        samples=bytes(pixmap.samples),
                    ),
                )
            if not self._cancelled.is_set():
                self.signals.finished.emit(self.request_id)
        except Exception as exc:
            if not self._cancelled.is_set():
                self.signals.failed.emit(self.request_id, str(exc))
        finally:
            if document is not None:
                document.close()
            if engine is not None:
                engine.close()


class SearchSignals(QObject):
    """Signals emitted by a background PDF search task."""

    finished = Signal(int, object)
    failed = Signal(int, str)


class SearchTask(QRunnable):
    """Search a snapshot of the current document outside the GUI thread.

    The task receives immutable-ish state snapshots instead of the live
    ``PdfEngine``.  PyMuPDF documents are not shared between threads, which
    keeps searching safe while the user continues editing or navigating.
    """

    def __init__(
        self,
        request_id: int,
        source_bytes: bytes,
        query: str,
        edits: tuple[TextEdit, ...],
        signatures: tuple[SignaturePlacement, ...],
        inserted_images: tuple[ImagePlacement, ...],
        deleted_images: tuple[ImageDeletion, ...],
        inserted_texts: tuple[TextPlacement, ...],
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.source_bytes = bytes(source_bytes)
        self.query = query
        self.edits = edits
        self.signatures = signatures
        self.inserted_images = inserted_images
        self.deleted_images = deleted_images
        self.inserted_texts = inserted_texts
        self.signals = SearchSignals()
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:  # noqa: D401 - QRunnable entry point
        engine = PdfEngine()
        document = None
        try:
            engine.load_bytes(self.source_bytes)
            document = engine.build_document(
                self.edits,
                self.signatures,
                self.inserted_images,
                self.deleted_images,
                self.inserted_texts,
            )
            matches: list[tuple[int, tuple[float, float, float, float]]] = []
            for page_index, page in enumerate(document):
                if self._cancelled.is_set():
                    return
                for rect in page.search_for(self.query):
                    if self._cancelled.is_set():
                        return
                    if rect.is_empty:
                        continue
                    matches.append(
                        (page_index, (rect.x0, rect.y0, rect.x1, rect.y1))
                    )
            if not self._cancelled.is_set():
                self.signals.finished.emit(self.request_id, matches)
        except Exception as exc:
            if not self._cancelled.is_set():
                self.signals.failed.emit(self.request_id, str(exc))
        finally:
            if document is not None:
                document.close()
            engine.close()


class RecoverySignals(QObject):
    """Signals emitted by a background recovery write."""

    finished = Signal(int, object)


class RecoveryTask(QRunnable):
    """Atomically save an immutable editor snapshot outside the GUI thread."""

    def __init__(
        self,
        request_id: int,
        path: str,
        snapshot: RecoverySnapshot,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.path = path
        self.snapshot = snapshot
        self.signals = RecoverySignals()
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        error: str | None = None
        try:
            write_recovery_snapshot(self.path, self.snapshot, self._cancelled)
        except RecoveryCancelled:
            pass
        except Exception as exc:
            error = str(exc)
        finally:
            self.signals.finished.emit(self.request_id, error)
