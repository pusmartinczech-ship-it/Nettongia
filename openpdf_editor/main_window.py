from __future__ import annotations

import copy
import math
import os
import shutil
import sys
import tempfile
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pymupdf
from PySide6.QtCore import (
    QAbstractItemModel,
    QByteArray,
    QEvent,
    QElapsedTimer,
    QLocale,
    QModelIndex,
    QPointF,
    QProcess,
    QRectF,
    QSettings,
    QSizeF,
    QStandardPaths,
    QThreadPool,
    QTimer,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QIcon,
    QImage,
    QKeyEvent,
    QKeySequence,
    QPageLayout,
    QPageSize,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QTransform,
    QDesktopServices,
)
from PySide6.QtPrintSupport import (
    QAbstractPrintDialog,
    QPrintDialog,
    QPrintPreviewDialog,
    QPrintPreviewWidget,
    QPrinter,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFontComboBox,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .branding import APP_NAME, LEGACY_APP_NAME
from .crash_trace import record_signature_trace
from .dialogs import (
    CompressionDialog,
    EditTextDialog,
    FormFieldDialog,
    NewDocumentDialog,
    SignatureDialog,
)
from .document_session import DocumentSession, DocumentWriteContext
from .document_write_coordinator import (
    DocumentWriteCoordinator,
    DocumentWriteOutcome,
)
from .diagnostics import (
    OperationLog,
    build_diagnostic_bundle,
    default_crash_log_path,
    error_reason,
    file_size_bucket,
)
from .engine import (
    AnnotationInfo,
    CompressionResult,
    FormFieldInfo,
    FormFieldSpec,
    ImageDeletion,
    ImagePlacement,
    OutlineEntry,
    PdfEngine,
    PdfInvalidPasswordError,
    PdfPasswordRequiredError,
    SignaturePlacement,
    TextEdit,
    TextPlacement,
    TextRun,
)
from .text_layer import InlineTextEditor, TextObjectGraphicsItem, clean_pdf_font_name
from .recovery import (
    RecoverySnapshot,
    quarantine_recovery_file,
    read_recovery_snapshot,
    remove_recovery_file,
    validate_recovery_assets,
    validate_recovery_pages,
)
from .i18n import (
    LANGUAGES,
    LANGUAGE_CODES,
    RIGHT_TO_LEFT,
    language_from_locale,
    language_icon,
    translate,
)
from .inspection_worker import (
    DocumentInspectionReport,
)
from .inspection_coordinator import (
    InspectionContext,
    InspectionCoordinator,
    InspectionOutcome,
)
from .ocr_worker import available_ocr_languages
from .ocr_coordinator import OcrContext, OcrCoordinator, OcrOutcome
from .tile_worker import RenderedTile
from .tile_render_coordinator import TileRenderCoordinator, TileRenderOutcome
from .workers import RecoveryTask, SearchTask
from .version_check import ReleaseInfo, VersionCheckTask, is_newer


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
ZOOM_LEVELS = (25, 33, 50, 67, 75, 100, 125, 150, 200, 300, 400)
PREVIEW_RENDER_PIXELS = 2_500_000
RENDER_TILE_SIZE = 768
RENDER_TILE_CACHE_BYTES = 96 * 1024 * 1024
FONT_SIZE_PRESETS = (
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    14,
    16,
    18,
    20,
    22,
    24,
    26,
    28,
    32,
    36,
    48,
    72,
    96,
    120,
    144,
    200,
)
FORM_VISUAL_SIGNATURE_VALUE = object()
MAX_RECENT_FILES = 10
RECOVERY_DELAY_MS = 1600


def _rotated_outer_size(width: float, height: float, angle_degrees: float) -> tuple[float, float]:
    angle = math.radians(angle_degrees)
    cosine = abs(math.cos(angle))
    sine = abs(math.sin(angle))
    return width * cosine + height * sine, width * sine + height * cosine


def _normalized_angle(angle: float) -> float:
    normalized = (angle + 180.0) % 360.0 - 180.0
    return 0.0 if abs(normalized) < 0.01 else normalized


@dataclass
class EditorState:
    pdf_bytes: bytes
    edits: dict[str, TextEdit]
    inserted_texts: list[TextPlacement]
    signatures: list[SignaturePlacement]
    inserted_images: list[ImagePlacement]
    deleted_images: list[ImageDeletion]


@dataclass(frozen=True)
class TextObjectSpec:
    kind: str
    key: str
    page_index: int
    bbox: tuple[float, float, float, float]
    text: str
    font_family: str
    font_size: float
    bold: bool
    italic: bool
    underline: bool
    color: int


@dataclass(frozen=True)
class SearchMatch:
    page_index: int
    bbox: tuple[float, float, float, float]


class _OutlineTreeNode:
    def __init__(
        self,
        entry: OutlineEntry | None,
        parent: "_OutlineTreeNode | None",
        row: int,
    ) -> None:
        self.entry = entry
        self.parent = parent
        self.row = row
        self.children: list[_OutlineTreeNode] = []
        self.children_started = False
        self.next_child: OutlineEntry | None = None
        self.fully_fetched = entry is not None and not entry.has_children


class PdfOutlineModel(QAbstractItemModel):
    """Lazy outline model for EPLAN files with tens of thousands of entries."""

    def __init__(self, engine: PdfEngine, parent=None, batch_size: int = 128) -> None:
        super().__init__(parent)
        self.engine = engine
        self.batch_size = batch_size
        self.root = _OutlineTreeNode(None, None, 0)
        self.root.children_started = True
        self.root.next_child = engine.first_outline() if engine.is_open else None
        self.root.fully_fetched = self.root.next_child is None
        self._append_without_signals(self.root, 32)

    @property
    def has_entries(self) -> bool:
        return bool(self.root.children)

    def _node(self, index: QModelIndex) -> _OutlineTreeNode:
        return index.internalPointer() if index.isValid() else self.root

    def _start_children(self, node: _OutlineTreeNode) -> None:
        if node.children_started:
            return
        node.children_started = True
        node.next_child = self.engine.child_outline(node.entry) if node.entry else None
        node.fully_fetched = node.next_child is None

    def _collect_children(
        self,
        node: _OutlineTreeNode,
        limit: int,
    ) -> tuple[list[_OutlineTreeNode], OutlineEntry | None]:
        self._start_children(node)
        cursor = node.next_child
        start_row = len(node.children)
        children: list[_OutlineTreeNode] = []
        while cursor is not None and len(children) < limit:
            children.append(_OutlineTreeNode(cursor, node, start_row + len(children)))
            cursor = self.engine.next_outline(cursor)
        return children, cursor

    def _append_without_signals(self, node: _OutlineTreeNode, limit: int) -> None:
        children, cursor = self._collect_children(node, limit)
        node.children.extend(children)
        node.next_child = cursor
        node.fully_fetched = cursor is None

    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        if column != 0 or row < 0:
            return QModelIndex()
        parent_node = self._node(parent)
        if row >= len(parent_node.children):
            return QModelIndex()
        return self.createIndex(row, column, parent_node.children[row])

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node = self._node(index)
        parent_node = node.parent
        if parent_node is None or parent_node is self.root:
            return QModelIndex()
        return self.createIndex(parent_node.row, 0, parent_node)

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid() and parent.column() != 0:
            return 0
        return len(self._node(parent).children)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 1

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        entry = self._node(index).entry
        if entry is None:
            return None
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return entry.title
        if role == Qt.UserRole:
            return entry.page_index
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def hasChildren(self, parent=QModelIndex()) -> bool:
        node = self._node(parent)
        if node.children:
            return True
        if node is self.root:
            return node.next_child is not None
        return bool(node.entry and node.entry.has_children)

    def canFetchMore(self, parent: QModelIndex) -> bool:
        node = self._node(parent)
        if not node.children_started:
            return bool(node.entry and node.entry.has_children)
        return not node.fully_fetched

    def fetchMore(self, parent: QModelIndex) -> None:
        node = self._node(parent)
        children, cursor = self._collect_children(node, self.batch_size)
        if not children:
            node.fully_fetched = True
            return
        first = len(node.children)
        self.beginInsertRows(parent, first, first + len(children) - 1)
        node.children.extend(children)
        node.next_child = cursor
        node.fully_fetched = cursor is None
        self.endInsertRows()

    def entry_for_index(self, index: QModelIndex) -> OutlineEntry | None:
        return self._node(index).entry if index.isValid() else None


class PageThumbnailList(QListWidget):
    """Pages sidebar with explicit keyboard and context-menu signals."""

    delete_requested = Signal()
    context_menu_requested = Signal(int, object)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Delete and event.modifiers() == Qt.NoModifier:
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        row = self.row(item) if item is not None else -1
        if row < 0:
            event.ignore()
            return
        self.setCurrentRow(row)
        self.context_menu_requested.emit(row, self.mapToGlobal(event.pos()))
        event.accept()


class TextRunItem(QGraphicsRectItem):
    def __init__(self, run: TextRun, scale: float, host: "PageView") -> None:
        x0, y0, x1, y1 = run.bbox
        super().__init__(x0 * scale, y0 * scale, (x1 - x0) * scale, (y1 - y0) * scale)
        self.run = run
        self.host = host
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.IBeamCursor)
        self.setPen(QPen(Qt.transparent, 0))
        self.setBrush(Qt.NoBrush)
        self.setZValue(10)

    def hoverEnterEvent(self, event) -> None:
        if not self.host.special_mode:
            self.setPen(QPen(QColor(0, 120, 215, 210), 1.4))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.setPen(QPen(Qt.transparent, 0))
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self.host.special_mode:
            self.host.edit_requested.emit(self.run.key)
            event.accept()
            return
        event.ignore()


class VisualImageItem(QGraphicsRectItem):
    """Selection and transformation controls for an untouched PDF image.

    The source pixels remain in the MuPDF-rendered page beneath this item.
    Selecting the frame therefore does not rewrite, rotate, or resample the
    document. The image is promoted to an editable placement only when a real
    geometry change is committed.
    """

    def __init__(
        self,
        run: ImageRun,
        scale: float,
        host: "PageView",
        z_value: float,
    ) -> None:
        x0, y0, x1, y1 = run.bbox
        outer_width = max(1.0, (x1 - x0) * scale)
        outer_height = max(1.0, (y1 - y0) * scale)
        intrinsic_width = max(1.0, float(run.width))
        intrinsic_height = max(1.0, float(run.height))
        rotated_width, rotated_height = _rotated_outer_size(
            intrinsic_width,
            intrinsic_height,
            run.rotation_degrees,
        )
        fitted_scale = min(
            outer_width / max(1.0, rotated_width),
            outer_height / max(1.0, rotated_height),
        )
        local_width = max(1.0, intrinsic_width * fitted_scale)
        local_height = max(1.0, intrinsic_height * fitted_scale)
        super().__init__(
            -local_width / 2,
            -local_height / 2,
            local_width,
            local_height,
        )
        self.run = run
        self.kind = "source"
        self.key = run.key
        self.host = host
        self.render_scale = scale
        self._handle_role: str | None = None
        self._drag_start_distance = 1.0
        self._drag_start_vector_angle = 0.0
        self._drag_start_scale = 1.0
        self._drag_start_rotation = 0.0
        self._transform_at_press: tuple[QPointF, float, float] | None = None
        self._hovered = False

        self.setPos((x0 + x1) * scale / 2, (y0 + y1) * scale / 2)
        self.setRotation(run.rotation_degrees)
        self.setZValue(z_value)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

        self.rotation_line = QGraphicsLineItem(self)
        line_pen = QPen()
        line_pen.setCosmetic(True)
        line_pen.setWidthF(1.8)
        self.rotation_line.setPen(line_pen)
        self.rotation_line.setZValue(4)
        self.resize_handle = SignatureControlHandle("resize", self)
        self.rotation_handle = SignatureControlHandle("rotate", self)
        self._update_control_positions()
        self.refresh_mode()

    def _update_control_positions(self) -> None:
        bounds = self.rect()
        self.resize_handle.setPos(bounds.bottomRight())
        local_gap = 28.0 / max(0.001, abs(self.scale()))
        top_center = QPointF(bounds.center().x(), bounds.top())
        rotation_point = QPointF(top_center.x(), top_center.y() - local_gap)
        self.rotation_line.setLine(
            top_center.x(), top_center.y(), rotation_point.x(), rotation_point.y()
        )
        self.rotation_handle.setPos(rotation_point)

    def _set_control_color(self, color: QColor, fill: QColor | None = None) -> None:
        pen = QPen(color, 1.8)
        pen.setCosmetic(True)
        self.setPen(pen)
        line_pen = QPen(color, 1.8)
        line_pen.setCosmetic(True)
        self.rotation_line.setPen(line_pen)
        handle_fill = fill or color
        for handle in (self.resize_handle, self.rotation_handle):
            handle_pen = QPen(color.darker(145), 1.2)
            handle_pen.setCosmetic(True)
            handle.setPen(handle_pen)
            handle.setBrush(handle_fill)

    def _set_controls_visible(self, visible: bool) -> None:
        if visible:
            self._set_control_color(self.host.signature_accent)
        else:
            self.setPen(QPen(Qt.transparent, 0))
        selected = visible and self.isSelected() and not self.host.special_mode
        self.rotation_line.setVisible(selected)
        self.resize_handle.setVisible(selected)
        self.rotation_handle.setVisible(selected)

    def refresh_mode(self) -> None:
        if self.host.delete_image_mode:
            self.setFlag(QGraphicsItem.ItemIsSelectable, False)
            self.setFlag(QGraphicsItem.ItemIsMovable, False)
            self.setPen(QPen(QColor("#ff5252"), 2.1, Qt.DashLine))
            self.setBrush(QColor(255, 60, 60, 28))
            self.setCursor(Qt.PointingHandCursor)
            self.rotation_line.hide()
            self.resize_handle.hide()
            self.rotation_handle.hide()
            return
        if self.host.placement_mode or self.host.text_box_mode:
            self.setFlag(QGraphicsItem.ItemIsSelectable, False)
            self.setFlag(QGraphicsItem.ItemIsMovable, False)
            self.unsetCursor()
            self.setBrush(Qt.NoBrush)
            self._set_controls_visible(False)
            return
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setCursor(Qt.OpenHandCursor)
        if self.host.source_image_edit_mode and not self.isSelected():
            self.setPen(QPen(QColor("#ffb300"), 2.1, Qt.DashLine))
            self.setBrush(QColor(255, 179, 0, 28))
            self.rotation_line.hide()
            self.resize_handle.hide()
            self.rotation_handle.hide()
        else:
            self.setBrush(Qt.NoBrush)
            self._set_controls_visible(self.isSelected() or self._hovered)

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        if self.host.source_image_edit_mode:
            self.setPen(QPen(QColor("#ff8f00"), 3.0))
            self.setBrush(QColor(255, 179, 0, 55))
        elif self.host.delete_image_mode:
            self.setPen(QPen(QColor("#ff1744"), 3.0))
            self.setBrush(QColor(255, 23, 68, 55))
        elif not self.host.special_mode:
            self._set_controls_visible(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.refresh_mode()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self.host.delete_image_mode and event.button() == Qt.LeftButton:
            self.host.delete_image_requested.emit(self.kind, self.key)
            event.accept()
            return
        if self.host.placement_mode or self.host.text_box_mode:
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            self._transform_at_press = (QPointF(self.pos()), self.scale(), self.rotation())
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)
        if self.host.source_image_edit_mode and event.button() == Qt.LeftButton:
            self.host.source_image_edit_requested.emit(self.key)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self.setCursor(Qt.OpenHandCursor)
        self._commit_if_changed()

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._set_controls_visible(bool(value))
        return result

    def begin_handle_drag(self, role: str, scene_position: QPointF) -> None:
        self.setSelected(True)
        self._handle_role = role
        self._transform_at_press = (QPointF(self.pos()), self.scale(), self.rotation())
        center = self.pos()
        delta_x = scene_position.x() - center.x()
        delta_y = scene_position.y() - center.y()
        self._drag_start_distance = max(1.0, math.hypot(delta_x, delta_y))
        self._drag_start_vector_angle = math.degrees(math.atan2(delta_y, delta_x))
        self._drag_start_scale = self.scale()
        self._drag_start_rotation = self.rotation()

    def update_handle_drag(self, scene_position: QPointF) -> None:
        if self._handle_role is None:
            return
        center = self.pos()
        delta_x = scene_position.x() - center.x()
        delta_y = scene_position.y() - center.y()
        if self._handle_role == "resize":
            distance = max(1.0, math.hypot(delta_x, delta_y))
            requested = self._drag_start_scale * distance / self._drag_start_distance
            min_scale = 30.0 * self.render_scale / max(1.0, self.rect().width())
            self.setScale(max(min_scale, requested))
            self._update_control_positions()
        else:
            current_vector_angle = math.degrees(math.atan2(delta_y, delta_x))
            self.setRotation(
                _normalized_angle(
                    self._drag_start_rotation
                    + current_vector_angle
                    - self._drag_start_vector_angle
                )
            )

    def finish_handle_drag(self) -> None:
        self._handle_role = None
        self._commit_if_changed()

    def _commit_if_changed(self) -> None:
        if self._transform_at_press is None:
            return
        old_position, old_scale, old_rotation = self._transform_at_press
        self._transform_at_press = None
        changed = (
            abs(self.pos().x() - old_position.x()) > 0.05
            or abs(self.pos().y() - old_position.y()) > 0.05
            or abs(self.scale() - old_scale) > 0.0001
            or abs(_normalized_angle(self.rotation() - old_rotation)) > 0.05
        )
        if not changed:
            return
        mapped = self.mapRectToScene(self.rect())
        rect = mapped.boundingRect() if hasattr(mapped, "boundingRect") else mapped
        bbox = (
            rect.left() / self.render_scale,
            rect.top() / self.render_scale,
            rect.right() / self.render_scale,
            rect.bottom() / self.render_scale,
        )
        self.host.visual_transform_requested.emit(
            self.kind,
            self.key,
            bbox,
            _normalized_angle(self.rotation()),
        )


class SignatureControlHandle(QGraphicsEllipseItem):
    def __init__(self, role: str, signature_item: "SignatureGraphicsItem") -> None:
        super().__init__(-6, -6, 12, 12, signature_item)
        self.role = role
        self.signature_item = signature_item
        self.setZValue(6)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setCursor(Qt.SizeFDiagCursor if role == "resize" else Qt.CrossCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.signature_item.begin_handle_drag(self.role, event.scenePos())
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self.signature_item.update_handle_drag(event.scenePos())
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.signature_item.finish_handle_drag()
            event.accept()
            return
        event.ignore()


class SignatureGraphicsItem(QGraphicsPixmapItem):
    def __init__(
        self,
        visual: SignaturePlacement | ImagePlacement,
        kind: str,
        render_scale: float,
        host: "PageView",
        z_value: float,
    ) -> None:
        payload = visual.png_bytes if isinstance(visual, SignaturePlacement) else visual.image_bytes
        image = QImage.fromData(payload)
        if image.isNull():
            image = QImage(2, 2, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
        pixmap = QPixmap.fromImage(image)
        super().__init__(pixmap)
        self.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)
        self.visual = visual
        self.kind = kind
        self.key = visual.key
        self.host = host
        self.render_scale = render_scale
        self._handle_role: str | None = None
        self._drag_start_distance = 1.0
        self._drag_start_vector_angle = 0.0
        self._drag_start_scale = 1.0
        self._drag_start_rotation = 0.0
        self._transform_at_press: tuple[QPointF, float, float] | None = None
        self._hovered = False

        self.setTransformationMode(Qt.SmoothTransformation)
        self.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
        x0, y0, x1, y1 = visual.bbox
        center = QPointF((x0 + x1) * render_scale / 2, (y0 + y1) * render_scale / 2)
        rotated_width, rotated_height = _rotated_outer_size(
            pixmap.width(), pixmap.height(), visual.rotation_degrees
        )
        scale_x = (x1 - x0) * render_scale / max(1.0, rotated_width)
        scale_y = (y1 - y0) * render_scale / max(1.0, rotated_height)
        self.setScale(max(0.0001, min(scale_x, scale_y)))
        self.setRotation(visual.rotation_degrees)
        self.setPos(center)
        self.setZValue(z_value)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

        border_pen = QPen()
        border_pen.setCosmetic(True)
        border_pen.setWidthF(1.8)
        self.border = QGraphicsRectItem(self.boundingRect(), self)
        self.border.setPen(border_pen)
        self.border.setBrush(Qt.NoBrush)
        self.border.setZValue(4)

        self.rotation_line = QGraphicsLineItem(self)
        line_pen = QPen()
        line_pen.setCosmetic(True)
        line_pen.setWidthF(1.8)
        self.rotation_line.setPen(line_pen)
        self.rotation_line.setZValue(4)
        self.resize_handle = SignatureControlHandle("resize", self)
        self.rotation_handle = SignatureControlHandle("rotate", self)
        self._update_control_positions()
        self.refresh_mode()

    def paint(self, painter, option, widget=None) -> None:
        # MuPDF renders the image into the page layer. This graphics item is a
        # transparent interaction proxy whose child controls remain visible.
        # Drawing the same bitmap through Qt a second time made selected images
        # look softer and could expose a different rotation interpretation.
        return

    def _update_control_positions(self) -> None:
        bounds = self.boundingRect()
        self.resize_handle.setPos(bounds.bottomRight())
        local_gap = 28.0 / max(0.001, abs(self.scale()))
        top_center = QPointF(bounds.center().x(), bounds.top())
        rotation_point = QPointF(top_center.x(), top_center.y() - local_gap)
        self.rotation_line.setLine(top_center.x(), top_center.y(), rotation_point.x(), rotation_point.y())
        self.rotation_handle.setPos(rotation_point)

    def _set_control_color(self, color: QColor, fill: QColor | None = None) -> None:
        border_pen = self.border.pen()
        border_pen.setColor(color)
        border_pen.setWidthF(1.8)
        border_pen.setStyle(Qt.SolidLine)
        border_pen.setCosmetic(True)
        self.border.setPen(border_pen)
        line_pen = self.rotation_line.pen()
        line_pen.setColor(color)
        line_pen.setWidthF(1.8)
        line_pen.setStyle(Qt.SolidLine)
        line_pen.setCosmetic(True)
        self.rotation_line.setPen(line_pen)
        handle_fill = fill or color
        for handle in (self.resize_handle, self.rotation_handle):
            pen = QPen(color.darker(145), 1.2)
            pen.setCosmetic(True)
            handle.setPen(pen)
            handle.setBrush(handle_fill)

    def refresh_mode(self) -> None:
        if self.host.delete_image_mode:
            self.setFlag(QGraphicsItem.ItemIsSelectable, False)
            self.setFlag(QGraphicsItem.ItemIsMovable, False)
            self.setCursor(Qt.PointingHandCursor)
            self._set_control_color(QColor("#e12222"), QColor("#ff6b6b"))
            self.border.setPen(QPen(QColor("#e12222"), 2.2, Qt.DashLine))
            self.border.show()
            self.rotation_line.hide()
            self.resize_handle.hide()
            self.rotation_handle.hide()
            return
        if self.host.placement_mode or self.host.source_image_edit_mode:
            self.setFlag(QGraphicsItem.ItemIsSelectable, False)
            self.setFlag(QGraphicsItem.ItemIsMovable, False)
            self.unsetCursor()
            self._set_controls_visible(False)
            return
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setCursor(Qt.OpenHandCursor)
        self._set_control_color(self.host.signature_accent)
        self._set_controls_visible(self.isSelected() or self._hovered)

    def _set_controls_visible(self, visible: bool) -> None:
        self.border.setVisible(visible)
        selected = visible and self.isSelected() and not self.host.special_mode
        self.rotation_line.setVisible(selected)
        self.resize_handle.setVisible(selected)
        self.rotation_handle.setVisible(selected)

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        if not self.host.special_mode:
            self._set_controls_visible(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        if not self.host.special_mode:
            self._set_controls_visible(self.isSelected())
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self.host.delete_image_mode and event.button() == Qt.LeftButton:
            self.host.delete_image_requested.emit(self.kind, self.key)
            event.accept()
            return
        if self.host.placement_mode or self.host.source_image_edit_mode:
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            self._transform_at_press = (QPointF(self.pos()), self.scale(), self.rotation())
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self.setCursor(Qt.OpenHandCursor)
        self._commit_if_changed()

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._set_controls_visible(bool(value))
        return result

    def begin_handle_drag(self, role: str, scene_position: QPointF) -> None:
        self.setSelected(True)
        self._handle_role = role
        self._transform_at_press = (QPointF(self.pos()), self.scale(), self.rotation())
        center = self.pos()
        delta_x = scene_position.x() - center.x()
        delta_y = scene_position.y() - center.y()
        self._drag_start_distance = max(1.0, math.hypot(delta_x, delta_y))
        self._drag_start_vector_angle = math.degrees(math.atan2(delta_y, delta_x))
        self._drag_start_scale = self.scale()
        self._drag_start_rotation = self.rotation()

    def update_handle_drag(self, scene_position: QPointF) -> None:
        if self._handle_role is None:
            return
        center = self.pos()
        delta_x = scene_position.x() - center.x()
        delta_y = scene_position.y() - center.y()
        if self._handle_role == "resize":
            distance = max(1.0, math.hypot(delta_x, delta_y))
            requested = self._drag_start_scale * distance / self._drag_start_distance
            min_scale = 30.0 * self.render_scale / max(1, self.pixmap().width())
            self.setScale(max(min_scale, requested))
            self._update_control_positions()
        else:
            current_vector_angle = math.degrees(math.atan2(delta_y, delta_x))
            self.setRotation(_normalized_angle(
                self._drag_start_rotation + current_vector_angle - self._drag_start_vector_angle
            ))

    def finish_handle_drag(self) -> None:
        self._handle_role = None
        self._commit_if_changed()

    def _commit_if_changed(self) -> None:
        if self._transform_at_press is None:
            return
        old_position, old_scale, old_rotation = self._transform_at_press
        self._transform_at_press = None
        changed = (
            abs(self.pos().x() - old_position.x()) > 0.05
            or abs(self.pos().y() - old_position.y()) > 0.05
            or abs(self.scale() - old_scale) > 0.0001
            or abs(_normalized_angle(self.rotation() - old_rotation)) > 0.05
        )
        if not changed:
            return
        mapped = self.mapRectToScene(self.boundingRect())
        rect = mapped.boundingRect() if hasattr(mapped, "boundingRect") else mapped
        bbox = (
            rect.left() / self.render_scale,
            rect.top() / self.render_scale,
            rect.right() / self.render_scale,
            rect.bottom() / self.render_scale,
        )
        self.host.visual_transform_requested.emit(
            self.kind, self.key, bbox, _normalized_angle(self.rotation())
        )


class FormPlainTextEdit(QPlainTextEdit):
    editingFinished = Signal()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.editingFinished.emit()


class PageView(QGraphicsView):
    edit_requested = Signal(str)
    inline_edit_requested = Signal(str, str)
    inline_edit_finished = Signal(str, str, str)
    inline_edit_cancelled = Signal(str, str)
    inline_editor_closed = Signal()
    pointer_interaction_finished = Signal()
    page_refresh_requested = Signal()
    new_text_box_requested = Signal(object)
    redaction_area_requested = Signal(object, int)
    form_field_area_requested = Signal(object, int)
    form_value_edited = Signal(int, object)
    form_signature_requested = Signal(int)
    text_transform_requested = Signal(str, str, object)
    text_selection_changed = Signal(object)
    delete_text_requested = Signal(str, str)
    cancel_requested = Signal()
    placement_clicked = Signal(float, float)
    comment_placement_clicked = Signal(float, float)
    delete_image_requested = Signal(str, str)
    source_image_edit_requested = Signal(str)
    visual_transform_requested = Signal(str, str, object, float)
    object_context_menu_requested = Signal(str, str, str, object)
    signature_selection_changed = Signal(object)
    page_scroll_requested = Signal(int)
    visible_area_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._placement_mode = False
        self._comment_placement_mode = False
        self._delete_image_mode = False
        self._source_image_edit_mode = False
        self._text_box_mode = False
        self._redaction_mode = False
        self._form_field_mode = False
        self._form_field_compact = False
        self._form_field_signature = False
        self._text_drag_origin: QPointF | None = None
        self._text_drag_item: QGraphicsRectItem | None = None
        self._inline_proxy = None
        self._inline_editor: InlineTextEditor | None = None
        self._inline_ref: tuple[str, str] | None = None
        self.render_scale = 1.0
        self.selected_signature_key: str | None = None
        self.selected_visual_ref: tuple[str, str] | None = None
        self.selected_text_ref: tuple[str, str] | None = None
        self.signature_accent = QColor("#ffd166")
        self.text_accent = QColor("#6ec6ff")
        self._search_highlight_item: QGraphicsRectItem | None = None
        self._building_scene = False
        self._page_generation = 0
        self._pointer_interaction_active = False
        self._enable_hand_drag_pending = False
        self._explicit_text_clear = False
        self._page_wheel_delta = 0
        # QGraphicsScene owns the C++ items, but some PySide versions do not
        # reliably retain their Python wrappers.  A wrapper collected while a
        # mouse button is held can remove the corresponding item from the
        # scene.  Keep explicit references for the lifetime of each page.
        self._page_item: QGraphicsPixmapItem | None = None
        self._scene_item_refs: list[QGraphicsItem] = []
        self._tile_items: dict[object, QGraphicsPixmapItem] = {}
        self.setScene(QGraphicsScene(self))
        self.scene().selectionChanged.connect(self._selection_changed)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setBackgroundBrush(QColor("#30343a"))
        self.setAlignment(Qt.AlignCenter)
        self.horizontalScrollBar().valueChanged.connect(self.visible_area_changed)
        self.verticalScrollBar().valueChanged.connect(self.visible_area_changed)

    @property
    def delete_image_mode(self) -> bool:
        return self._delete_image_mode

    @property
    def source_image_edit_mode(self) -> bool:
        return self._source_image_edit_mode

    @property
    def placement_mode(self) -> bool:
        return self._placement_mode

    @property
    def comment_placement_mode(self) -> bool:
        return self._comment_placement_mode

    @property
    def text_box_mode(self) -> bool:
        return self._text_box_mode

    @property
    def redaction_mode(self) -> bool:
        return self._redaction_mode

    @property
    def form_field_mode(self) -> bool:
        return self._form_field_mode

    @property
    def inline_editing(self) -> bool:
        return self._inline_editor is not None

    @property
    def pointer_interaction_active(self) -> bool:
        return self._pointer_interaction_active

    @property
    def special_mode(self) -> bool:
        return (
            self._placement_mode
            or self._comment_placement_mode
            or self._delete_image_mode
            or self._source_image_edit_mode
            or self._text_box_mode
            or self._redaction_mode
            or self._form_field_mode
            or self.inline_editing
        )

    def set_page(
        self,
        pixmap: QPixmap,
        text_objects: list[tuple[str, str, tuple[float, float, float, float]]],
        visual_items: list[ImageRun],
        signatures: list[SignaturePlacement],
        scale: float,
        preview_scale: float | None = None,
        target_size: tuple[float, float] | None = None,
        inserted_images: list[ImagePlacement] | None = None,
        form_fields: list[FormFieldInfo] | None = None,
        form_mode: str = "none",
        form_values: dict[int, object] | None = None,
        sign_label: str = "Sign",
        signed_label: str = "Signed",
        visual_signature_added_label: str = "Visual signature added",
    ) -> None:
        if pixmap.isNull():
            raise ValueError("The rendered PDF page is empty.")
        selected_key = self.selected_signature_key
        selected_text_ref = self.selected_text_ref
        scroll_state = self._scroll_state()

        # Build the replacement scene completely before exposing it. Clearing
        # the live scene first used to leave a grey viewport whenever an item
        # constructor failed, and it is unsafe if a proxy text editor still
        # owns focus on Windows.
        new_scene = QGraphicsScene(self)
        new_scene.selectionChanged.connect(self._selection_changed)
        scene_item_refs: list[QGraphicsItem] = []
        try:
            page_item = QGraphicsPixmapItem(pixmap)
            page_item.setZValue(0)
            page_item.setAcceptedMouseButtons(Qt.NoButton)
            page_item.setTransformationMode(Qt.SmoothTransformation)
            if target_size is not None:
                target_width = max(1.0, float(target_size[0]))
                target_height = max(1.0, float(target_size[1]))
                page_item.setTransform(
                    QTransform.fromScale(
                        target_width / max(1, pixmap.width()),
                        target_height / max(1, pixmap.height()),
                    )
                )
                page_rect = QRectF(0.0, 0.0, target_width, target_height)
            else:
                effective_preview_scale = preview_scale or scale
                page_item.setScale(scale / max(0.0001, effective_preview_scale))
                page_rect = page_item.sceneBoundingRect()
            new_scene.addItem(page_item)
            scene_item_refs.append(page_item)
            selected_text_item = None
            selected_item = None
            for order, (kind, key, bbox) in enumerate(text_objects):
                z_value = 10 + order / 10000 if kind == "source" else 35 + order / 10000
                item = TextObjectGraphicsItem(kind, key, bbox, scale, self, z_value)
                new_scene.addItem(item)
                scene_item_refs.append(item)
                if (kind, key) == selected_text_ref:
                    selected_text_item = item
            for order, run in enumerate(visual_items):
                item = VisualImageItem(run, scale, self, 5 + order / 1000)
                new_scene.addItem(item)
                scene_item_refs.append(item)
                if run.key == selected_key:
                    selected_item = item
            for order, inserted_image in enumerate(inserted_images or []):
                item = SignatureGraphicsItem(
                    inserted_image, "inserted", scale, self, 25 + order / 1000
                )
                new_scene.addItem(item)
                scene_item_refs.append(item)
                if inserted_image.key == selected_key:
                    selected_item = item
            for order, signature in enumerate(signatures):
                item = SignatureGraphicsItem(
                    signature, "signature", scale, self, 30 + order / 1000
                )
                new_scene.addItem(item)
                scene_item_refs.append(item)
                if signature.key == selected_key:
                    selected_item = item
            if form_mode in {"preview", "fill"}:
                overrides = form_values or {}
                for order, field in enumerate(form_fields or ()):
                    value = overrides.get(
                        field.xref,
                        field.checked
                        if field.type_code in (
                            pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                            pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
                        )
                        else field.value,
                    )
                    if field.type_code == pymupdf.PDF_WIDGET_TYPE_TEXT:
                        if field.multiline:
                            control = FormPlainTextEdit()
                            control.setPlainText(str(value))
                            control.editingFinished.connect(
                                lambda field_xref=field.xref, editor=control:
                                self.form_value_edited.emit(
                                    field_xref, editor.toPlainText()
                                )
                            )
                        else:
                            control = QLineEdit(str(value))
                            control.editingFinished.connect(
                                lambda field_xref=field.xref, editor=control:
                                self.form_value_edited.emit(field_xref, editor.text())
                            )
                    elif field.type_code == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                        control = QCheckBox()
                        control.setChecked(bool(value))
                        control.toggled.connect(
                            lambda checked, field_xref=field.xref:
                            self.form_value_edited.emit(field_xref, checked)
                        )
                    elif field.type_code == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                        control = QRadioButton()
                        control.setChecked(bool(value))
                        control.toggled.connect(
                            lambda checked, field_xref=field.xref:
                            checked and self.form_value_edited.emit(field_xref, True)
                        )
                    elif field.type_code in (
                        pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                        pymupdf.PDF_WIDGET_TYPE_LISTBOX,
                    ):
                        control = QComboBox()
                        control.addItems(field.choices)
                        index = control.findText(str(value))
                        if index >= 0:
                            control.setCurrentIndex(index)
                        control.activated.connect(
                            lambda _index, field_xref=field.xref, editor=control:
                            self.form_value_edited.emit(
                                field_xref, editor.currentText()
                            )
                        )
                    elif field.type_code == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
                        visual_signature_added = value is FORM_VISUAL_SIGNATURE_VALUE
                        control = QPushButton(
                            visual_signature_added_label
                            if visual_signature_added
                            else signed_label if bool(value) else sign_label
                        )
                        control.clicked.connect(
                            lambda _checked=False, field_xref=field.xref:
                            self.form_signature_requested.emit(field_xref)
                        )
                    else:
                        continue
                    control.setEnabled(
                        not field.read_only
                        and not (
                            field.type_code == pymupdf.PDF_WIDGET_TYPE_SIGNATURE
                            and bool(value)
                        )
                    )
                    tooltip = field.label or field.name
                    if field.required:
                        tooltip = f"{tooltip} *" if tooltip else "*"
                    control.setToolTip(tooltip)
                    border = "#f59e0b" if field.required else "#2477c9"
                    background = (
                        "rgba(255, 250, 225, 235)"
                        if form_mode == "preview"
                        else "rgba(236, 248, 255, 240)"
                    )
                    control.setStyleSheet(
                        f"border: 2px solid {border}; background: {background}; "
                        "color: #101820; border-radius: 3px;"
                    )
                    x0, y0, x1, y1 = field.bbox
                    width = max(22, round((x1 - x0) * scale))
                    height = max(22, round((y1 - y0) * scale))
                    control.setFixedSize(width, height)
                    proxy = new_scene.addWidget(control)
                    proxy.setPos(x0 * scale, y0 * scale)
                    proxy.setZValue(90 + order / 1000)
                    scene_item_refs.append(proxy)
            new_scene.setSceneRect(page_rect)
        except BaseException:
            new_scene.deleteLater()
            raise

        old_scene = self.scene()
        self._building_scene = True
        try:
            self.setScene(new_scene)
            self._page_item = page_item
            self._scene_item_refs = scene_item_refs
            self._tile_items = {}
            self._inline_proxy = None
            self._inline_editor = None
            self._inline_ref = None
            self._search_highlight_item = None
            self._page_wheel_delta = 0
            self.render_scale = scale
            self._page_generation += 1
            generation = self._page_generation
            if old_scene is not None and old_scene is not new_scene:
                try:
                    old_scene.selectionChanged.disconnect(self._selection_changed)
                except (RuntimeError, TypeError):
                    pass
                old_scene.deleteLater()
        finally:
            self._building_scene = False
        if selected_text_item is not None:
            selected_text_item.setSelected(True)
        elif selected_text_ref is not None:
            self.selected_text_ref = None
        if selected_item is not None and selected_text_item is None:
            selected_item.setSelected(True)
        elif selected_key is not None:
            self.selected_signature_key = None
            self.selected_visual_ref = None
        self._restore_scroll_state(scroll_state)
        QTimer.singleShot(
            0,
            lambda current_generation=generation, state=scroll_state: self._finish_page_swap(
                current_generation,
                state,
            ),
        )

    def set_render_tile(
        self,
        key: object,
        pixmap: QPixmap,
        x: int,
        y: int,
    ) -> None:
        """Overlay one target-resolution tile above the scaled page preview."""

        if pixmap.isNull() or self._page_item is None:
            return
        previous = self._tile_items.pop(key, None)
        if previous is not None and previous.scene() is self.scene():
            self.scene().removeItem(previous)
        item = QGraphicsPixmapItem(pixmap)
        item.setPos(float(x), float(y))
        item.setZValue(1)
        item.setAcceptedMouseButtons(Qt.NoButton)
        self.scene().addItem(item)
        self._tile_items[key] = item

    def clear_render_tiles(self) -> None:
        for item in tuple(self._tile_items.values()):
            try:
                if item.scene() is self.scene():
                    self.scene().removeItem(item)
            except RuntimeError:
                pass
        self._tile_items.clear()

    def retain_render_tiles(self, keys: set[object]) -> None:
        for key in tuple(self._tile_items):
            if key in keys:
                continue
            item = self._tile_items.pop(key)
            try:
                if item.scene() is self.scene():
                    self.scene().removeItem(item)
            except RuntimeError:
                pass

    def visible_page_rect(self, margin: float = 0.0) -> QRectF:
        if self.sceneRect().isEmpty():
            return QRectF()
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        if margin > 0:
            visible = visible.adjusted(-margin, -margin, margin, margin)
        return visible.intersected(self.sceneRect())

    def _scroll_state(self) -> tuple[float | None, float | None]:
        def fraction(scroll_bar) -> float | None:
            span = scroll_bar.maximum() - scroll_bar.minimum()
            if span <= 0:
                return None
            return (scroll_bar.value() - scroll_bar.minimum()) / span

        return fraction(self.horizontalScrollBar()), fraction(self.verticalScrollBar())

    def _restore_scroll_state(self, state: tuple[float | None, float | None]) -> None:
        for scroll_bar, fraction in zip(
            (self.horizontalScrollBar(), self.verticalScrollBar()),
            state,
        ):
            if fraction is None:
                scroll_bar.setValue(scroll_bar.minimum())
                continue
            span = scroll_bar.maximum() - scroll_bar.minimum()
            scroll_bar.setValue(
                scroll_bar.minimum()
                + round(span * min(1.0, max(0.0, fraction)))
            )

    def _finish_page_swap(
        self,
        generation: int,
        scroll_state: tuple[float | None, float | None],
    ) -> None:
        if generation != self._page_generation or self.sceneRect().isEmpty():
            return
        self._restore_scroll_state(scroll_state)
        page_rect = self.sceneRect()
        visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        intersection = page_rect.intersected(visible_rect)
        expected_width = min(page_rect.width(), visible_rect.width())
        expected_height = min(page_rect.height(), visible_rect.height())
        if (
            intersection.width() < expected_width * 0.5
            or intersection.height() < expected_height * 0.5
        ):
            self.centerOn(page_rect.center())
        self.visible_area_changed.emit()

    def clear_page(self) -> None:
        self.finish_inline_editor(False)
        self._building_scene = True
        self._search_highlight_item = None
        self.scene().clear()
        self._page_item = None
        self._scene_item_refs = []
        self._tile_items = {}
        self.scene().setSceneRect(QRectF())
        self._building_scene = False
        self.selected_signature_key = None
        self.selected_visual_ref = None
        self.selected_text_ref = None

    def center_on_pdf_rect(self, bbox: tuple[float, float, float, float]) -> None:
        x0, y0, x1, y1 = bbox
        target = QRectF(
            x0 * self.render_scale,
            y0 * self.render_scale,
            max(1.0, (x1 - x0) * self.render_scale),
            max(1.0, (y1 - y0) * self.render_scale),
        ).intersected(self.sceneRect())
        if not target.isEmpty():
            self.centerOn(target.center())

    def set_search_highlight(
        self,
        bbox: tuple[float, float, float, float] | None,
    ) -> None:
        highlight = self._search_highlight_item
        self._search_highlight_item = None
        if highlight is not None:
            try:
                if highlight.scene() is not None:
                    self.scene().removeItem(highlight)
            except RuntimeError:
                pass
        if bbox is None:
            return
        x0, y0, x1, y1 = bbox
        rect = QRectF(
            x0 * self.render_scale,
            y0 * self.render_scale,
            max(1.0, (x1 - x0) * self.render_scale),
            max(1.0, (y1 - y0) * self.render_scale),
        )
        highlight = QGraphicsRectItem(rect)
        pen = QPen(QColor("#f57c00"), 2.4)
        pen.setCosmetic(True)
        highlight.setPen(pen)
        highlight.setBrush(QColor(255, 214, 0, 82))
        highlight.setZValue(80)
        highlight.setAcceptedMouseButtons(Qt.NoButton)
        self.scene().addItem(highlight)
        self._search_highlight_item = highlight
        self.ensureVisible(highlight, 32, 32)

    def _selection_changed(self) -> None:
        if self._building_scene:
            return
        selected = next(
            (
                item
                for item in self.scene().selectedItems()
                if isinstance(item, (SignatureGraphicsItem, VisualImageItem))
            ),
            None,
        )
        selected_text = next(
            (item for item in self.scene().selectedItems() if isinstance(item, TextObjectGraphicsItem)),
            None,
        )
        self.selected_signature_key = selected.key if selected and selected_text is None else None
        self.selected_visual_ref = (
            (selected.kind, selected.key)
            if selected is not None and selected_text is None
            else None
        )
        if selected_text is not None:
            self.selected_text_ref = (selected_text.kind, selected_text.key)
        elif self._explicit_text_clear or self.selected_text_ref is None:
            # A transient scene clear can occur while focus moves to a combo
            # popup.  Keep the editing target unless the user actually clicked
            # another object or the blank canvas.
            self.selected_text_ref = None
        self.signature_selection_changed.emit(self.selected_signature_key)
        if selected_text is not None or self._explicit_text_clear or self.selected_text_ref is None:
            self.text_selection_changed.emit(self.selected_text_ref)

    @staticmethod
    def _context_object(item: QGraphicsItem | None) -> QGraphicsItem | None:
        """Resolve a handle/border hit to its editable parent object."""

        while item is not None:
            if isinstance(item, (TextObjectGraphicsItem, SignatureGraphicsItem, VisualImageItem)):
                return item
            item = item.parentItem()
        return None

    def contextMenuEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        target = self._context_object(item)
        if target is None or self.special_mode or self.inline_editing:
            super().contextMenuEvent(event)
            return

        # A right click selects the object under the pointer before opening its
        # menu.  The explicit clear also drops a retained text-toolbar target
        # when the user changes from text to an image (or vice versa).
        self._explicit_text_clear = True
        self.scene().clearSelection()
        self._explicit_text_clear = False
        target.setSelected(True)
        category = "text" if isinstance(target, TextObjectGraphicsItem) else "visual"
        self.object_context_menu_requested.emit(
            category,
            str(target.kind),
            str(target.key),
            event.globalPos(),
        )
        event.accept()

    def set_theme(self, dark: bool) -> None:
        self.setBackgroundBrush(QColor("#30343a" if dark else "#cfd5dc"))
        self.signature_accent = QColor("#ffd166" if dark else "#0067b8")
        self.text_accent = QColor("#6ec6ff" if dark else "#0067b8")
        for item in self.scene().items():
            if isinstance(item, (SignatureGraphicsItem, VisualImageItem)):
                item.refresh_mode()
            elif isinstance(item, TextObjectGraphicsItem):
                item.refresh_visuals()

    def set_placement_mode(self, enabled: bool) -> None:
        self._placement_mode = enabled
        if enabled:
            self._comment_placement_mode = False
            self._delete_image_mode = False
            self._source_image_edit_mode = False
            self._text_box_mode = False
            self._redaction_mode = False
            self._form_field_mode = False
        self._refresh_interaction_mode()
        for item in self.scene().items():
            if isinstance(item, (SignatureGraphicsItem, VisualImageItem)):
                item.refresh_mode()
            elif isinstance(item, TextObjectGraphicsItem):
                item.refresh_visuals()

    def set_comment_placement_mode(self, enabled: bool) -> None:
        self._comment_placement_mode = enabled
        if enabled:
            self._placement_mode = False
            self._delete_image_mode = False
            self._source_image_edit_mode = False
            self._text_box_mode = False
            self._redaction_mode = False
            self._form_field_mode = False
            self.finish_inline_editor(False)
        self._refresh_interaction_mode()
        for item in self.scene().items():
            if isinstance(item, (SignatureGraphicsItem, VisualImageItem)):
                item.refresh_mode()
            elif isinstance(item, TextObjectGraphicsItem):
                item.refresh_visuals()

    def set_delete_image_mode(self, enabled: bool) -> None:
        self._delete_image_mode = enabled
        if enabled:
            self._placement_mode = False
            self._comment_placement_mode = False
            self._source_image_edit_mode = False
            self._text_box_mode = False
            self._redaction_mode = False
            self._form_field_mode = False
        self._refresh_interaction_mode()
        for item in self.scene().items():
            if isinstance(item, VisualImageItem):
                item.refresh_mode()
            elif isinstance(item, SignatureGraphicsItem):
                item.refresh_mode()
            elif isinstance(item, TextObjectGraphicsItem):
                item.refresh_visuals()

    def set_source_image_edit_mode(self, enabled: bool) -> None:
        self._source_image_edit_mode = enabled
        if enabled:
            self._placement_mode = False
            self._comment_placement_mode = False
            self._delete_image_mode = False
            self._text_box_mode = False
            self._redaction_mode = False
            self._form_field_mode = False
        self._refresh_interaction_mode()
        for item in self.scene().items():
            if isinstance(item, VisualImageItem):
                item.refresh_mode()
            elif isinstance(item, SignatureGraphicsItem):
                item.refresh_mode()
            elif isinstance(item, TextObjectGraphicsItem):
                item.refresh_visuals()

    def set_text_box_mode(self, enabled: bool) -> None:
        self._text_box_mode = enabled
        if enabled:
            self._placement_mode = False
            self._comment_placement_mode = False
            self._delete_image_mode = False
            self._source_image_edit_mode = False
            self._redaction_mode = False
            self._form_field_mode = False
            self.finish_inline_editor(False)
        if not enabled:
            self._clear_text_drag()
        self._refresh_interaction_mode()
        for item in self.scene().items():
            if isinstance(item, (SignatureGraphicsItem, VisualImageItem)):
                item.refresh_mode()
            elif isinstance(item, TextObjectGraphicsItem):
                item.refresh_visuals()

    def set_redaction_mode(self, enabled: bool) -> None:
        self._redaction_mode = enabled
        if enabled:
            self._placement_mode = False
            self._comment_placement_mode = False
            self._delete_image_mode = False
            self._source_image_edit_mode = False
            self._text_box_mode = False
            self._form_field_mode = False
            self.finish_inline_editor(False)
        if not enabled:
            self._clear_text_drag()
        self._refresh_interaction_mode()

    def set_form_field_mode(
        self,
        enabled: bool,
        *,
        compact: bool = False,
        signature: bool = False,
    ) -> None:
        self._form_field_mode = enabled
        self._form_field_compact = bool(compact) if enabled else False
        self._form_field_signature = bool(signature) if enabled else False
        if enabled:
            self._placement_mode = False
            self._comment_placement_mode = False
            self._delete_image_mode = False
            self._source_image_edit_mode = False
            self._text_box_mode = False
            self._redaction_mode = False
            self.finish_inline_editor(False)
        if not enabled:
            self._clear_text_drag()
        self._refresh_interaction_mode()

    def _refresh_interaction_mode(self) -> None:
        requested_drag_mode = (
            QGraphicsView.NoDrag if self.special_mode else QGraphicsView.ScrollHandDrag
        )
        if (
            requested_drag_mode == QGraphicsView.ScrollHandDrag
            and self._pointer_interaction_active
        ):
            # A click outside the inline editor moves focus back to this view.
            # Do not enable hand dragging between that mouse press and its
            # release: Qt can otherwise retain a half-started drag operation.
            self._enable_hand_drag_pending = True
        else:
            self._enable_hand_drag_pending = False
            self.setDragMode(requested_drag_mode)
        if (
            self._placement_mode
            or self._comment_placement_mode
            or self._text_box_mode
            or self._redaction_mode
            or self._form_field_mode
        ):
            cursor = Qt.CrossCursor
        elif self._delete_image_mode or self._source_image_edit_mode:
            cursor = Qt.PointingHandCursor
        else:
            cursor = Qt.ArrowCursor
        self.viewport().setCursor(cursor)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.NoButton:
            self._pointer_interaction_active = True
        if (
            self._text_box_mode or self._redaction_mode or self._form_field_mode
        ) and event.button() == Qt.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(point):
                self._text_drag_origin = point
                self._text_drag_item = QGraphicsRectItem(QRectF(point, point))
                if self._redaction_mode:
                    accent = QColor("#e53935")
                elif self._form_field_mode:
                    accent = QColor("#7b61ff")
                else:
                    accent = self.text_accent
                pen = QPen(accent, 1.8, Qt.DashLine)
                pen.setCosmetic(True)
                self._text_drag_item.setPen(pen)
                self._text_drag_item.setBrush(
                    QColor(accent.red(), accent.green(), accent.blue(), 45)
                )
                self._text_drag_item.setZValue(90)
                self.scene().addItem(self._text_drag_item)
                event.accept()
                return
        if self._placement_mode and event.button() == Qt.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(point):
                self.placement_clicked.emit(point.x(), point.y())
                event.accept()
                return
        if self._comment_placement_mode and event.button() == Qt.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if self.sceneRect().contains(point):
                self.comment_placement_clicked.emit(point.x(), point.y())
                event.accept()
                return
        explicit_clear = False
        if event.button() == Qt.LeftButton and not self.special_mode:
            item = self.itemAt(event.position().toPoint())
            while item is not None and not isinstance(item, TextObjectGraphicsItem):
                item = item.parentItem()
            explicit_clear = item is None
        self._explicit_text_clear = explicit_clear
        try:
            super().mousePressEvent(event)
            if explicit_clear:
                for selected_item in tuple(self.scene().selectedItems()):
                    if isinstance(selected_item, TextObjectGraphicsItem):
                        selected_item.setSelected(False)
                if self.selected_text_ref is not None:
                    # ScrollHandDrag does not always clear a scene selection
                    # when the page background is clicked, so clear the text
                    # target explicitly without disturbing a signature that
                    # may have been selected by the same click.
                    self.selected_text_ref = None
                    self.text_selection_changed.emit(None)
        finally:
            self._explicit_text_clear = False

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() != Qt.NoButton:
            self._pointer_interaction_active = True
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            (self._text_box_mode or self._redaction_mode or self._form_field_mode)
            and self._text_drag_origin is not None
            and self._text_drag_item is not None
        ):
            point = self.mapToScene(event.position().toPoint())
            rect = QRectF(self._text_drag_origin, point).normalized().intersected(self.sceneRect())
            self._text_drag_item.setRect(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        try:
            if (
                (self._text_box_mode or self._redaction_mode or self._form_field_mode)
                and self._text_drag_origin is not None
                and event.button() == Qt.LeftButton
            ):
                end = self.mapToScene(event.position().toPoint())
                rect = QRectF(self._text_drag_origin, end).normalized().intersected(
                    self.sceneRect()
                )
                redaction = self._redaction_mode
                form_field = self._form_field_mode
                if not redaction and (rect.width() < 16 or rect.height() < 12):
                    if form_field and self._form_field_compact:
                        default_width, default_height = 24.0, 24.0
                    elif form_field and self._form_field_signature:
                        default_width, default_height = 180.0, 52.0
                    elif form_field:
                        default_width, default_height = 180.0, 28.0
                    else:
                        default_width, default_height = 220.0, 60.0
                    width = min(default_width * self.render_scale, self.sceneRect().width())
                    height = min(default_height * self.render_scale, self.sceneRect().height())
                    left = min(
                        max(self.sceneRect().left(), self._text_drag_origin.x()),
                        self.sceneRect().right() - width,
                    )
                    top = min(
                        max(self.sceneRect().top(), self._text_drag_origin.y()),
                        self.sceneRect().bottom() - height,
                    )
                    rect = QRectF(left, top, width, height)
                bbox = (
                    rect.left() / self.render_scale,
                    rect.top() / self.render_scale,
                    rect.right() / self.render_scale,
                    rect.bottom() / self.render_scale,
                )
                self._text_box_mode = False
                self._redaction_mode = False
                self._form_field_mode = False
                self._form_field_compact = False
                self._form_field_signature = False
                self._clear_text_drag()
                self._refresh_interaction_mode()
                if redaction:
                    if rect.width() / self.render_scale >= 1.0 and rect.height() / self.render_scale >= 1.0:
                        self.redaction_area_requested.emit(bbox, self._page_generation)
                elif form_field:
                    self.form_field_area_requested.emit(bbox, self._page_generation)
                else:
                    self.new_text_box_requested.emit(bbox)
                event.accept()
                return
            super().mouseReleaseEvent(event)
        finally:
            if event.buttons() == Qt.NoButton:
                self._pointer_interaction_active = False
                if self._enable_hand_drag_pending:
                    self._refresh_interaction_mode()
                self.pointer_interaction_finished.emit()
                QTimer.singleShot(0, self._verify_page_after_interaction)

    def _verify_page_after_interaction(self) -> None:
        if self.sceneRect().isEmpty():
            return
        page_item = self._page_item
        try:
            page_invalid = (
                page_item is None
                or page_item.scene() is not self.scene()
                or page_item.pixmap().isNull()
            )
        except RuntimeError:
            page_invalid = True
        if page_invalid:
            self.page_refresh_requested.emit()
            return

        # This check is a safety net for the historical disappearing-page
        # fault.  A normal click must not invalidate the complete page: doing
        # so produces a visible white/grey flash, especially on large pages.
        # Repaint only when the base layer or the scene bounds actually need
        # repairing.
        repair_needed = False
        if not page_item.isVisible():
            page_item.setVisible(True)
            repair_needed = True
        page_rect = page_item.sceneBoundingRect()
        if self.sceneRect() != page_rect:
            self.scene().setSceneRect(page_rect)
            repair_needed = True
        if repair_needed:
            self.scene().update(page_rect)
            self.viewport().update()

    def _clear_text_drag(self) -> None:
        if self._text_drag_item is not None and self._text_drag_item.scene() is not None:
            self.scene().removeItem(self._text_drag_item)
        self._text_drag_item = None
        self._text_drag_origin = None

    def start_inline_editor(
        self,
        kind: str,
        key: str,
        bbox: tuple[float, float, float, float],
        text: str,
        family: str,
        font_size: float,
        bold: bool,
        italic: bool,
        underline: bool,
        color: int,
        dark: bool,
    ) -> None:
        self.finish_inline_editor(False)
        self._placement_mode = False
        self._delete_image_mode = False
        self._source_image_edit_mode = False
        self._text_box_mode = False
        editor = InlineTextEditor(
            text,
            family,
            font_size * self.render_scale,
            bold,
            italic,
            underline,
            QColor((color >> 16) & 255, (color >> 8) & 255, color & 255),
            dark,
        )
        x0, y0, x1, y1 = bbox
        width = max(130.0, (x1 - x0) * self.render_scale + 12.0)
        height = max(54.0, (y1 - y0) * self.render_scale + 16.0, font_size * self.render_scale * 2.1)
        editor.resize(round(width), round(height))
        proxy = self.scene().addWidget(editor)
        proxy.setPos(x0 * self.render_scale, y0 * self.render_scale)
        proxy.setZValue(100)
        self._inline_editor = editor
        self._inline_proxy = proxy
        self._inline_ref = (kind, key)
        self.selected_text_ref = (kind, key)
        editor.accepted.connect(lambda value, k=kind, item_key=key: self._inline_accepted(k, item_key, value))
        editor.rejected.connect(lambda k=kind, item_key=key: self._inline_rejected(k, item_key))
        self._refresh_interaction_mode()
        editor.setFocus(Qt.MouseFocusReason)

    def finish_inline_editor(self, accept: bool) -> None:
        if self._inline_editor is not None:
            self._inline_editor.finish(accept)

    def _remove_inline_editor(self) -> None:
        proxy = self._inline_proxy
        editor = self._inline_editor
        self._inline_proxy = None
        self._inline_editor = None
        self._inline_ref = None
        if proxy is not None:
            owner_scene = proxy.scene()
            if owner_scene is not None:
                owner_scene.removeItem(proxy)
            proxy.deleteLater()
        elif editor is not None:
            editor.deleteLater()
        self._refresh_interaction_mode()

    def _inline_accepted(self, kind: str, key: str, text: str) -> None:
        self._remove_inline_editor()
        self.inline_edit_finished.emit(kind, key, text)
        self.inline_editor_closed.emit()

    def _inline_rejected(self, kind: str, key: str) -> None:
        self._remove_inline_editor()
        self.inline_edit_cancelled.emit(kind, key)
        self.inline_editor_closed.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Delete and self.selected_text_ref is not None and not self.special_mode:
            self.delete_text_requested.emit(*self.selected_text_ref)
            event.accept()
            return
        if (
            event.key() == Qt.Key_Delete
            and self.selected_visual_ref is not None
            and not self.special_mode
        ):
            self.delete_image_requested.emit(*self.selected_visual_ref)
            event.accept()
            return
        if event.key() == Qt.Key_Escape and (
            self._text_box_mode
            or self._placement_mode
            or self._delete_image_mode
            or self._source_image_edit_mode
        ):
            self.cancel_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        """Scroll the page, then continue through the document at its edges."""
        if event.modifiers() & Qt.ShiftModifier:
            self._page_wheel_delta = 0
            super().wheelEvent(event)
            return

        angle_delta = event.angleDelta().y()
        delta = angle_delta or event.pixelDelta().y()
        if not delta:
            self._page_wheel_delta = 0
            super().wheelEvent(event)
            return
        threshold = 120 if angle_delta else 40

        scroll_bar = self.verticalScrollBar()
        at_top = scroll_bar.value() <= scroll_bar.minimum()
        at_bottom = scroll_bar.value() >= scroll_bar.maximum()
        requests_previous = delta > 0 and at_top
        requests_next = delta < 0 and at_bottom
        if not (requests_previous or requests_next):
            self._page_wheel_delta = 0
            super().wheelEvent(event)
            return

        if self._page_wheel_delta and (self._page_wheel_delta > 0) != (delta > 0):
            self._page_wheel_delta = 0
        self._page_wheel_delta += delta
        if abs(self._page_wheel_delta) >= threshold:
            direction = -1 if self._page_wheel_delta > 0 else 1
            self._page_wheel_delta = 0
            self.page_scroll_requested.emit(direction)
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.visible_area_changed.emit()


class CollapsibleToolSidebar(QWidget):
    """Acrobat-style right tool rail with a panel that opens to the left."""

    currentChanged = Signal(int)
    collapsed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("rightToolSidebar")
        self._buttons: list[QToolButton] = []
        self._titles: list[str] = []
        self._current_index = -1
        self._expanded = False

        self._title = QLabel()
        self._title.setObjectName("rightToolTitle")
        title_font = self._title.font()
        title_font.setBold(True)
        self._title.setFont(title_font)
        close_button = QToolButton()
        close_button.setObjectName("rightToolClose")
        close_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight))
        close_button.clicked.connect(self.collapse)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(10, 6, 6, 4)
        title_row.addWidget(self._title, 1)
        title_row.addWidget(close_button)
        self._stack = QStackedWidget()
        self._panel = QWidget()
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        panel_layout.addLayout(title_row)
        panel_layout.addWidget(self._stack, 1)

        self._rail = QWidget()
        self._rail.setObjectName("rightToolRail")
        self._rail.setFixedWidth(48)
        self._rail_layout = QVBoxLayout(self._rail)
        self._rail_layout.setContentsMargins(3, 4, 3, 4)
        self._rail_layout.setSpacing(3)
        self._rail_layout.addStretch(1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._panel, 1)
        layout.addWidget(self._rail)
        self.collapse()

    def addTab(self, widget: QWidget, icon: QIcon, title: str) -> int:
        index = self._stack.addWidget(widget)
        button = QToolButton(self._rail)
        button.setObjectName("rightToolButton")
        button.setCheckable(True)
        button.setAutoExclusive(False)
        button.setIcon(icon)
        button.setIconSize(QPixmap(24, 24).size())
        button.setFixedSize(42, 42)
        button.setToolTip(title)
        button.clicked.connect(lambda _checked=False, tab=index: self._activate(tab))
        self._rail_layout.insertWidget(self._rail_layout.count() - 1, button)
        self._buttons.append(button)
        self._titles.append(title)
        if self._current_index < 0:
            self._current_index = index
            self._stack.setCurrentIndex(index)
            self._title.setText(title)
        return index

    def _activate(self, index: int) -> None:
        if not 0 <= index < len(self._buttons) or not self._buttons[index].isEnabled():
            return
        if self._expanded and self._current_index == index:
            self.collapse()
            return
        self.setCurrentIndex(index)

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._buttons) or not self._buttons[index].isEnabled():
            return
        self._current_index = index
        self._stack.setCurrentIndex(index)
        self._title.setText(self._titles[index])
        self._expanded = True
        self._panel.show()
        self.setMinimumWidth(250)
        self.setMaximumWidth(420)
        for item, button in enumerate(self._buttons):
            button.setChecked(item == index)
        self.currentChanged.emit(index)

    def currentIndex(self) -> int:
        return self._current_index

    def isExpanded(self) -> bool:
        return self._expanded

    def collapse(self) -> None:
        self._expanded = False
        self._panel.hide()
        self.setFixedWidth(48)
        for button in self._buttons:
            button.setChecked(False)
        self.collapsed.emit()

    def setTabEnabled(self, index: int, enabled: bool) -> None:
        if not 0 <= index < len(self._buttons):
            return
        self._buttons[index].setEnabled(enabled)
        self._stack.widget(index).setEnabled(enabled)
        if not enabled and self._expanded and self._current_index == index:
            replacement = next(
                (item for item, button in enumerate(self._buttons) if button.isEnabled()),
                None,
            )
            if replacement is None:
                self.collapse()
            else:
                self.setCurrentIndex(replacement)

    def isTabEnabled(self, index: int) -> bool:
        return 0 <= index < len(self._buttons) and self._buttons[index].isEnabled()

    def setTabText(self, index: int, title: str) -> None:
        if not 0 <= index < len(self._buttons):
            return
        self._titles[index] = title
        self._buttons[index].setToolTip(title)
        if self._current_index == index:
            self._title.setText(title)

    def setTabToolTip(self, index: int, text: str) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setToolTip(text or self._titles[index])


class MainWindow(QMainWindow):
    def __init__(
        self,
        recovery_path: str | Path | None = None,
        settings: QSettings | None = None,
        operation_log_path: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.settings = (
            settings
            if settings is not None
            else QSettings(LEGACY_APP_NAME, LEGACY_APP_NAME)
        )
        default_language = language_from_locale(QLocale.system().name())
        stored_language = str(self.settings.value("ui/language", default_language))
        self.language_code = stored_language if stored_language in LANGUAGE_CODES else default_language
        QApplication.instance().setLayoutDirection(
            Qt.RightToLeft if self.language_code in RIGHT_TO_LEFT else Qt.LeftToRight
        )
        stored_theme = str(self.settings.value("appearance/theme", "automatic"))
        self.theme_mode = stored_theme if stored_theme in {"automatic", "dark", "light"} else "automatic"
        self._operation_log = OperationLog(operation_log_path)
        self._crash_log_path = default_crash_log_path()
        self._operation_log.record(
            "session_started",
            language=self.language_code,
            theme=self.theme_mode,
            outcome="started",
        )
        self._system_dark_fallback = QApplication.palette().color(QPalette.Window).lightness() < 128
        self._effective_dark = self._theme_is_dark(self.theme_mode)
        self.engine = PdfEngine()
        self._document_session = DocumentSession()
        self.current_page = 0
        self.render_scale = 1.0
        self.edits: dict[str, TextEdit] = {}
        self.inserted_texts: list[TextPlacement] = []
        self.signatures: list[SignaturePlacement] = []
        self.inserted_images: list[ImagePlacement] = []
        self.deleted_images: list[ImageDeletion] = []
        self.history: list[EditorState] = []
        self.history_index = -1
        self._pending_visual: tuple[str, bytes, float, str, float] | None = None
        self._pending_text_box: tuple[str, tuple[float, float, float, float]] | None = None
        self._redaction_target_page: int | None = None
        self._pending_form_field: FormFieldSpec | None = None
        self._form_field_target_page: int | None = None
        self._form_workspace_mode = "none"
        self._form_preview_values: dict[int, object] = {}
        self._syncing_text_toolbar = False
        self._text_toolbar_reference: tuple[str, str] | None = None
        self._text_toolbar_preserved_family: str | None = None
        self._text_font_user_changed = False
        self._render_pending = False
        self._render_in_progress = False
        self._text_color = QColor("#000000")
        self._font_size_value = 12.0
        self.search_matches: list[SearchMatch] = []
        self.search_index = -1
        self._search_query = ""
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._run_search)
        self._search_task: SearchTask | None = None
        self._search_generation = 0
        self._search_cursor_active = False
        self._search_pool = QThreadPool.globalInstance()
        self._tile_renderer = TileRenderCoordinator(self)
        self._tile_renderer.completed.connect(self._tile_render_completed)
        self._legacy_tile_task: object | None = None
        self._tile_source_temporary: tempfile.TemporaryDirectory[str] | None = None
        self._tile_source_workspace: Path | None = None
        self._tile_source_path: Path | None = None
        self._tile_context: tuple[int, int, int, float, float] | None = None
        self._tile_pool = QThreadPool(self)
        self._tile_pool.setMaxThreadCount(1)
        self._tile_pool.setExpiryTimeout(30_000)
        self._tile_timer = QTimer(self)
        self._tile_timer.setSingleShot(True)
        self._tile_timer.setInterval(70)
        self._tile_timer.timeout.connect(self._start_visible_tile_render)
        self._tile_cache: OrderedDict[
            tuple[object, ...], tuple[int, int, QPixmap, int]
        ] = OrderedDict()
        self._tile_cache_bytes = 0
        self._tile_cache_hits = 0
        self._tile_cache_misses = 0
        self._tile_cache_evictions = 0
        self._thumbnail_queue: deque[int] = deque()
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.timeout.connect(self._render_thumbnail_batch)
        self._thumbnail_reorder_context: tuple[int, int] | None = None
        self._thumbnail_reorder_pending = False
        self._outline_model: PdfOutlineModel | None = None
        self.recent_files = self._read_recent_files_setting()
        self._recovery_path = (
            Path(recovery_path)
            if recovery_path is not None
            else self._default_recovery_path()
        )
        self._recovery_protected = self._recovery_path.is_file()
        self._recovery_request_id = 0
        self._recovery_task: RecoveryTask | None = None
        self._recovery_dirty = False
        self._recovery_delete_when_idle = False
        self._recovery_timer = QTimer(self)
        self._recovery_timer.setSingleShot(True)
        self._recovery_timer.setInterval(RECOVERY_DELAY_MS)
        self._recovery_timer.timeout.connect(self._start_recovery_write)
        self._recovery_pool = QThreadPool(self)
        self._recovery_pool.setMaxThreadCount(1)
        self._recovery_pool.setExpiryTimeout(30_000)
        self._update_pool = QThreadPool(self)
        self._update_pool.setMaxThreadCount(1)
        self._update_task: VersionCheckTask | None = None
        self._update_manual = False
        self._update_closing = False
        self._document_writer = DocumentWriteCoordinator(self)
        self._document_writer.completed.connect(self._document_write_finished)
        self._write_progress: QProgressDialog | None = None
        self._inspection_coordinator = InspectionCoordinator(self)
        self._inspection_coordinator.completed.connect(self._inspection_finished)
        self._inspection_report: DocumentInspectionReport | None = None
        self._inspection_error: str | None = None
        self._compatibility_risk_acknowledged = False
        self._ocr_coordinator = OcrCoordinator(self)
        self._ocr_coordinator.completed.connect(self._ocr_finished)
        self._ocr_progress: QProgressDialog | None = None

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(ASSET_DIR / "app_logo.svg")))
        self.resize(1420, 900)
        self.setAcceptDrops(True)

        self.page_list = PageThumbnailList()
        self.page_list.setIconSize(QPixmap(100, 132).size())
        self.page_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.page_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.page_list.setDefaultDropAction(Qt.MoveAction)
        self.page_list.setDragEnabled(True)
        self.page_list.setAcceptDrops(True)
        self.page_list.setDropIndicatorShown(True)
        self.page_list.currentRowChanged.connect(self._page_selected)
        self.page_list.delete_requested.connect(self.delete_current_page)
        self.page_list.context_menu_requested.connect(self._show_page_context_menu)
        self.page_list.model().rowsAboutToBeMoved.connect(
            self._thumbnail_rows_about_to_move
        )
        self.page_list.model().rowsMoved.connect(self._thumbnail_rows_moved)

        self.outline_tree = QTreeView()
        self.outline_tree.setObjectName("outlineTree")
        self.outline_tree.setHeaderHidden(True)
        self.outline_tree.setUniformRowHeights(True)
        self.outline_tree.setAnimated(False)
        self.outline_tree.clicked.connect(self._outline_clicked)

        self.comments_list = QListWidget()
        self.comments_list.setObjectName("commentsList")
        self.comments_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.comments_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.comments_list.itemDoubleClicked.connect(self._comment_item_activated)
        self.comments_list.currentItemChanged.connect(
            lambda _current, _previous: self._update_actions()
        )
        self.comments_list.customContextMenuRequested.connect(
            self._show_comment_context_menu
        )

        self.forms_list = QListWidget()
        self.forms_list.setObjectName("formsList")
        self.forms_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.forms_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.forms_list.itemClicked.connect(self._form_item_selected)
        self.forms_list.itemDoubleClicked.connect(
            lambda _item: self.edit_selected_form_field()
        )
        self.forms_list.currentItemChanged.connect(
            lambda _current, _previous: self._update_actions()
        )
        self.forms_list.customContextMenuRequested.connect(
            self._show_form_context_menu
        )

        self.fill_forms_list = QListWidget()
        self.fill_forms_list.setObjectName("fillFormsList")
        self.fill_forms_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.fill_forms_list.itemClicked.connect(self._form_item_selected)

        self.sidebar_tabs = QTabWidget()
        self.sidebar_tabs.setObjectName("sidebarTabs")
        self.sidebar_tabs.setDocumentMode(True)
        self.sidebar_tabs.setMinimumWidth(210)
        self.sidebar_tabs.setMaximumWidth(420)
        self.pages_tab_index = self.sidebar_tabs.addTab(
            self.page_list,
            self.style().standardIcon(QStyle.SP_FileDialogListView),
            "Pages",
        )
        self.outline_tab_index = self.sidebar_tabs.addTab(
            self.outline_tree,
            self.style().standardIcon(QStyle.SP_DirIcon),
            "Tree",
        )
        self.sidebar_tabs.setTabEnabled(self.outline_tab_index, False)

        self.add_comment_side_button = QPushButton("Add comment...")
        self.edit_comment_side_button = QPushButton("Edit")
        self.delete_comment_side_button = QPushButton("Delete")
        self.add_comment_side_button.clicked.connect(self.start_add_comment)
        self.edit_comment_side_button.clicked.connect(self.edit_selected_comment)
        self.delete_comment_side_button.clicked.connect(self.delete_selected_annotation)
        comments_actions = QHBoxLayout()
        comments_actions.setContentsMargins(6, 4, 6, 4)
        comments_actions.addWidget(self.add_comment_side_button)
        comments_actions.addWidget(self.edit_comment_side_button)
        comments_actions.addWidget(self.delete_comment_side_button)
        comments_panel = QWidget()
        comments_layout = QVBoxLayout(comments_panel)
        comments_layout.setContentsMargins(0, 0, 0, 0)
        comments_layout.setSpacing(0)
        comments_layout.addLayout(comments_actions)
        comments_layout.addWidget(self.comments_list, 1)

        self.create_form_side_button = QPushButton("Create field...")
        self.edit_form_side_button = QPushButton("Edit")
        self.delete_form_side_button = QPushButton("Delete")
        self.create_form_side_button.clicked.connect(self.start_create_form_field)
        self.edit_form_side_button.clicked.connect(self.edit_selected_form_field)
        self.delete_form_side_button.clicked.connect(self.delete_selected_form_field)
        forms_actions = QHBoxLayout()
        forms_actions.setContentsMargins(6, 4, 6, 4)
        forms_actions.addWidget(self.create_form_side_button)
        forms_actions.addWidget(self.edit_form_side_button)
        forms_actions.addWidget(self.delete_form_side_button)
        self.form_edit_mode_button = QPushButton("Edit")
        self.form_edit_mode_button.setCheckable(True)
        self.form_edit_mode_button.setChecked(True)
        self.form_preview_mode_button = QPushButton("Preview")
        self.form_preview_mode_button.setCheckable(True)
        self.reset_form_preview_button = QPushButton("Reset test data")
        self.reset_form_preview_button.setVisible(False)
        self.form_edit_mode_button.clicked.connect(
            lambda: self._set_form_workspace_mode("edit")
        )
        self.form_preview_mode_button.clicked.connect(
            lambda: self._set_form_workspace_mode("preview")
        )
        self.reset_form_preview_button.clicked.connect(self.reset_form_preview)
        forms_modes = QHBoxLayout()
        forms_modes.setContentsMargins(6, 4, 6, 4)
        forms_modes.addWidget(self.form_edit_mode_button)
        forms_modes.addWidget(self.form_preview_mode_button)
        forms_panel = QWidget()
        forms_layout = QVBoxLayout(forms_panel)
        forms_layout.setContentsMargins(0, 0, 0, 0)
        forms_layout.setSpacing(0)
        forms_layout.addLayout(forms_modes)
        forms_layout.addWidget(self.reset_form_preview_button)
        forms_layout.addLayout(forms_actions)
        forms_layout.addWidget(self.forms_list, 1)

        self.fill_forms_hint = QLabel("Fill fields directly on the page.")
        self.fill_forms_hint.setWordWrap(True)
        self.fill_forms_hint.setContentsMargins(8, 6, 8, 6)
        self.clear_form_values_button = QPushButton("Clear form")
        self.add_visual_signature_button = QPushButton("Add visual signature...")
        self.clear_form_values_button.clicked.connect(self.clear_form_values)
        self.add_visual_signature_button.clicked.connect(self.add_signature)
        fill_actions = QHBoxLayout()
        fill_actions.setContentsMargins(6, 4, 6, 4)
        fill_actions.addWidget(self.clear_form_values_button)
        fill_actions.addWidget(self.add_visual_signature_button)
        fill_panel = QWidget()
        fill_layout = QVBoxLayout(fill_panel)
        fill_layout.setContentsMargins(0, 0, 0, 0)
        fill_layout.setSpacing(0)
        fill_layout.addWidget(self.fill_forms_hint)
        fill_layout.addLayout(fill_actions)
        fill_layout.addWidget(self.fill_forms_list, 1)

        self.right_sidebar = CollapsibleToolSidebar()
        self.comments_tool_index = self.right_sidebar.addTab(
            comments_panel,
            self.style().standardIcon(QStyle.SP_MessageBoxInformation),
            "Comments",
        )
        self.forms_tool_index = self.right_sidebar.addTab(
            forms_panel,
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView),
            "Forms",
        )
        self.fill_sign_tool_index = self.right_sidebar.addTab(
            fill_panel,
            self._asset_icon("signature.svg"),
            "Fill & Sign",
        )
        self.right_sidebar.setTabEnabled(self.comments_tool_index, False)
        self.right_sidebar.setTabEnabled(self.forms_tool_index, False)
        self.right_sidebar.setTabEnabled(self.fill_sign_tool_index, False)
        self.right_sidebar.currentChanged.connect(self._right_tool_changed)
        self.right_sidebar.collapsed.connect(self._right_tools_collapsed)

        self.page_view = PageView()
        self.page_view.edit_requested.connect(self._edit_run)
        self.page_view.inline_edit_requested.connect(self._start_inline_text_edit)
        self.page_view.inline_edit_finished.connect(self._finish_inline_text_edit)
        self.page_view.inline_edit_cancelled.connect(self._cancel_inline_text_edit)
        self.page_view.inline_editor_closed.connect(self._resume_deferred_render)
        self.page_view.pointer_interaction_finished.connect(self._resume_deferred_render)
        self.page_view.page_refresh_requested.connect(self._render_current_page)
        self.page_view.new_text_box_requested.connect(self._create_text_box)
        self.page_view.redaction_area_requested.connect(
            self._confirm_redaction,
            Qt.QueuedConnection,
        )
        self.page_view.form_field_area_requested.connect(
            self._create_form_field,
            Qt.QueuedConnection,
        )
        # Form controls live inside QGraphicsProxyWidget items. Their handlers
        # can rebuild the whole page scene, so defer mutations until the
        # originating widget's click/focus event has completely returned.
        # Destroying the active proxy synchronously can crash Qt on Windows.
        self.page_view.form_value_edited.connect(
            self._form_value_edited,
            Qt.QueuedConnection,
        )
        self.page_view.form_signature_requested.connect(
            self._form_signature_requested,
            Qt.QueuedConnection,
        )
        self.page_view.text_transform_requested.connect(
            self._transform_text,
            Qt.QueuedConnection,
        )
        self.page_view.text_selection_changed.connect(self._text_selection_changed)
        self.page_view.delete_text_requested.connect(self._delete_text, Qt.QueuedConnection)
        self.page_view.cancel_requested.connect(self.cancel_special_mode)
        self.page_view.placement_clicked.connect(self._place_visual, Qt.QueuedConnection)
        self.page_view.comment_placement_clicked.connect(
            self._place_comment,
            Qt.QueuedConnection,
        )
        self.page_view.delete_image_requested.connect(self._delete_visual, Qt.QueuedConnection)
        self.page_view.source_image_edit_requested.connect(
            self._promote_source_image,
            Qt.QueuedConnection,
        )
        self.page_view.visual_transform_requested.connect(
            self._transform_visual,
            Qt.QueuedConnection,
        )
        self.page_view.object_context_menu_requested.connect(
            self._show_object_context_menu
        )
        self.page_view.signature_selection_changed.connect(self._signature_selection_changed)
        self.page_view.page_scroll_requested.connect(self._scroll_main_view)
        self.page_view.visible_area_changed.connect(self._schedule_tile_render)

        splitter = QSplitter()
        splitter.addWidget(self.sidebar_tabs)
        splitter.addWidget(self.page_view)
        splitter.addWidget(self.right_sidebar)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 1092, 48])

        workspace = QWidget(self)
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        self._make_find_bar(workspace)
        workspace_layout.addWidget(self.find_bar)
        workspace_layout.addWidget(splitter, 1)
        self.setCentralWidget(workspace)

        self._make_actions()
        self._make_menu()
        self._make_toolbar()
        self.status_label = QLabel(self.trx("open_to_begin"))
        self.statusBar().addPermanentWidget(self.status_label)
        self._apply_theme(persist=False)
        self._retranslate_ui()
        try:
            QApplication.instance().styleHints().colorSchemeChanged.connect(self._system_theme_changed)
        except (AttributeError, TypeError):
            pass
        self._update_actions()

    @property
    def document_path(self) -> Path | None:
        return self._document_session.document_path

    @document_path.setter
    def document_path(self, value: Path | None) -> None:
        self._document_session.document_path = value

    @property
    def save_target_path(self) -> Path | None:
        return self._document_session.save_target_path

    @save_target_path.setter
    def save_target_path(self, value: Path | None) -> None:
        self._document_session.save_target_path = value

    @property
    def saved_history_index(self) -> int | None:
        return self._document_session.saved_history_index

    @saved_history_index.setter
    def saved_history_index(self, value: int | None) -> None:
        self._document_session.saved_history_index = value

    @property
    def _document_generation(self) -> int:
        return self._document_session.document_generation

    @_document_generation.setter
    def _document_generation(self, value: int) -> None:
        self._document_session.document_generation = value

    @property
    def _content_revision(self) -> int:
        return self._document_session.content_revision

    @_content_revision.setter
    def _content_revision(self, value: int) -> None:
        self._document_session.content_revision = value

    @property
    def _write_process(self) -> QProcess | None:
        """Compatibility view of the process now owned by the coordinator."""

        return self._document_writer.process

    @property
    def _inspection_process(self) -> QProcess | None:
        """Compatibility view of the isolated inspection process."""

        return self._inspection_coordinator.process

    @property
    def _tile_task(self) -> object | None:
        """Compatibility view for process and legacy runnable tests."""

        return self._tile_renderer.process or self._legacy_tile_task

    @_tile_task.setter
    def _tile_task(self, value: object | None) -> None:
        self._legacy_tile_task = value

    @property
    def _ocr_process(self) -> QProcess | None:
        """Compatibility view of the isolated OCR process."""

        return self._ocr_coordinator.process

    def trx(self, key: str, **values: object) -> str:
        return translate(self.language_code, key, **values)

    @staticmethod
    def _default_recovery_path() -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / LEGACY_APP_NAME / "Recovery" / "current.openpdf-recovery"
        root = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
        if not root:
            root = str(Path(QStandardPaths.writableLocation(QStandardPaths.TempLocation)) / LEGACY_APP_NAME)
        return Path(root) / "Recovery" / "current.openpdf-recovery"

    @staticmethod
    def _normalized_file_path(path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        try:
            return candidate.absolute()
        except OSError:
            return candidate

    @staticmethod
    def _recent_path_key(path: str | Path) -> str:
        return str(MainWindow._normalized_file_path(path)).casefold()

    def _read_recent_files_setting(self) -> list[Path]:
        stored = self.settings.value("files/recent", [])
        if isinstance(stored, str):
            values = [stored]
        elif isinstance(stored, (list, tuple)):
            values = list(stored)
        else:
            values = []
        result: list[Path] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            path = self._normalized_file_path(value)
            key = self._recent_path_key(path)
            if path.suffix.lower() != ".pdf" or key in seen:
                continue
            seen.add(key)
            result.append(path)
            if len(result) == MAX_RECENT_FILES:
                break
        return result

    def _store_recent_files(self) -> None:
        self.settings.setValue("files/recent", [str(path) for path in self.recent_files])
        self.settings.sync()

    def _add_recent_file(self, path: str | Path) -> None:
        candidate = self._normalized_file_path(path)
        if candidate.suffix.lower() != ".pdf":
            return
        key = self._recent_path_key(candidate)
        self.recent_files = [
            existing
            for existing in self.recent_files
            if self._recent_path_key(existing) != key
        ]
        self.recent_files.insert(0, candidate)
        del self.recent_files[MAX_RECENT_FILES:]
        self._store_recent_files()
        if hasattr(self, "recent_menu"):
            self._rebuild_recent_menu()

    def _remove_recent_file(self, path: str | Path) -> None:
        key = self._recent_path_key(path)
        self.recent_files = [
            existing
            for existing in self.recent_files
            if self._recent_path_key(existing) != key
        ]
        self._store_recent_files()
        if hasattr(self, "recent_menu"):
            self._rebuild_recent_menu()

    def clear_recent_files(self) -> None:
        self.recent_files = []
        self._store_recent_files()
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        if not hasattr(self, "recent_menu"):
            return
        self.recent_menu.clear()
        if not self.recent_files:
            empty = self.recent_menu.addAction(self.trx("no_recent_files"))
            empty.setEnabled(False)
            return
        for index, path in enumerate(self.recent_files, 1):
            native_path = str(path).replace("&", "&&")
            action = self.recent_menu.addAction(f"&{index}  {native_path}")
            action.setToolTip(str(path))
            action.setData(str(path))
            action.triggered.connect(
                lambda checked=False, selected=str(path): self._open_recent_file(selected)
            )
        self.recent_menu.addSeparator()
        clear_action = self.recent_menu.addAction(self.trx("clear_recent_files"))
        clear_action.triggered.connect(self.clear_recent_files)

    def _open_recent_file(self, path: str) -> None:
        candidate = Path(path)
        if not candidate.is_file():
            self._remove_recent_file(candidate)
            QMessageBox.warning(
                self,
                self.trx("unable_open_title"),
                self.trx("recent_file_missing", path=candidate),
            )
            return
        self.open_pdf(str(candidate))

    def _recovery_snapshot(self) -> RecoverySnapshot:
        state = self._capture_state()
        return RecoverySnapshot(
            pdf_bytes=state.pdf_bytes,
            edits=tuple(sorted(state.edits.values(), key=lambda item: item.run.key)),
            inserted_texts=tuple(state.inserted_texts),
            signatures=tuple(state.signatures),
            inserted_images=tuple(state.inserted_images),
            deleted_images=tuple(state.deleted_images),
            document_path=str(self.document_path) if self.document_path else None,
            save_target_path=str(self.save_target_path) if self.save_target_path else None,
            current_page=self.current_page,
            render_scale=self.render_scale,
        )

    def _schedule_recovery(self) -> None:
        if self._recovery_protected or not self.has_unsaved_changes:
            return
        self._recovery_timer.start()

    def _sync_recovery_to_state(self) -> None:
        if self.has_unsaved_changes:
            self._schedule_recovery()
        else:
            self._clear_recovery(wait=False)

    def _start_recovery_write(self) -> None:
        if self._recovery_protected or not self.has_unsaved_changes:
            return
        if self._recovery_task is not None:
            self._recovery_dirty = True
            return
        try:
            snapshot = self._recovery_snapshot()
        except Exception as exc:
            self.statusBar().showMessage(
                self.trx("recovery_unavailable", error=exc),
                6000,
            )
            return
        self._recovery_request_id += 1
        request_id = self._recovery_request_id
        task = RecoveryTask(request_id, str(self._recovery_path), snapshot)
        task.signals.finished.connect(self._recovery_write_finished)
        self._recovery_task = task
        self._recovery_dirty = False
        self._recovery_delete_when_idle = False
        self._recovery_pool.start(task)

    def _recovery_write_finished(self, request_id: int, error: object) -> None:
        task = self._recovery_task
        if task is not None and task.request_id == request_id:
            self._recovery_task = None
        if self._recovery_delete_when_idle:
            remove_recovery_file(self._recovery_path)
            self._recovery_delete_when_idle = False
        is_current = request_id == self._recovery_request_id
        if is_current and error and self.has_unsaved_changes:
            self.statusBar().showMessage(
                self.trx("recovery_unavailable", error=error),
                6000,
            )
        if self._recovery_dirty and self.has_unsaved_changes and not self._recovery_protected:
            self._recovery_dirty = False
            self._recovery_timer.start(100)

    def _clear_recovery(self, *, wait: bool, force: bool = False) -> None:
        if self._recovery_protected and not force:
            return
        self._recovery_timer.stop()
        self._recovery_dirty = False
        self._recovery_request_id += 1
        task = self._recovery_task
        if task is not None:
            task.cancel()
        remove_recovery_file(self._recovery_path)
        if task is not None and wait:
            self._recovery_pool.waitForDone()
            self._recovery_task = None
            remove_recovery_file(self._recovery_path)
            self._recovery_delete_when_idle = False
        elif task is not None:
            self._recovery_delete_when_idle = True

    def _report_damaged_recovery(self, error: Exception) -> None:
        preserved = quarantine_recovery_file(self._recovery_path)
        self._recovery_protected = preserved is None and self._recovery_path.exists()
        shown_path = preserved or self._recovery_path
        QMessageBox.critical(
            self,
            self.trx("recovery_failed_title"),
            self.trx("recovery_failed_message", path=shown_path, error=error),
        )

    def _restore_recovery_snapshot(self, snapshot: RecoverySnapshot) -> bool:
        candidate = PdfEngine()
        try:
            validate_recovery_assets(snapshot)
            candidate.load_bytes(snapshot.pdf_bytes, snapshot.document_path)
            validate_recovery_pages(snapshot, candidate.page_count)
        except Exception:
            candidate.close()
            raise
        state = EditorState(
            pdf_bytes=snapshot.pdf_bytes,
            edits={item.run.key: item for item in snapshot.edits},
            inserted_texts=list(snapshot.inserted_texts),
            signatures=list(snapshot.signatures),
            inserted_images=list(snapshot.inserted_images),
            deleted_images=list(snapshot.deleted_images),
        )
        document_path = Path(snapshot.document_path) if snapshot.document_path else None
        save_target = Path(snapshot.save_target_path) if snapshot.save_target_path else None
        self._activate_document(
            candidate,
            document_path,
            already_saved=False,
            initial_state=state,
            initial_page=snapshot.current_page,
            initial_scale=snapshot.render_scale,
            save_target_path=save_target,
            preserve_recovery=True,
        )
        if document_path is not None and document_path.is_file():
            self._add_recent_file(document_path)
        self.statusBar().showMessage(self.trx("recovery_restored"), 6000)
        return True

    def _ask_recovery_action(self, name: str) -> str:
        prompt = QMessageBox(
            QMessageBox.Warning,
            self.trx("recovery_title"),
            self.trx("recovery_question", name=name),
            parent=self,
        )
        restore_button = prompt.addButton(self.trx("restore"), QMessageBox.AcceptRole)
        discard_button = prompt.addButton(self.trx("discard"), QMessageBox.DestructiveRole)
        prompt.setDefaultButton(restore_button)
        prompt.exec()
        clicked = prompt.clickedButton()
        if clicked is restore_button:
            return "restore"
        if clicked is discard_button:
            return "discard"
        return "later"

    def offer_recovery(self) -> bool:
        """Offer to restore the last atomically saved unsaved editor state."""

        if not self._recovery_path.is_file():
            self._recovery_protected = False
            return False
        try:
            snapshot = read_recovery_snapshot(self._recovery_path)
        except Exception as exc:
            self._report_damaged_recovery(exc)
            return False
        name = (
            Path(snapshot.document_path).name
            if snapshot.document_path
            else self.trx("untitled")
        )
        action = self._ask_recovery_action(name)
        if action == "restore":
            self._recovery_protected = False
            try:
                return self._restore_recovery_snapshot(snapshot)
            except Exception as exc:
                self._report_damaged_recovery(exc)
                return False
        if action == "discard":
            self._recovery_protected = False
            self._clear_recovery(wait=True, force=True)
        return False

    def _asset_icon(self, name: str) -> QIcon:
        try:
            svg = (ASSET_DIR / name).read_text(encoding="utf-8")
            if not self._effective_dark:
                svg = svg.replace("#ffffff", "#17212b")
                svg = svg.replace("#ffd166", "#9a5700")
                svg = svg.replace("#ff6b6b", "#c62828")
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            pixmap = QPixmap(32, 32)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            return QIcon(pixmap)
        except Exception:
            return QIcon(str(ASSET_DIR / name))

    def _make_find_bar(self, parent: QWidget) -> None:
        self.find_bar = QWidget(parent)
        self.find_bar.setObjectName("findBar")
        self.find_bar.setFixedHeight(40)
        layout = QHBoxLayout(self.find_bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.find_label = QLabel("Find:", self.find_bar)
        layout.addWidget(self.find_label)
        self.find_edit = QLineEdit(self.find_bar)
        self.find_edit.setObjectName("findEdit")
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.setMinimumWidth(240)
        self.find_edit.setMaximumWidth(520)
        self.find_edit.setFixedHeight(30)
        self.find_edit.textChanged.connect(self._queue_search)
        self.find_edit.returnPressed.connect(self.find_next)
        self.find_edit.installEventFilter(self)
        layout.addWidget(self.find_edit, 1)

        self.find_result_label = QLabel("0 / 0", self.find_bar)
        self.find_result_label.setObjectName("findResultLabel")
        self.find_result_label.setAlignment(Qt.AlignCenter)
        self.find_result_label.setFixedWidth(64)
        layout.addWidget(self.find_result_label)

        self.find_previous_button = QToolButton(self.find_bar)
        self.find_previous_button.setObjectName("findButton")
        self.find_previous_button.setIcon(
            self.style().standardIcon(QStyle.SP_ArrowUp)
        )
        self.find_previous_button.setFixedSize(30, 30)
        self.find_previous_button.clicked.connect(self.find_previous)
        layout.addWidget(self.find_previous_button)

        self.find_next_button = QToolButton(self.find_bar)
        self.find_next_button.setObjectName("findButton")
        self.find_next_button.setIcon(
            self.style().standardIcon(QStyle.SP_ArrowDown)
        )
        self.find_next_button.setFixedSize(30, 30)
        self.find_next_button.clicked.connect(self.find_next)
        layout.addWidget(self.find_next_button)

        self.find_close_button = QToolButton(self.find_bar)
        self.find_close_button.setObjectName("findButton")
        self.find_close_button.setIcon(
            self.style().standardIcon(QStyle.SP_TitleBarCloseButton)
        )
        self.find_close_button.setFixedSize(30, 30)
        self.find_close_button.clicked.connect(self.hide_find_bar)
        layout.addWidget(self.find_close_button)
        layout.addStretch(1)
        self.find_bar.hide()

    def _make_actions(self) -> None:
        self.new_action = QAction(self.style().standardIcon(QStyle.SP_FileIcon), "New PDF...", self)
        self.new_action.setShortcut(QKeySequence.New)
        self.new_action.setToolTip("Create a new blank PDF (Ctrl+N)")
        self.new_action.triggered.connect(self.new_document)
        self.open_action = QAction(self.style().standardIcon(QStyle.SP_DialogOpenButton), "Open...", self)
        self.open_action.setShortcut(QKeySequence.Open)
        self.open_action.triggered.connect(self.open_dialog)
        self.close_document_action = QAction(
            self.style().standardIcon(QStyle.SP_DialogCloseButton),
            "Close document",
            self,
        )
        self.close_document_action.setShortcut(QKeySequence.Close)
        self.close_document_action.triggered.connect(self.close_document)
        self.save_action = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "Save", self)
        self.save_action.setShortcut(QKeySequence.Save)
        self.save_action.triggered.connect(self.save_document)
        self.save_as_action = QAction(
            self.style().standardIcon(QStyle.SP_DialogSaveButton),
            "Save As...",
            self,
        )
        self.save_as_action.setShortcut(QKeySequence.SaveAs)
        self.save_as_action.triggered.connect(self.save_as)
        self.save_copy_action = QAction(
            self.style().standardIcon(QStyle.SP_DialogSaveButton),
            "Save a Copy...",
            self,
        )
        self.save_copy_action.setShortcut(QKeySequence("Ctrl+Alt+S"))
        self.save_copy_action.triggered.connect(self.save_copy)
        self.print_action = QAction(self._asset_icon("print.svg"), "Print...", self)
        self.print_action.setShortcut(QKeySequence.Print)
        self.print_action.setToolTip("Print the current document (Ctrl+P)")
        self.print_action.triggered.connect(self.print_document)

        self.undo_action = QAction(self._asset_icon("undo.svg"), "Undo", self)
        self.undo_action.setShortcut(QKeySequence.Undo)
        self.undo_action.setToolTip("Undo (Ctrl+Z)")
        self.undo_action.triggered.connect(self.undo)
        self.redo_action = QAction(self._asset_icon("redo.svg"), "Redo", self)
        self.redo_action.setShortcut(QKeySequence.Redo)
        self.redo_action.setToolTip("Redo (Ctrl+Y)")
        self.redo_action.triggered.connect(self.redo)

        self.find_action = QAction("Find...", self)
        self.find_action.setShortcut(QKeySequence.Find)
        self.find_action.triggered.connect(self.show_find_bar)
        self.find_next_action = QAction("Find next", self)
        self.find_next_action.setShortcut(QKeySequence("F3"))
        self.find_next_action.triggered.connect(self.find_next)
        self.find_previous_action = QAction("Find previous", self)
        self.find_previous_action.setShortcut(QKeySequence("Shift+F3"))
        self.find_previous_action.triggered.connect(self.find_previous)

        self.add_text_action = QAction(self._asset_icon("text_add.svg"), "Add text box", self)
        self.add_text_action.setToolTip("Draw a text box on the page and type directly into it")
        self.add_text_action.setShortcut(QKeySequence("Ctrl+Alt+T"))
        self.add_text_action.triggered.connect(self.start_add_text)
        self.delete_text_action = QAction(self._asset_icon("text_remove.svg"), "Delete selected text", self)
        self.delete_text_action.setToolTip("Remove the selected original or inserted text")
        self.delete_text_action.triggered.connect(self.delete_selected_text)

        self.zoom_in_action = QAction(self._asset_icon("zoom_in.svg"), "Zoom in", self)
        self.zoom_in_action.setShortcut(QKeySequence.ZoomIn)
        self.zoom_in_action.setToolTip("Zoom in")
        self.zoom_in_action.triggered.connect(lambda: self.step_zoom(1))
        self.zoom_out_action = QAction(self._asset_icon("zoom_out.svg"), "Zoom out", self)
        self.zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        self.zoom_out_action.setToolTip("Zoom out")
        self.zoom_out_action.triggered.connect(lambda: self.step_zoom(-1))
        self.fit_width_action = QAction(self._asset_icon("fit_width.svg"), "Fit width", self)
        self.fit_width_action.setToolTip("Fit page width to window")
        self.fit_width_action.triggered.connect(self.fit_width)

        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for mode, label in (
            ("automatic", "Automatic (system)"),
            ("dark", "Dark"),
            ("light", "Light"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(mode)
            action.setChecked(mode == self.theme_mode)
            self.theme_group.addAction(action)
            self.theme_actions[mode] = action
        self.theme_group.triggered.connect(lambda action: self.set_theme(str(action.data())))

        self.language_group = QActionGroup(self)
        self.language_group.setExclusive(True)
        self.language_actions: dict[str, QAction] = {}
        for language in LANGUAGES:
            label = language.native_name
            if language.native_name != language.english_name:
                label += f" ({language.english_name})"
            action = QAction(language_icon(language.code), label, self)
            action.setCheckable(True)
            action.setData(language.code)
            action.setChecked(language.code == self.language_code)
            self.language_group.addAction(action)
            self.language_actions[language.code] = action
        self.language_group.triggered.connect(
            lambda action: self.set_language(str(action.data()))
        )

        self.add_blank_page_action = QAction(self._asset_icon("page_add.svg"), "Add blank page", self)
        self.add_blank_page_action.setToolTip("Insert a blank page after the current page")
        self.add_blank_page_action.triggered.connect(self.add_blank_page)
        self.insert_pdf_action = QAction(self._asset_icon("pages_import.svg"), "Insert pages from PDF...", self)
        self.insert_pdf_action.setToolTip("Insert all pages from another PDF after the current page")
        self.insert_pdf_action.triggered.connect(self.insert_pdf_pages)
        self.delete_page_action = QAction(self._asset_icon("page_remove.svg"), "Delete current page", self)
        self.delete_page_action.setToolTip("Delete the current page")
        self.delete_page_action.triggered.connect(self.delete_current_page)
        self.move_page_up_action = QAction("Move page earlier", self)
        self.move_page_up_action.setShortcut(QKeySequence("Alt+Shift+Up"))
        self.move_page_up_action.triggered.connect(self.move_current_page_up)
        self.move_page_down_action = QAction("Move page later", self)
        self.move_page_down_action.setShortcut(QKeySequence("Alt+Shift+Down"))
        self.move_page_down_action.triggered.connect(self.move_current_page_down)
        self.rotate_page_left_action = QAction(
            self._asset_icon("rotate_left.svg"),
            "Rotate page left",
            self,
        )
        self.rotate_page_left_action.setShortcut(QKeySequence("Ctrl+Shift+Left"))
        self.rotate_page_left_action.triggered.connect(
            lambda _checked=False: self.rotate_current_page(-1)
        )
        self.rotate_page_right_action = QAction(
            self._asset_icon("rotate_right.svg"),
            "Rotate page right",
            self,
        )
        self.rotate_page_right_action.setShortcut(QKeySequence("Ctrl+Shift+Right"))
        self.rotate_page_right_action.triggered.connect(
            lambda _checked=False: self.rotate_current_page(1)
        )

        self.add_image_action = QAction(self._asset_icon("image_add.svg"), "Insert image...", self)
        self.add_image_action.setToolTip("Insert a PNG, JPEG, BMP, TIFF, or WebP image")
        self.add_image_action.triggered.connect(self.add_image)
        self.delete_image_action = QAction(self._asset_icon("image_remove.svg"), "Delete image", self)
        self.delete_image_action.setToolTip("Select an image or visual signature to remove")
        self.delete_image_action.triggered.connect(self.start_delete_image)
        self.edit_original_image_action = QAction("Edit original image...", self)
        self.edit_original_image_action.triggered.connect(self.start_edit_original_image)

        self.signature_action = QAction(self._asset_icon("signature.svg"), "Add visual signature...", self)
        self.signature_action.setToolTip("Draw or type a rotatable visual signature")
        self.signature_action.triggered.connect(self.add_signature)
        self.add_comment_action = QAction("Add comment...", self)
        self.add_comment_action.setShortcut(QKeySequence("Ctrl+Alt+M"))
        self.add_comment_action.triggered.connect(self.start_add_comment)
        self.edit_comment_action = QAction("Edit selected comment...", self)
        self.edit_comment_action.triggered.connect(self.edit_selected_comment)
        self.delete_comment_action = QAction("Delete selected annotation", self)
        self.delete_comment_action.triggered.connect(self.delete_selected_annotation)
        self.edit_form_action = QAction("Edit selected form field...", self)
        self.edit_form_action.triggered.connect(self.edit_selected_form_field)
        self.create_form_action = QAction("Create form field...", self)
        self.create_form_action.setShortcut(QKeySequence("Ctrl+Alt+F"))
        self.create_form_action.triggered.connect(self.start_create_form_field)
        self.delete_form_action = QAction("Delete selected form field", self)
        self.delete_form_action.triggered.connect(self.delete_selected_form_field)
        self.redact_area_action = QAction("Permanently redact area...", self)
        self.redact_area_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.redact_area_action.triggered.connect(self.start_redact_area)
        self.compress_action = QAction(self._asset_icon("compress.svg"), "Compress PDF...", self)
        self.compress_action.setToolTip("Save an optimized or image-compressed copy")
        self.compress_action.triggered.connect(self.compress_pdf)

        self.compatibility_action = QAction("Document compatibility...", self)
        self.compatibility_action.triggered.connect(self.show_document_compatibility)
        self.ocr_page_action = QAction("OCR current page...", self)
        self.ocr_page_action.triggered.connect(self.ocr_current_page)
        self.ocr_document_action = QAction("OCR document...", self)
        self.ocr_document_action.triggered.connect(self.ocr_document)

        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.close)
        self.export_diagnostics_action = QAction(
            "Export anonymized diagnostics...", self
        )
        self.export_diagnostics_action.triggered.connect(self.export_diagnostics)
        self.about_action = QAction("About", self)
        self.about_action.triggered.connect(self.show_about)
        self.check_for_updates_action = QAction("Check for updates...", self)
        self.check_for_updates_action.triggered.connect(self.check_for_updates)
        self.automatic_updates_action = QAction(self)
        self.automatic_updates_action.setCheckable(True)
        self.automatic_updates_action.setChecked(
            str(self.settings.value("updates/enabled", "true")).lower() == "true"
        )
        self.automatic_updates_action.toggled.connect(self._set_automatic_updates)

    def _make_menu(self) -> None:
        self.file_menu = self.menuBar().addMenu("File")
        self.file_menu.addAction(self.new_action)
        self.file_menu.addAction(self.open_action)
        self.recent_menu = self.file_menu.addMenu("Recent files")
        self.recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        self._rebuild_recent_menu()
        self.file_menu.addAction(self.close_document_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.save_action)
        self.file_menu.addAction(self.save_as_action)
        self.file_menu.addAction(self.save_copy_action)
        self.file_menu.addAction(self.print_action)
        self.file_menu.addAction(self.compress_action)
        self.file_menu.addAction(self.compatibility_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)

        self.edit_menu = self.menuBar().addMenu("Edit")
        self.edit_menu.addAction(self.undo_action)
        self.edit_menu.addAction(self.redo_action)
        self.edit_menu.addSeparator()
        self.edit_menu.addAction(self.find_action)
        self.edit_menu.addAction(self.find_next_action)
        self.edit_menu.addAction(self.find_previous_action)
        self.edit_menu.addSeparator()
        self.edit_menu.addAction(self.delete_text_action)
        self.edit_menu.addAction(self.redact_area_action)

        self.insert_menu = self.menuBar().addMenu("Insert")
        self.insert_menu.addAction(self.add_text_action)
        self.insert_menu.addSeparator()
        self.insert_menu.addAction(self.add_blank_page_action)
        self.insert_menu.addAction(self.insert_pdf_action)
        self.insert_menu.addSeparator()
        self.insert_menu.addAction(self.add_image_action)
        self.insert_menu.addAction(self.signature_action)
        self.insert_menu.addAction(self.add_comment_action)

        self.page_menu = self.menuBar().addMenu("Page")
        self.page_menu.addAction(self.move_page_up_action)
        self.page_menu.addAction(self.move_page_down_action)
        self.page_menu.addSeparator()
        self.page_menu.addAction(self.rotate_page_left_action)
        self.page_menu.addAction(self.rotate_page_right_action)
        self.page_menu.addSeparator()
        self.page_menu.addAction(self.delete_page_action)
        self.page_menu.addSeparator()
        self.page_menu.addAction(self.ocr_page_action)
        self.page_menu.addAction(self.ocr_document_action)

        self.image_menu = self.menuBar().addMenu("Image")
        self.image_menu.addAction(self.add_image_action)
        self.image_menu.addAction(self.edit_original_image_action)
        self.image_menu.addAction(self.delete_image_action)

        self.comments_menu = self.menuBar().addMenu("Comments")
        self.comments_menu.addAction(self.add_comment_action)
        self.comments_menu.addAction(self.edit_comment_action)
        self.comments_menu.addAction(self.delete_comment_action)

        self.forms_menu = self.menuBar().addMenu("Forms")
        self.forms_menu.addAction(self.create_form_action)
        self.forms_menu.addSeparator()
        self.forms_menu.addAction(self.edit_form_action)
        self.forms_menu.addAction(self.delete_form_action)

        self.view_menu = self.menuBar().addMenu("View")
        self.view_menu.addAction(self.zoom_in_action)
        self.view_menu.addAction(self.zoom_out_action)
        self.view_menu.addAction(self.fit_width_action)
        self.view_menu.addSeparator()
        self.appearance_menu = self.view_menu.addMenu("Appearance")
        self.appearance_menu.addActions(self.theme_group.actions())
        self.language_menu = self.view_menu.addMenu(language_icon(self.language_code), "Language")
        self.language_menu.addActions(self.language_group.actions())

        self.help_menu = self.menuBar().addMenu("Help")
        self.help_menu.addAction(self.export_diagnostics_action)
        self.help_menu.addAction(self.check_for_updates_action)
        self.help_menu.addAction(self.automatic_updates_action)
        self.help_menu.addSeparator()
        self.help_menu.addAction(self.about_action)

    def _make_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        self.toolbar = toolbar
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QPixmap(24, 24).size())
        toolbar.setContentsMargins(0, 0, 41, 0)
        toolbar.installEventFilter(self)
        self._style_toolbar()
        toolbar.addAction(self.new_action)
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.save_action)
        toolbar.addAction(self.print_action)
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)
        toolbar.addSeparator()
        toolbar.addAction(self.zoom_out_action)

        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setInsertPolicy(QComboBox.NoInsert)
        self.zoom_combo.setFixedWidth(72)
        self.zoom_combo.addItems([f"{level}%" for level in ZOOM_LEVELS])
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.setToolTip("Current zoom")
        self.zoom_combo.activated.connect(self._zoom_entered)
        self.zoom_combo.lineEdit().editingFinished.connect(self._zoom_entered)
        toolbar.addWidget(self.zoom_combo)

        toolbar.addAction(self.zoom_in_action)
        toolbar.addAction(self.fit_width_action)
        toolbar.addSeparator()
        self._add_text_controls(toolbar)

        # Keep the most-used editing controls first. If the window is narrow,
        # Qt moves these trailing document actions into the overflow menu.
        toolbar.addAction(self.compress_action)
        toolbar.addAction(self.add_blank_page_action)
        toolbar.addAction(self.insert_pdf_action)
        toolbar.addAction(self.rotate_page_left_action)
        toolbar.addAction(self.rotate_page_right_action)
        toolbar.addAction(self.delete_page_action)
        toolbar.addSeparator()
        toolbar.addAction(self.add_image_action)
        toolbar.addAction(self.delete_image_action)
        toolbar.addAction(self.signature_action)

        # This button is a direct toolbar child instead of a toolbar action.
        # The reserved right margin keeps it visible even while ordinary
        # actions move into Qt's overflow menu on narrower windows.
        self.language_button = QToolButton(toolbar)
        self.language_button.setObjectName("languageButton")
        self.language_button.setFixedSize(39, 39)
        self.language_button.setIcon(language_icon(self.language_code))
        self.language_button.setIconSize(QPixmap(30, 22).size())
        self.language_button.setPopupMode(QToolButton.InstantPopup)
        self.language_button.setMenu(QMenu(self.language_button))
        self.language_button.menu().addActions(self.language_group.actions())
        self.addToolBar(toolbar)
        self._position_language_button()

    def _add_text_controls(self, toolbar: QToolBar) -> None:
        toolbar.addAction(self.add_text_action)
        toolbar.addAction(self.delete_text_action)
        toolbar.addSeparator()

        controls = QWidget(toolbar)
        controls.setObjectName("textControls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(2, 0, 2, 0)
        controls_layout.setSpacing(3)

        self.text_font_box = QFontComboBox(controls)
        self.text_font_box.setFixedSize(120, 30)
        self.text_font_box.view().setMinimumWidth(320)
        self.text_font_box.setCurrentFont(QFont("Arial"))
        self.text_font_box.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.text_font_box.currentFontChanged.connect(self._font_selection_changed)
        self.text_font_box.activated.connect(
            lambda *_: QTimer.singleShot(0, self._show_font_name_start)
        )
        self.text_font_box.lineEdit().editingFinished.connect(self._show_font_name_start)
        controls_layout.addWidget(self.text_font_box)

        self.text_size_box = QComboBox(controls)
        self.text_size_box.setObjectName("fontSizeCombo")
        self.text_size_box.setEditable(True)
        self.text_size_box.setInsertPolicy(QComboBox.NoInsert)
        self.text_size_box.addItems([f"{size} pt" for size in FONT_SIZE_PRESETS])
        self.text_size_box.setCurrentText(self._format_font_size(self._font_size_value))
        self.text_size_box.setFixedSize(72, 30)
        self.text_size_box.view().setMinimumWidth(86)
        self.text_size_box.lineEdit().setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.text_size_box.activated.connect(self._font_size_changed)
        self.text_size_box.lineEdit().editingFinished.connect(self._font_size_changed)
        controls_layout.addWidget(self.text_size_box)

        self.text_bold_button = self._text_style_button("B")
        bold_font = self.text_bold_button.font()
        bold_font.setBold(True)
        self.text_bold_button.setFont(bold_font)
        self.text_italic_button = self._text_style_button("I")
        italic_font = self.text_italic_button.font()
        italic_font.setItalic(True)
        self.text_italic_button.setFont(italic_font)
        self.text_underline_button = self._text_style_button("U")
        underline_font = self.text_underline_button.font()
        underline_font.setUnderline(True)
        self.text_underline_button.setFont(underline_font)
        for button in (
            self.text_bold_button,
            self.text_italic_button,
            self.text_underline_button,
        ):
            button.setFocusPolicy(Qt.ClickFocus)
            button.toggled.connect(lambda *_: self._apply_selected_text_format())
            controls_layout.addWidget(button)

        self.text_color_button = QToolButton(controls)
        self.text_color_button.setObjectName("textColorButton")
        self.text_color_button.setText("A")
        self.text_color_button.setFixedSize(28, 30)
        self.text_color_button.clicked.connect(self._choose_text_color)
        controls_layout.addWidget(self.text_color_button)
        controls.setFixedSize(controls.sizeHint())
        toolbar.addWidget(controls)
        self.text_controls_widget = controls
        for widget in (
            controls,
            self.text_font_box,
            self.text_font_box.lineEdit(),
            self.text_size_box,
            self.text_size_box.lineEdit(),
            self.text_bold_button,
            self.text_italic_button,
            self.text_underline_button,
            self.text_color_button,
        ):
            if widget is not None:
                widget.installEventFilter(self)
        self._show_font_name_start()
        self._show_font_size_start()
        self._refresh_text_color_button()

    @staticmethod
    def _text_style_button(label: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("textStyleButton")
        button.setText(label)
        button.setCheckable(True)
        button.setFixedSize(28, 30)
        return button

    def _theme_is_dark(self, mode: str) -> bool:
        if mode == "dark":
            return True
        if mode == "light":
            return False
        try:
            scheme = QApplication.instance().styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return True
            if scheme == Qt.ColorScheme.Light:
                return False
        except (AttributeError, TypeError):
            pass
        return self._system_dark_fallback

    @staticmethod
    def _palette(dark: bool) -> QPalette:
        palette = QPalette()
        if dark:
            colors = {
                QPalette.Window: "#20242a",
                QPalette.WindowText: "#f2f5f7",
                QPalette.Base: "#15191e",
                QPalette.AlternateBase: "#2a3038",
                QPalette.ToolTipBase: "#f7e6b1",
                QPalette.ToolTipText: "#171b20",
                QPalette.Text: "#f2f5f7",
                QPalette.Button: "#343c46",
                QPalette.ButtonText: "#f7f9fa",
                QPalette.BrightText: "#ff6b6b",
                QPalette.Link: "#79c0ff",
                QPalette.Highlight: "#276da8",
                QPalette.HighlightedText: "#ffffff",
                QPalette.PlaceholderText: "#a8b0ba",
            }
            disabled_text = QColor("#7e8791")
            disabled_button = QColor("#292f36")
        else:
            colors = {
                QPalette.Window: "#f2f4f7",
                QPalette.WindowText: "#17212b",
                QPalette.Base: "#ffffff",
                QPalette.AlternateBase: "#e9edf2",
                QPalette.ToolTipBase: "#fff4ce",
                QPalette.ToolTipText: "#392d00",
                QPalette.Text: "#17212b",
                QPalette.Button: "#f9fbfd",
                QPalette.ButtonText: "#17212b",
                QPalette.BrightText: "#b42318",
                QPalette.Link: "#005da8",
                QPalette.Highlight: "#0878c9",
                QPalette.HighlightedText: "#ffffff",
                QPalette.PlaceholderText: "#687482",
            }
            disabled_text = QColor("#87919c")
            disabled_button = QColor("#d9dee4")
        for role, value in colors.items():
            palette.setColor(role, QColor(value))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role, disabled_text)
        palette.setColor(QPalette.Disabled, QPalette.Button, disabled_button)
        palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor("#9aa3ad"))
        return palette

    def set_theme(self, mode: str) -> None:
        if mode not in {"automatic", "dark", "light"}:
            return
        self.theme_mode = mode
        self._apply_theme(persist=True)
        label = self.theme_actions[mode].text() if hasattr(self, "theme_actions") else mode.title()
        self.statusBar().showMessage(f"{self.trx('menu_appearance')}: {label}", 3000)

    def set_language(self, code: str) -> None:
        if code not in LANGUAGE_CODES:
            return
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        self.language_code = code
        self.settings.setValue("ui/language", code)
        QApplication.instance().setLayoutDirection(
            Qt.RightToLeft if code in RIGHT_TO_LEFT else Qt.LeftToRight
        )
        self._retranslate_ui()
        language = next(item for item in LANGUAGES if item.code == code)
        self.statusBar().showMessage(f"{self.trx('menu_language')}: {language.native_name}", 3000)

    def _retranslate_ui(self) -> None:
        menu_keys = {
            self.file_menu: "menu_file",
            self.recent_menu: "recent_files",
            self.edit_menu: "menu_edit",
            self.insert_menu: "menu_insert",
            self.page_menu: "menu_page",
            self.image_menu: "menu_image",
            self.comments_menu: "comments",
            self.forms_menu: "forms",
            self.view_menu: "menu_view",
            self.appearance_menu: "menu_appearance",
            self.language_menu: "menu_language",
            self.help_menu: "menu_help",
        }
        for menu, key in menu_keys.items():
            menu.setTitle(self.trx(key))

        action_keys = {
            self.new_action: "new_pdf",
            self.open_action: "open",
            self.close_document_action: "close_document",
            self.save_action: "save",
            self.save_as_action: "save_as",
            self.save_copy_action: "save_copy",
            self.print_action: "print",
            self.compress_action: "compress",
            self.compatibility_action: "document_compatibility",
            self.ocr_page_action: "ocr_page",
            self.ocr_document_action: "ocr_document",
            self.exit_action: "exit",
            self.undo_action: "undo",
            self.redo_action: "redo",
            self.find_action: "find",
            self.find_next_action: "find_next",
            self.find_previous_action: "find_previous",
            self.add_text_action: "add_text",
            self.delete_text_action: "delete_text",
            self.zoom_in_action: "zoom_in",
            self.zoom_out_action: "zoom_out",
            self.fit_width_action: "fit_width",
            self.add_blank_page_action: "add_blank_page",
            self.insert_pdf_action: "insert_pages",
            self.delete_page_action: "delete_page",
            self.move_page_up_action: "move_page_up",
            self.move_page_down_action: "move_page_down",
            self.rotate_page_left_action: "rotate_page_left",
            self.rotate_page_right_action: "rotate_page_right",
            self.add_image_action: "insert_image",
            self.edit_original_image_action: "edit_original_image",
            self.delete_image_action: "delete_image",
            self.signature_action: "add_signature",
            self.add_comment_action: "add_comment",
            self.edit_comment_action: "edit_comment",
            self.delete_comment_action: "delete_annotation",
            self.edit_form_action: "edit_form_field",
            self.create_form_action: "create_form_field",
            self.delete_form_action: "delete_form_field",
            self.redact_area_action: "redact_area",
            self.export_diagnostics_action: "export_diagnostics",
            self.check_for_updates_action: "check_for_updates",
            self.automatic_updates_action: "automatic_updates",
            self.about_action: "about",
        }
        for action, key in action_keys.items():
            action.setText(self.trx(key))
            action.setToolTip(self.trx(key))

        self.new_action.setToolTip(f"{self.trx('new_pdf')} (Ctrl+N)")
        self.close_document_action.setToolTip(
            f"{self.trx('close_document')} (Ctrl+W)"
        )
        self.find_action.setToolTip(f"{self.trx('find')} (Ctrl+F)")
        self.find_next_action.setToolTip(f"{self.trx('find_next')} (F3)")
        self.find_previous_action.setToolTip(
            f"{self.trx('find_previous')} (Shift+F3)"
        )
        self.print_action.setToolTip(f"{self.trx('print')} (Ctrl+P)")
        self.save_action.setToolTip(f"{self.trx('save')} (Ctrl+S)")
        self.save_as_action.setToolTip(f"{self.trx('save_as')} (Ctrl+Shift+S)")
        self.save_copy_action.setToolTip(f"{self.trx('save_copy')} (Ctrl+Alt+S)")
        self.undo_action.setToolTip(f"{self.trx('undo')} (Ctrl+Z)")
        self.redo_action.setToolTip(f"{self.trx('redo')} (Ctrl+Y)")
        self.theme_actions["automatic"].setText(self.trx("theme_auto"))
        self.theme_actions["dark"].setText(self.trx("theme_dark"))
        self.theme_actions["light"].setText(self.trx("theme_light"))
        self.zoom_combo.setToolTip(self.trx("current_zoom"))
        self.text_font_box.setToolTip(self.trx("font"))
        self.text_size_box.setToolTip(self.trx("font_size"))
        self.text_bold_button.setToolTip(self.trx("bold"))
        self.text_italic_button.setToolTip(self.trx("italic"))
        self.text_underline_button.setToolTip(self.trx("underline"))
        self.text_color_button.setToolTip(self.trx("text_color"))
        self.find_label.setText(self.trx("find_label"))
        self.find_edit.setPlaceholderText(self.trx("find_placeholder"))
        self.find_previous_button.setToolTip(self.trx("find_previous"))
        self.find_next_button.setToolTip(self.trx("find_next"))
        self.find_close_button.setToolTip(self.trx("close_search"))
        self._update_find_controls()
        self.sidebar_tabs.setTabText(self.pages_tab_index, self.trx("sidebar_pages"))
        self.sidebar_tabs.setTabText(self.outline_tab_index, self.trx("sidebar_tree"))
        self.right_sidebar.setTabText(self.comments_tool_index, self.trx("comments"))
        self.right_sidebar.setTabText(self.forms_tool_index, self.trx("forms"))
        self.right_sidebar.setTabText(
            self.fill_sign_tool_index, self.trx("fill_and_sign")
        )
        self.sidebar_tabs.setTabToolTip(
            self.outline_tab_index,
            "" if self._outline_model and self._outline_model.has_entries else self.trx("no_document_tree"),
        )
        self.right_sidebar.setTabToolTip(
            self.forms_tool_index,
            "" if self.forms_list.count() else self.trx("no_form_fields"),
        )
        self.right_sidebar.setTabToolTip(
            self.fill_sign_tool_index,
            "" if self.fill_forms_list.count() else self.trx("no_form_fields"),
        )
        self.add_comment_side_button.setText("+")
        self.add_comment_side_button.setToolTip(self.trx("add_comment"))
        self.edit_comment_side_button.setText("✎")
        self.edit_comment_side_button.setToolTip(self.trx("edit_comment"))
        self.delete_comment_side_button.setText("×")
        self.delete_comment_side_button.setToolTip(self.trx("delete_annotation"))
        self.create_form_side_button.setText("+")
        self.create_form_side_button.setToolTip(self.trx("create_form_field"))
        self.edit_form_side_button.setText("✎")
        self.edit_form_side_button.setToolTip(self.trx("edit_form_field"))
        self.delete_form_side_button.setText("×")
        self.delete_form_side_button.setToolTip(self.trx("delete_form_field"))
        self.form_edit_mode_button.setText(self.trx("form_edit_mode"))
        self.form_preview_mode_button.setText(self.trx("form_preview_mode"))
        self.reset_form_preview_button.setText(self.trx("reset_test_data"))
        self.fill_forms_hint.setText(self.trx("fill_form_hint"))
        self.clear_form_values_button.setText(self.trx("clear_form"))
        self.add_visual_signature_button.setText(self.trx("add_signature"))
        self.toolbar.setWindowTitle(self.trx("menu_file"))
        self.text_controls_widget.setToolTip(self.trx("font"))
        current_icon = language_icon(self.language_code)
        self.language_button.setIcon(current_icon)
        self.language_button.setToolTip(self.trx("menu_language"))
        self.language_menu.setIcon(current_icon)
        self.language_actions[self.language_code].setChecked(True)
        self._rebuild_recent_menu()
        for index in range(self.page_list.count()):
            self.page_list.item(index).setText(f"{self.trx('page_word')} {index + 1}")
        if self.engine.is_open:
            self._refresh_annotations_sidebar()
            self._refresh_forms_sidebar()
            self._render_current_page()
        else:
            self.status_label.setText(self.trx("open_to_begin"))

    def _apply_theme(self, persist: bool) -> None:
        self._effective_dark = self._theme_is_dark(self.theme_mode)
        app = QApplication.instance()
        app.setPalette(self._palette(self._effective_dark))
        if self._effective_dark:
            menu_styles = (
                "QMenuBar { background: #1d2228; color: #f5f7f9; border-bottom: 1px solid #3e4650; }"
                "QMenuBar::item { background: transparent; color: #f5f7f9; padding: 4px 8px; }"
                "QMenuBar::item:selected { background: #424a55; color: #ffffff; }"
                "QMenuBar::item:pressed { background: #8f5a00; color: #ffffff; }"
                "QMenu { background: #252b32; color: #f5f7f9; border: 1px solid #687380; }"
                "QMenu::item { color: #f5f7f9; padding: 5px 30px 5px 26px; }"
                "QMenu::item:selected { background: #8f5a00; color: #ffffff; }"
                "QMenu::item:disabled { color: #858f9a; }"
                "QMenu::separator { height: 1px; background: #59636e; margin: 4px 8px; }"
            )
            find_styles = (
                "QWidget#findBar { background: #2b3138; border-bottom: 1px solid #59636e; }"
                "QWidget#findBar QLabel { color: #f5f7f9; }"
                "QWidget#findBar QLineEdit { background: #ffffff; color: #111820; "
                "border: 2px solid #788594; border-radius: 4px; padding: 3px 6px; }"
                "QWidget#findBar QToolButton { background: #3b424c; color: #ffffff; "
                "border: 1px solid #707b88; border-radius: 4px; }"
                "QWidget#findBar QToolButton:hover { background: #9b6200; "
                "border-color: #ffd166; }"
                "QWidget#findBar QToolButton:disabled { background: #292e35; "
                "border-color: #3a414a; }"
            )
        else:
            menu_styles = (
                "QMenuBar { background: #f3f5f7; color: #111820; border-bottom: 1px solid #aeb7c1; }"
                "QMenuBar::item { background: transparent; color: #111820; padding: 4px 8px; }"
                "QMenuBar::item:selected { background: #c7e5f8; color: #0d1821; }"
                "QMenuBar::item:pressed { background: #a8d5f2; color: #0a141c; }"
                "QMenu { background: #ffffff; color: #111820; border: 1px solid #8995a2; }"
                "QMenu::item { color: #111820; padding: 5px 30px 5px 26px; }"
                "QMenu::item:selected { background: #c7e5f8; color: #0d1821; }"
                "QMenu::item:disabled { color: #7c8792; }"
                "QMenu::separator { height: 1px; background: #c2c9d1; margin: 4px 8px; }"
            )
            find_styles = (
                "QWidget#findBar { background: #e7ebf0; border-bottom: 1px solid #aab3bd; }"
                "QWidget#findBar QLabel { color: #111820; }"
                "QWidget#findBar QLineEdit { background: #ffffff; color: #111820; "
                "border: 2px solid #65717e; border-radius: 4px; padding: 3px 6px; }"
                "QWidget#findBar QToolButton { background: #ffffff; color: #17212b; "
                "border: 1px solid #74808d; border-radius: 4px; }"
                "QWidget#findBar QToolButton:hover { background: #ffe3a3; "
                "border-color: #8a5200; }"
                "QWidget#findBar QToolButton:disabled { background: #d2d8df; "
                "border-color: #aeb7c1; }"
            )
        if self._effective_dark:
            right_sidebar_styles = (
                "QWidget#rightToolSidebar, QWidget#rightToolRail { background: #252b32; "
                "border-left: 1px solid #59636e; }"
                "QLabel#rightToolTitle { padding: 4px; color: #f2f5f7; }"
                "QToolButton#rightToolButton, QToolButton#rightToolClose { background: transparent; "
                "border: 1px solid transparent; border-radius: 4px; padding: 4px; }"
                "QToolButton#rightToolButton:hover, QToolButton#rightToolButton:checked, "
                "QToolButton#rightToolClose:hover { background: #3b424c; border-color: #707b88; }"
            )
        else:
            right_sidebar_styles = (
                "QWidget#rightToolSidebar, QWidget#rightToolRail { background: #edf1f5; "
                "border-left: 1px solid #aab3bd; }"
                "QLabel#rightToolTitle { padding: 4px; color: #17212b; }"
                "QToolButton#rightToolButton, QToolButton#rightToolClose { background: transparent; "
                "border: 1px solid transparent; border-radius: 4px; padding: 4px; }"
                "QToolButton#rightToolButton:hover, QToolButton#rightToolButton:checked, "
                "QToolButton#rightToolClose:hover { background: #c7e5f8; border-color: #74808d; }"
            )
        app.setStyleSheet(
            menu_styles
            + find_styles
            + right_sidebar_styles
            + "QToolTip { background: #fff4ce; color: #392d00; border: 1px solid #b69122; padding: 4px; }"
        )
        if persist:
            self.settings.setValue("appearance/theme", self.theme_mode)
        if hasattr(self, "theme_actions"):
            self.theme_actions[self.theme_mode].setChecked(True)
        if hasattr(self, "toolbar"):
            self._style_toolbar()
        if hasattr(self, "undo_action"):
            self._refresh_action_icons()
        self.page_view.set_theme(self._effective_dark)

    def _system_theme_changed(self, *args) -> None:
        if self.theme_mode == "automatic":
            self._apply_theme(persist=False)

    def _style_toolbar(self) -> None:
        if not hasattr(self, "toolbar"):
            return
        if self._effective_dark:
            stylesheet = (
                "QToolBar#mainToolbar { background: #20242a; border: 0; spacing: 2px; padding: 4px; }"
                "QToolBar#mainToolbar QToolButton { background: #3b424c; border: 1px solid #707b88; "
                "border-radius: 4px; padding: 2px; margin: 1px; }"
                "QToolBar#mainToolbar QToolButton:hover { background: #9b6200; border-color: #ffd166; }"
                "QToolBar#mainToolbar QToolButton:pressed { background: #ce8300; }"
                "QToolBar#mainToolbar QToolButton:disabled { background: #292e35; border-color: #3a414a; }"
                "QToolBar#mainToolbar QComboBox { background: #ffffff; color: #101317; border: 2px solid #788594; "
                "border-radius: 4px; padding: 4px 6px; min-height: 24px; }"
                "QToolBar#mainToolbar QToolButton#textStyleButton:checked { background: #9b6200; "
                "border-color: #ffd166; color: #ffffff; }"
                "QToolBar#mainToolbar QToolBarSeparator { background: #65707c; width: 1px; margin: 4px 1px; }"
            )
        else:
            stylesheet = (
                "QToolBar#mainToolbar { background: #dfe4ea; border-bottom: 1px solid #aab3bd; "
                "spacing: 2px; padding: 4px; }"
                "QToolBar#mainToolbar QToolButton { background: #ffffff; border: 1px solid #74808d; "
                "border-radius: 4px; padding: 2px; margin: 1px; }"
                "QToolBar#mainToolbar QToolButton:hover { background: #ffe3a3; border-color: #8a5200; }"
                "QToolBar#mainToolbar QToolButton:pressed { background: #ffc95c; border-color: #6f4200; }"
                "QToolBar#mainToolbar QToolButton:disabled { background: #d2d8df; border-color: #aeb7c1; }"
                "QToolBar#mainToolbar QComboBox { background: #ffffff; color: #17212b; border: 2px solid #65717e; "
                "border-radius: 4px; padding: 4px 6px; min-height: 24px; }"
                "QToolBar#mainToolbar QToolButton#textStyleButton:checked { background: #b9def5; "
                "border-color: #0067b8; color: #10202d; }"
                "QToolBar#mainToolbar QToolBarSeparator { background: #8d98a4; width: 1px; margin: 4px 1px; }"
            )
        stylesheet += (
            "QToolBar#mainToolbar QWidget#textControls { background: transparent; }"
            "QToolBar#mainToolbar QWidget#textControls QComboBox { min-height: 0; padding: 2px 4px; }"
            "QToolBar#mainToolbar QWidget#textControls QToolButton { padding: 1px; margin: 0; }"
            "QToolBar#mainToolbar QComboBox QAbstractItemView { background: #ffffff; color: #111820; "
            "selection-background-color: #176fa6; selection-color: #ffffff; border: 1px solid #65717e; }"
            "QToolBar#mainToolbar QComboBox QAbstractItemView::item { color: #111820; "
            "background: #ffffff; min-height: 24px; }"
            "QToolBar#mainToolbar QComboBox QAbstractItemView::item:selected { color: #ffffff; "
            "background: #176fa6; }"
        )
        self.toolbar.setStyleSheet(stylesheet)
        if hasattr(self, "text_font_box"):
            for popup in (self.text_font_box.view(), self.text_size_box.view()):
                popup_palette = popup.palette()
                for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
                    popup_palette.setColor(group, QPalette.Base, QColor("#ffffff"))
                    popup_palette.setColor(group, QPalette.Text, QColor("#111820"))
                    popup_palette.setColor(group, QPalette.WindowText, QColor("#111820"))
                    popup_palette.setColor(group, QPalette.Highlight, QColor("#176fa6"))
                    popup_palette.setColor(group, QPalette.HighlightedText, QColor("#ffffff"))
                popup.setPalette(popup_palette)
            self._refresh_text_color_button()

    def _refresh_action_icons(self) -> None:
        custom_icons = {
            self.print_action: "print.svg",
            self.compress_action: "compress.svg",
            self.undo_action: "undo.svg",
            self.redo_action: "redo.svg",
            self.zoom_in_action: "zoom_in.svg",
            self.zoom_out_action: "zoom_out.svg",
            self.fit_width_action: "fit_width.svg",
            self.add_blank_page_action: "page_add.svg",
            self.insert_pdf_action: "pages_import.svg",
            self.delete_page_action: "page_remove.svg",
            self.add_image_action: "image_add.svg",
            self.delete_image_action: "image_remove.svg",
            self.signature_action: "signature.svg",
            self.add_text_action: "text_add.svg",
            self.delete_text_action: "text_remove.svg",
        }
        for action, name in custom_icons.items():
            action.setIcon(self._asset_icon(name))
        self.open_action.setIcon(self._asset_icon("file_open.svg"))
        self.close_document_action.setIcon(self._asset_icon("file_close.svg"))
        self.save_action.setIcon(self._asset_icon("file_save.svg"))
        self.save_as_action.setIcon(self._asset_icon("file_save_as.svg"))
        self.save_copy_action.setIcon(self._asset_icon("file_copy.svg"))
        self.new_action.setIcon(self._asset_icon("file_new.svg"))

    @property
    def has_unsaved_changes(self) -> bool:
        return self._document_session.has_unsaved_changes(
            is_open=self.engine.is_open,
            history_index=self.history_index,
        )

    def _update_window_title(self) -> None:
        if not self.engine.is_open:
            self.setWindowTitle(APP_NAME)
            return
        name = self.document_path.name if self.document_path else self.trx("untitled")
        marker = " *" if self.has_unsaved_changes else ""
        self.setWindowTitle(f"{APP_NAME} - {name}{marker}")

    def _maybe_save_changes(self) -> bool:
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        if not self.has_unsaved_changes:
            return True
        name = self.document_path.name if self.document_path else self.trx("untitled")
        prompt = QMessageBox(QMessageBox.Warning, self.trx("unsaved_title"), self.trx("unsaved_question", name=name), parent=self)
        prompt.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        prompt.setDefaultButton(QMessageBox.Save)
        prompt.button(QMessageBox.Save).setText(self.trx("save"))
        prompt.button(QMessageBox.Discard).setText(self.trx("discard"))
        prompt.button(QMessageBox.Cancel).setText(self.trx("cancel"))
        answer = prompt.exec()
        if answer == QMessageBox.Save:
            # A document switch or application close may proceed only after
            # the requested save has actually completed.
            return self.save_document(
                show_confirmation=False,
                background=False,
            )
        return answer == QMessageBox.Discard

    def _activate_document(
        self,
        engine: PdfEngine,
        document_path: Path | None,
        already_saved: bool,
        initial_state: EditorState | None = None,
        initial_page: int = 0,
        initial_scale: float = 1.0,
        save_target_path: Path | None = None,
        preserve_recovery: bool = False,
    ) -> None:
        self._cancel_document_inspection()
        self._cancel_tile_render(clear_cache=True)
        self._clear_tile_render_source()
        if not preserve_recovery:
            self._clear_recovery(wait=True)
        self._cancel_thumbnail_loading()
        self._clear_outline_tree()
        self._reset_find_state(clear_query=True, hide=True)
        self.page_view.clear_page()
        self.engine.close()
        self.engine = engine
        self._prepare_tile_render_source()
        self._document_session.activate(
            document_path,
            save_target_path=save_target_path,
            already_saved=already_saved,
        )
        self.cancel_special_mode()
        self.page_view.selected_signature_key = None
        self.page_view.selected_visual_ref = None
        self.page_view.selected_text_ref = None
        self._clear_text_toolbar_target()
        self.current_page = min(max(0, initial_page), max(0, engine.page_count - 1))
        self.render_scale = min(4.0, max(0.25, float(initial_scale)))
        if initial_state is None:
            self.edits = {}
            self.inserted_texts = []
            self.signatures = []
            self.inserted_images = []
            self.deleted_images = []
        else:
            self.edits = copy.deepcopy(initial_state.edits)
            self.inserted_texts = copy.deepcopy(initial_state.inserted_texts)
            self.signatures = copy.deepcopy(initial_state.signatures)
            self.inserted_images = copy.deepcopy(initial_state.inserted_images)
            self.deleted_images = copy.deepcopy(initial_state.deleted_images)
        self.history = [self._capture_state()]
        self.history_index = 0
        self._sync_zoom_display()
        self._load_thumbnails(self.current_page)
        self._load_outline_tree(select_tree=True)
        self._refresh_annotations_sidebar()
        self._form_preview_values.clear()
        self._refresh_forms_sidebar()
        self._select_and_render_page(self.current_page)
        self._update_window_title()
        self._update_actions()
        self._sync_recovery_to_state()
        self._start_document_inspection()
        self._operation_log.record(
            "document_opened",
            operation="new" if document_path is None else "open",
            outcome="succeeded",
            page_count=engine.page_count,
            file_size_bucket=file_size_bucket(len(engine.source_bytes)),
            encrypted=bool(engine.was_encrypted),
            restored=initial_state is not None,
            document_generation=self._document_generation,
        )

    def new_document(self) -> None:
        if self._document_write_in_progress():
            return
        dialog = NewDocumentDialog(self, self.trx)
        if not dialog.exec():
            return
        if not self._maybe_save_changes():
            return
        width, height, page_count = dialog.document_settings()
        candidate = PdfEngine()
        try:
            candidate.load_bytes(PdfEngine.blank_document_bytes(width, height, page_count))
        except Exception as exc:
            candidate.close()
            QMessageBox.critical(self, self.trx("unable_create_title"), str(exc))
            return
        self._activate_document(candidate, None, already_saved=False)
        self.statusBar().showMessage(
            self.trx("new_created", count=page_count, width=width, height=height),
            6000,
        )

    def open_dialog(self) -> None:
        if self._document_write_in_progress():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.trx("open_pdf_title"),
            "",
            self.trx("pdf_filter"),
        )
        if path:
            self.open_pdf(path)

    def open_pdf(self, path: str) -> bool:
        if self._document_write_in_progress():
            return False
        source_path = self._normalized_file_path(path)
        candidate = PdfEngine()
        password: str | None = None
        password_prompt = self.trx("pdf_password_prompt")
        while True:
            try:
                candidate.open(source_path, password=password)
                break
            except PdfPasswordRequiredError:
                pass
            except PdfInvalidPasswordError:
                password_prompt = self.trx("pdf_password_incorrect")
            except Exception as exc:
                candidate.close()
                QMessageBox.critical(self, self.trx("unable_open_title"), str(exc))
                return False
            password, accepted = QInputDialog.getText(
                self,
                self.trx("pdf_password_title"),
                password_prompt,
                QLineEdit.Password,
            )
            if not accepted:
                candidate.close()
                return False
        if not self._maybe_save_changes():
            candidate.close()
            return False
        was_encrypted = candidate.was_encrypted
        self._activate_document(candidate, source_path, already_saved=True)
        self._add_recent_file(source_path)
        if was_encrypted:
            self.statusBar().showMessage(self.trx("pdf_password_removed_notice"), 9000)
        return True

    def close_document(self) -> bool:
        if self._document_write_in_progress():
            return False
        if not self.engine.is_open:
            return True
        if not self._maybe_save_changes():
            return False
        self._operation_log.record(
            "document_closed",
            outcome="succeeded",
            page_count=self.engine.page_count,
            history_index=self.history_index,
            content_revision=self._content_revision,
        )
        self._clear_recovery(wait=True)
        self._cancel_document_inspection()
        self._cancel_thumbnail_loading()
        self._clear_outline_tree()
        self._cancel_tile_render(clear_cache=True)
        self._clear_tile_render_source()
        self.cancel_special_mode()
        self._reset_find_state(clear_query=True, hide=True)
        self.page_view.clear_page()
        self.engine.close()
        self._document_session.close()
        self.current_page = 0
        self.render_scale = 1.0
        self.edits = {}
        self.inserted_texts = []
        self.signatures = []
        self.inserted_images = []
        self.deleted_images = []
        self.history = []
        self.history_index = -1
        self.page_list.clear()
        self.comments_list.clear()
        self.forms_list.clear()
        self.fill_forms_list.clear()
        self._form_preview_values.clear()
        self._form_workspace_mode = "none"
        self.right_sidebar.setTabEnabled(self.comments_tool_index, False)
        self.right_sidebar.setTabEnabled(self.forms_tool_index, False)
        self.right_sidebar.setTabEnabled(self.fill_sign_tool_index, False)
        self.right_sidebar.collapse()
        self._clear_text_toolbar_target()
        self._sync_zoom_display()
        self.status_label.setText(self.trx("open_to_begin"))
        self._update_window_title()
        self._update_actions()
        self.statusBar().showMessage(self.trx("document_closed"), 3000)
        return True

    def _start_document_inspection(self) -> None:
        self._cancel_document_inspection()
        if not self.engine.is_open:
            return
        self._inspection_report = None
        self._inspection_error = None
        self._compatibility_risk_acknowledged = False
        try:
            self._inspection_coordinator.start(
                self.engine.source_bytes,
                encrypted_source=self.engine.was_encrypted,
                context=InspectionContext(self._document_generation),
            )
        except Exception as exc:
            self._inspection_error = str(exc)
            self.statusBar().showMessage(
                self.trx("compatibility_failed", error=exc), 7000
            )
            self._update_actions()
            return
        self.statusBar().showMessage(self.trx("compatibility_checking"))
        self._update_actions()

    def _cancel_document_inspection(self) -> None:
        self._inspection_coordinator.cancel()
        if hasattr(self, "save_action"):
            self._update_actions()

    def _inspection_finished(
        self,
        outcome: InspectionOutcome,
    ) -> None:
        if outcome.context.document_generation != self._document_generation:
            return
        if not self.engine.is_open:
            return
        self._inspection_report = outcome.report
        self._inspection_error = outcome.error
        self._operation_log.record(
            "inspection_finished",
            worker="inspection",
            outcome="succeeded" if outcome.report is not None else "failed",
            reason=error_reason(outcome.error) if outcome.report is None else "unknown",
            warning_count=(
                len(outcome.report.warning_codes) if outcome.report is not None else 0
            ),
            document_generation=outcome.context.document_generation,
        )
        if outcome.report is not None:
            warning_count = len(outcome.report.warning_codes)
            message = (
                self.trx("compatibility_warnings", count=warning_count)
                if warning_count
                else self.trx("compatibility_ok")
            )
            self.statusBar().showMessage(message, 8000)
        else:
            self.statusBar().showMessage(
                self.trx(
                    "compatibility_failed",
                    error=outcome.error or "unknown error",
                ),
                8000,
            )
        self._update_actions()

    def show_document_compatibility(self) -> None:
        if not self.engine.is_open:
            return
        title = self.trx("document_compatibility").rstrip(".")
        if self._inspection_process is not None:
            QMessageBox.information(self, title, self.trx("compatibility_checking"))
            return
        report = self._inspection_report
        if report is None:
            QMessageBox.warning(
                self,
                title,
                self.trx(
                    "compatibility_failed",
                    error=self._inspection_error or "unknown error",
                ),
            )
            return
        warning_codes = report.warning_codes
        level_key = f"compatibility_level_{report.compatibility_level}"
        level_icon = {
            "safe": "🟢",
            "possible_changes": "🟡",
            "high_risk": "🔴",
        }[report.compatibility_level]
        lines = [
            f"{level_icon} {self.trx(level_key)}",
            "",
            f"{report.pdf_format} — {self.trx('pages_count', count=report.page_count)}",
            self.trx(
                "representative_render_ok",
                count=report.representative_pages_rendered,
            ),
        ]
        if warning_codes:
            lines.append("")
            lines.append(self.trx("compatibility_warnings", count=len(warning_codes)))
            labels = [code.replace("_", " ") for code in warning_codes]
            lines.append(self.trx("compatibility_features", features=", ".join(labels)))
            if report.signed_digital_signatures:
                lines.append(self.trx("compatibility_signature_risk"))
            QMessageBox.warning(self, title, "\n".join(lines))
        else:
            lines.extend(("", self.trx("compatibility_ok")))
            QMessageBox.information(self, title, "\n".join(lines))

    def show_find_bar(self) -> None:
        if not self.engine.is_open:
            return
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        self.cancel_special_mode()
        self.find_bar.show()
        query = self.find_edit.text().strip()
        if query and (query != self._search_query or not self.search_matches):
            self._search_timer.stop()
            self._run_search()
        else:
            self._restore_search_highlight()
        self.find_edit.setFocus(Qt.ShortcutFocusReason)
        self.find_edit.selectAll()

    def hide_find_bar(self) -> None:
        self._search_timer.stop()
        self._cancel_search_task()
        self.find_bar.hide()
        self.page_view.set_search_highlight(None)
        self.page_view.setFocus(Qt.ShortcutFocusReason)

    def _cancel_search_task(self) -> None:
        self._search_generation += 1
        if self._search_task is not None:
            self._search_task.cancel()
            self._search_task = None
        if self._search_cursor_active:
            QApplication.restoreOverrideCursor()
            self._search_cursor_active = False

    def _reset_find_state(self, clear_query: bool, hide: bool = False) -> None:
        self._search_timer.stop()
        self._cancel_search_task()
        self.search_matches = []
        self.search_index = -1
        self._search_query = ""
        if clear_query:
            self.find_edit.blockSignals(True)
            self.find_edit.clear()
            self.find_edit.blockSignals(False)
        self.find_result_label.setText("0 / 0")
        self.find_result_label.setToolTip("")
        self.find_previous_button.setEnabled(False)
        self.find_next_button.setEnabled(False)
        self.page_view.set_search_highlight(None)
        if hide:
            self.find_bar.hide()

    def _queue_search(self, *_args) -> None:
        self._cancel_search_task()
        self._search_query = ""
        self.search_matches = []
        self.search_index = -1
        self.page_view.set_search_highlight(None)
        self._update_find_controls()
        self._search_timer.start()

    def _run_search(self) -> None:
        query = self.find_edit.text().strip()
        self._cancel_search_task()
        self._search_query = query
        self.search_matches = []
        self.search_index = -1
        self.page_view.set_search_highlight(None)
        if not query or not self.engine.is_open:
            self._update_find_controls()
            return

        self._search_generation += 1
        request_id = self._search_generation
        task = SearchTask(
            request_id,
            self.engine.source_bytes,
            query,
            tuple(self.edits.values()),
            tuple(self.signatures),
            tuple(self.inserted_images),
            tuple(self.deleted_images),
            tuple(self.inserted_texts),
        )
        task.signals.finished.connect(self._search_finished)
        task.signals.failed.connect(self._search_failed)
        self._search_task = task
        if not self._search_cursor_active:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._search_cursor_active = True
        self._update_find_controls()
        self._search_pool.start(task)

    def _search_finished(self, request_id: int, raw_matches: object) -> None:
        if request_id != self._search_generation:
            return
        self._search_task = None
        if self._search_cursor_active:
            QApplication.restoreOverrideCursor()
            self._search_cursor_active = False
        self.search_matches = [
            SearchMatch(page_index, tuple(bbox))
            for page_index, bbox in list(raw_matches or [])
        ]
        self.search_index = -1
        if self.search_matches:
            self.search_index = next(
                (
                    index
                    for index, match in enumerate(self.search_matches)
                    if match.page_index >= self.current_page
                ),
                0,
            )
            self._show_search_match()
        else:
            self.statusBar().showMessage(self.trx("find_no_results"), 3000)
            self._update_find_controls()

    def _search_failed(self, request_id: int, message: str) -> None:
        if request_id != self._search_generation:
            return
        self._search_task = None
        if self._search_cursor_active:
            QApplication.restoreOverrideCursor()
            self._search_cursor_active = False
        self.search_matches = []
        self.search_index = -1
        self.statusBar().showMessage(message, 5000)
        self._update_find_controls()

    def _update_find_controls(self) -> None:
        has_matches = bool(self.search_matches)
        searching = self._search_task is not None
        if has_matches and 0 <= self.search_index < len(self.search_matches):
            self.find_result_label.setText(
                f"{self.search_index + 1} / {len(self.search_matches)}"
            )
            self.find_result_label.setToolTip("")
        else:
            self.find_result_label.setText("0 / 0")
            self.find_result_label.setToolTip(
                self.trx("find_no_results") if self._search_query else ""
            )
        self.find_previous_button.setEnabled(has_matches and not searching)
        self.find_next_button.setEnabled(has_matches and not searching)
        if hasattr(self, "find_next_action"):
            self.find_next_action.setEnabled(self.engine.is_open and has_matches and not searching)
            self.find_previous_action.setEnabled(self.engine.is_open and has_matches and not searching)

    def _restore_search_highlight(self) -> None:
        match = (
            self.search_matches[self.search_index]
            if 0 <= self.search_index < len(self.search_matches)
            else None
        )
        if (
            self.find_bar.isVisible()
            and match is not None
            and match.page_index == self.current_page
        ):
            self.page_view.set_search_highlight(match.bbox)
        else:
            self.page_view.set_search_highlight(None)

    def _show_search_match(self) -> None:
        if not (0 <= self.search_index < len(self.search_matches)):
            self._update_find_controls()
            return
        match = self.search_matches[self.search_index]
        self._update_find_controls()
        if self.current_page != match.page_index:
            self._select_and_render_page(match.page_index)
        else:
            self.page_view.set_search_highlight(match.bbox)
        self.statusBar().showMessage(
            f"{self.trx('find_label')} {self._search_query} "
            f"({self.search_index + 1}/{len(self.search_matches)})",
            3000,
        )

    def find_next(self) -> None:
        if not self.find_bar.isVisible():
            self.show_find_bar()
        query = self.find_edit.text().strip()
        if not query:
            return
        if self._search_timer.isActive() or query != self._search_query:
            self._search_timer.stop()
            self._run_search()
            return
        if not self.search_matches:
            self._run_search()
            return
        self.search_index = (self.search_index + 1) % len(self.search_matches)
        self._show_search_match()

    def find_previous(self) -> None:
        if not self.find_bar.isVisible():
            self.show_find_bar()
        query = self.find_edit.text().strip()
        if not query:
            return
        if self._search_timer.isActive() or query != self._search_query:
            self._search_timer.stop()
            self._run_search()
            return
        if not self.search_matches:
            self._run_search()
            return
        self.search_index = (self.search_index - 1) % len(self.search_matches)
        self._show_search_match()

    def _capture_state(self) -> EditorState:
        return EditorState(
            pdf_bytes=self.engine.source_bytes,
            edits=copy.deepcopy(self.edits),
            inserted_texts=copy.deepcopy(self.inserted_texts),
            signatures=copy.deepcopy(self.signatures),
            inserted_images=copy.deepcopy(self.inserted_images),
            deleted_images=copy.deepcopy(self.deleted_images),
        )

    def _clear_outline_tree(self) -> None:
        self.outline_tree.setModel(None)
        if self._outline_model is not None:
            self._outline_model.deleteLater()
        self._outline_model = None
        self.sidebar_tabs.setTabEnabled(self.outline_tab_index, False)
        if self.sidebar_tabs.currentIndex() == self.outline_tab_index:
            self.sidebar_tabs.setCurrentIndex(self.pages_tab_index)

    def _load_outline_tree(self, select_tree: bool) -> None:
        try:
            model = PdfOutlineModel(self.engine, self.outline_tree)
        except Exception:
            self._clear_outline_tree()
            return
        self._outline_model = model
        self.outline_tree.setModel(model)
        self.sidebar_tabs.setTabEnabled(self.outline_tab_index, model.has_entries)
        self.sidebar_tabs.setTabToolTip(
            self.outline_tab_index,
            "" if model.has_entries else self.trx("no_document_tree"),
        )
        if select_tree and model.has_entries:
            self.sidebar_tabs.setCurrentIndex(self.outline_tab_index)
        elif not model.has_entries:
            self.sidebar_tabs.setCurrentIndex(self.pages_tab_index)

    def _outline_clicked(self, index: QModelIndex) -> None:
        model = self._outline_model
        if model is None:
            return
        entry = model.entry_for_index(index)
        if entry is None or entry.page_index is None:
            return
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        self.cancel_special_mode()
        if entry.target_rect is not None:
            x0, y0, x1, y1 = entry.target_rect
            target_width = max(1.0, x1 - x0)
            target_height = max(1.0, y1 - y0)
            available_width = max(100, self.page_view.viewport().width() - 80)
            available_height = max(100, self.page_view.viewport().height() - 80)
            self.render_scale = min(
                4.0,
                max(
                    0.25,
                    min(available_width / target_width, available_height / target_height),
                ),
            )
        self._select_and_render_page(entry.page_index)
        if entry.target_rect is not None:
            self.page_view.center_on_pdf_rect(entry.target_rect)

    def _refresh_annotations_sidebar(self) -> None:
        self.comments_list.clear()
        self.right_sidebar.setTabEnabled(
            self.comments_tool_index,
            self.engine.is_open,
        )
        if not self.engine.is_open:
            return
        try:
            annotations = self.engine.annotations()
        except Exception:
            return
        for annotation in annotations:
            content = " ".join(annotation.content.split())
            summary = content[:72] + ("…" if len(content) > 72 else "")
            if not summary:
                summary = self.trx("annotation_without_comment")
            item = QListWidgetItem(
                f"{self.trx('page_word')} {annotation.page_index + 1} · "
                f"{annotation.type_name}\n{summary}"
            )
            item.setData(Qt.UserRole, annotation.xref)
            item.setToolTip(annotation.content or annotation.type_name)
            self.comments_list.addItem(item)

    def _annotation_for_item(self, item: QListWidgetItem | None) -> AnnotationInfo | None:
        if item is None or not self.engine.is_open:
            return None
        try:
            xref = int(item.data(Qt.UserRole))
        except (TypeError, ValueError):
            return None
        return next(
            (annotation for annotation in self.engine.annotations() if annotation.xref == xref),
            None,
        )

    def _comment_item_activated(self, item: QListWidgetItem) -> None:
        annotation = self._annotation_for_item(item)
        if annotation is None:
            return
        if self.current_page != annotation.page_index:
            self._select_and_render_page(annotation.page_index)
        self.page_view.center_on_pdf_rect(annotation.bbox)

    def _show_comment_context_menu(self, position) -> None:
        item = self.comments_list.itemAt(position)
        if item is None:
            return
        self.comments_list.setCurrentItem(item)
        menu = QMenu(self)
        edit = menu.addAction(self.trx("edit_comment"))
        edit.triggered.connect(self.edit_selected_comment)
        delete = menu.addAction(self.trx("delete_annotation"))
        delete.triggered.connect(self.delete_selected_annotation)
        self._exec_context_menu(menu, self.comments_list.mapToGlobal(position))

    @staticmethod
    def _form_field_summary(field: FormFieldInfo) -> str:
        if field.type_code == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
            return "signed" if field.value else "unsigned"
        if field.type_code in (
            pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
            pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
        ):
            return "checked" if field.checked else "unchecked"
        return " ".join(field.value.split())

    def _refresh_forms_sidebar(self) -> None:
        self.forms_list.clear()
        self.fill_forms_list.clear()
        fields: list[FormFieldInfo] = []
        if self.engine.is_open:
            try:
                fields = self.engine.form_fields()
            except Exception:
                fields = []
        for field in fields:
            name = field.label.strip() or field.name.strip() or self.trx("unnamed_form_field")
            summary = self._form_field_summary(field)
            if summary == "checked":
                summary = self.trx("form_checked")
            elif summary == "unchecked":
                summary = self.trx("form_unchecked")
            elif summary == "signed":
                summary = self.trx("form_signed")
            elif summary == "unsigned":
                summary = self.trx("form_unsigned")
            if not summary:
                summary = self.trx("form_empty")
            read_only = f" · {self.trx('form_read_only')}" if field.read_only else ""
            item = QListWidgetItem(
                f"{self.trx('page_word')} {field.page_index + 1} · "
                f"{name}\n{field.type_name}{read_only} · {summary}"
            )
            item.setData(Qt.UserRole, field.xref)
            item.setToolTip(field.name or name)
            self.forms_list.addItem(item)
            fill_item = QListWidgetItem(item.text())
            fill_item.setData(Qt.UserRole, field.xref)
            fill_item.setToolTip(item.toolTip())
            self.fill_forms_list.addItem(fill_item)
        self.right_sidebar.setTabEnabled(
            self.forms_tool_index,
            self.engine.is_open,
        )
        self.right_sidebar.setTabToolTip(
            self.forms_tool_index,
            "" if fields else self.trx("no_form_fields"),
        )
        self.right_sidebar.setTabEnabled(
            self.fill_sign_tool_index,
            self.engine.is_open,
        )
        self.right_sidebar.setTabToolTip(
            self.fill_sign_tool_index,
            "" if fields else self.trx("no_form_fields"),
        )

    def _right_tool_changed(self, index: int) -> None:
        if index == self.forms_tool_index:
            mode = "preview" if self.form_preview_mode_button.isChecked() else "edit"
            self._set_form_workspace_mode(mode)
        elif index == self.fill_sign_tool_index:
            self._set_form_workspace_mode("fill")
        else:
            self._set_form_workspace_mode("none")

    def _right_tools_collapsed(self) -> None:
        self._set_form_workspace_mode("none")

    def _set_form_workspace_mode(self, mode: str) -> None:
        if mode not in {"none", "edit", "preview", "fill"}:
            raise ValueError("Unknown form workspace mode.")
        if not self.engine.is_open:
            mode = "none"
        if mode != "preview" and self._form_workspace_mode == "preview":
            self._form_preview_values.clear()
        self._form_workspace_mode = mode
        self.form_edit_mode_button.setChecked(mode != "preview")
        self.form_preview_mode_button.setChecked(mode == "preview")
        self.reset_form_preview_button.setEnabled(mode == "preview")
        self.reset_form_preview_button.setVisible(mode == "preview")
        if self.engine.is_open:
            self._render_current_page()
        self._update_actions()

    def reset_form_preview(self) -> None:
        self._form_preview_values.clear()
        if self._form_workspace_mode == "preview" and self.engine.is_open:
            self._render_current_page()
            self.statusBar().showMessage(self.trx("form_preview_reset"), 3500)

    def _form_field_for_item(self, item: QListWidgetItem | None) -> FormFieldInfo | None:
        if item is None or not self.engine.is_open:
            return None
        try:
            xref = int(item.data(Qt.UserRole))
        except (TypeError, ValueError):
            return None
        return next(
            (field for field in self.engine.form_fields() if field.xref == xref),
            None,
        )

    @staticmethod
    def _matching_form_xref(engine: PdfEngine, original: FormFieldInfo) -> int:
        """Resolve a widget after composition, which may renumber PDF xrefs."""

        candidates = [
            field
            for field in engine.form_fields()
            if field.page_index == original.page_index
            and field.name == original.name
            and field.type_code == original.type_code
        ]
        if not candidates:
            raise ValueError("The form field is no longer available.")
        return min(
            candidates,
            key=lambda field: sum(
                abs(left - right) for left, right in zip(field.bbox, original.bbox)
            ),
        ).xref

    def _form_item_selected(self, item: QListWidgetItem) -> None:
        field = self._form_field_for_item(item)
        if field is None:
            return
        if self.current_page != field.page_index:
            self._select_and_render_page(field.page_index)
        self.page_view.center_on_pdf_rect(field.bbox)

    def _show_form_context_menu(self, position) -> None:
        item = self.forms_list.itemAt(position)
        if item is None:
            return
        self.forms_list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction(self.edit_form_action)
        menu.addAction(self.delete_form_action)
        self._exec_context_menu(menu, self.forms_list.mapToGlobal(position))

    def _thumbnail_placeholder_icon(self) -> QIcon:
        pixmap = QPixmap(100, 132)
        pixmap.fill(QColor("#f7f7f7"))
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor("#a8adb3"), 1))
        painter.drawRect(0, 0, pixmap.width() - 1, pixmap.height() - 1)
        painter.end()
        return QIcon(pixmap)

    def _thumbnail_rows_about_to_move(
        self,
        _source_parent: QModelIndex,
        source_start: int,
        source_end: int,
        _destination_parent: QModelIndex,
        destination_row: int,
    ) -> None:
        self._thumbnail_reorder_context = None
        if (
            self._thumbnail_reorder_pending
            or not self.engine.is_open
            or source_start != source_end
        ):
            return
        target = destination_row - 1 if destination_row > source_start else destination_row
        if not 0 <= target < self.engine.page_count or target == source_start:
            return
        self._thumbnail_reorder_context = (source_start, target)
        # QListWidget briefly changes its current row while completing an
        # internal move. Keep navigation stable until the PDF page tree and all
        # pending editor objects have been remapped together.
        self.page_list.blockSignals(True)

    def _thumbnail_rows_moved(
        self,
        _source_parent: QModelIndex,
        _source_start: int,
        _source_end: int,
        _destination_parent: QModelIndex,
        _destination_row: int,
    ) -> None:
        context = self._thumbnail_reorder_context
        self._thumbnail_reorder_context = None
        self.page_list.blockSignals(False)
        if context is None:
            return
        self._thumbnail_reorder_pending = True
        self.page_list.setDragEnabled(False)
        source, target = context
        QTimer.singleShot(
            0,
            lambda source=source, target=target: self._finish_thumbnail_reorder(
                source,
                target,
            ),
        )

    def _finish_thumbnail_reorder(self, source: int, target: int) -> None:
        try:
            if not self._move_page(source, target):
                self._load_thumbnails(self.current_page)
                self._select_and_render_page(self.current_page)
        finally:
            self._thumbnail_reorder_pending = False
            self._update_actions()

    def _show_page_context_menu(self, row: int, global_position: object) -> None:
        """Show PowerPoint-style commands for the thumbnail under the pointer."""

        if (
            not self.engine.is_open
            or not 0 <= row < self.engine.page_count
            or self._document_write_in_progress(False)
            or self._ocr_progress is not None
        ):
            return
        self._select_and_render_page(row)
        menu = QMenu(self)
        move_up = menu.addAction(self.trx("move_page_up"))
        move_up.setEnabled(row > 0)
        move_up.triggered.connect(
            lambda _checked=False, source=row: self._move_page(source, source - 1)
        )
        move_down = menu.addAction(self.trx("move_page_down"))
        move_down.setEnabled(row + 1 < self.engine.page_count)
        move_down.triggered.connect(
            lambda _checked=False, source=row: self._move_page(source, source + 1)
        )
        menu.addSeparator()
        rotate_left = menu.addAction(self.trx("rotate_page_left"))
        rotate_left.triggered.connect(
            lambda _checked=False, page=row: self._rotate_page(page, -1)
        )
        rotate_right = menu.addAction(self.trx("rotate_page_right"))
        rotate_right.triggered.connect(
            lambda _checked=False, page=row: self._rotate_page(page, 1)
        )
        menu.addSeparator()
        delete = menu.addAction(self.trx("delete_page"))
        delete.triggered.connect(
            lambda _checked=False, page=row: self._delete_page_at(page)
        )
        self._exec_context_menu(menu, global_position)

    @staticmethod
    def _exec_context_menu(menu: QMenu, global_position: object):
        return menu.exec(global_position)

    def _cancel_thumbnail_loading(self) -> None:
        self._thumbnail_timer.stop()
        self._thumbnail_queue.clear()

    def _load_thumbnails(self, priority_page: int = 0) -> None:
        self._cancel_thumbnail_loading()
        self.page_list.blockSignals(True)
        self.page_list.clear()
        try:
            placeholder = self._thumbnail_placeholder_icon()
            for page_index in range(self.engine.page_count):
                item = QListWidgetItem(f"{self.trx('page_word')} {page_index + 1}")
                item.setIcon(placeholder)
                item.setTextAlignment(Qt.AlignHCenter)
                self.page_list.addItem(item)
        finally:
            self.page_list.blockSignals(False)

        page_count = self.engine.page_count
        if not page_count:
            return
        priority_page = min(max(0, priority_page), page_count - 1)
        self._thumbnail_queue.extend(
            [priority_page, *(page for page in range(page_count) if page != priority_page)]
        )
        self._thumbnail_timer.start(0)

    def _render_thumbnail_batch(self) -> None:
        if not self.engine.is_open:
            self._thumbnail_queue.clear()
            return

        elapsed = QElapsedTimer()
        elapsed.start()
        rendered = 0
        while self._thumbnail_queue and (rendered == 0 or elapsed.elapsed() < 16) and rendered < 8:
            page_index = self._thumbnail_queue.popleft()
            if not 0 <= page_index < self.engine.page_count:
                continue
            try:
                samples, width, height, stride = self.engine.render_page(page_index, 0.18)
                image = QImage(samples, width, height, stride, QImage.Format_RGB888).copy()
                item = self.page_list.item(page_index)
                if item is not None:
                    item.setIcon(QIcon(QPixmap.fromImage(image)))
            except Exception:
                # A damaged page must not stop the remaining thumbnails or the editor itself.
                pass
            rendered += 1

        if self._thumbnail_queue:
            self._thumbnail_timer.start(0)

    def _select_and_render_page(self, page_index: int) -> None:
        if not self.engine.page_count:
            return
        self.current_page = min(max(0, page_index), self.engine.page_count - 1)
        self.page_list.blockSignals(True)
        self.page_list.setCurrentRow(self.current_page)
        self.page_list.blockSignals(False)
        self._render_current_page()

    def _page_selected(self, row: int) -> None:
        if row < 0 or not self.engine.is_open:
            return
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        self.cancel_special_mode()
        self.current_page = row
        self._render_current_page()

    def _scroll_main_view(self, direction: int) -> None:
        if not self.engine.is_open or not direction:
            return
        target_page = min(
            max(0, self.current_page + (1 if direction > 0 else -1)),
            self.engine.page_count - 1,
        )
        if target_page == self.current_page:
            return
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        self.cancel_special_mode()
        self._select_and_render_page(target_page)
        scroll_bar = self.page_view.verticalScrollBar()
        scroll_bar.setValue(
            scroll_bar.minimum() if direction > 0 else scroll_bar.maximum()
        )

    def _schedule_tile_render(self, *_args) -> None:
        if (
            self._tile_context is not None
            and self.engine.is_open
            and not self._render_in_progress
        ):
            self._tile_timer.start()

    def _cancel_tile_render(
        self,
        *,
        wait: bool = False,
        clear_cache: bool = False,
    ) -> None:
        self._tile_timer.stop()
        self._tile_renderer.cancel(wait=wait)
        legacy_task = self._legacy_tile_task
        if legacy_task is not None and hasattr(legacy_task, "cancel"):
            legacy_task.cancel()
        self._legacy_tile_task = None
        # Drop QRunnables which have not started yet.  A single running task
        # exits cooperatively; without clear(), rapid scroll events can queue
        # obsolete whole-document snapshots behind it.
        self._tile_pool.clear()
        self._tile_context = None
        if wait:
            self._tile_pool.waitForDone()
        if clear_cache:
            self._tile_cache.clear()
            self._tile_cache_bytes = 0
            self._tile_cache_hits = 0
            self._tile_cache_misses = 0
            self._tile_cache_evictions = 0

    def _clear_tile_render_source(self) -> None:
        temporary = self._tile_source_temporary
        self._tile_source_temporary = None
        workspace = self._tile_source_workspace
        self._tile_source_workspace = None
        self._tile_source_path = None
        if temporary is not None:
            temporary.cleanup()
        elif workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)

    def _prepare_tile_render_source(self) -> None:
        self._clear_tile_render_source()
        if not self.engine.is_open:
            return
        temporary = tempfile.TemporaryDirectory(prefix="NettongiaPDFEditor-render-source-")
        workspace = Path(temporary.name)
        source_path = workspace / "source.pdf"
        try:
            source_path.write_bytes(self.engine.source_bytes)
        except Exception:
            temporary.cleanup()
            raise
        self._tile_source_temporary = temporary
        self._tile_source_workspace = workspace
        self._tile_source_path = source_path

    def _tile_rects_for_visible_area(self) -> list[tuple[int, int, int, int]]:
        page_rect = self.page_view.sceneRect()
        visible = self.page_view.visible_page_rect(RENDER_TILE_SIZE)
        if page_rect.isEmpty() or visible.isEmpty():
            return []
        page_width = max(1, math.ceil(page_rect.width()))
        page_height = max(1, math.ceil(page_rect.height()))
        left = max(0, math.floor(visible.left() / RENDER_TILE_SIZE) * RENDER_TILE_SIZE)
        top = max(0, math.floor(visible.top() / RENDER_TILE_SIZE) * RENDER_TILE_SIZE)
        right = min(
            page_width,
            math.ceil(visible.right() / RENDER_TILE_SIZE) * RENDER_TILE_SIZE,
        )
        bottom = min(
            page_height,
            math.ceil(visible.bottom() / RENDER_TILE_SIZE) * RENDER_TILE_SIZE,
        )
        rects = [
            (x, y, min(page_width, x + RENDER_TILE_SIZE), min(page_height, y + RENDER_TILE_SIZE))
            for y in range(top, bottom, RENDER_TILE_SIZE)
            for x in range(left, right, RENDER_TILE_SIZE)
        ]
        center = self.page_view.visible_page_rect().center()
        rects.sort(
            key=lambda rect: (
                (rect[0] + rect[2]) / 2 - center.x()
            ) ** 2
            + (
                (rect[1] + rect[3]) / 2 - center.y()
            ) ** 2
        )
        return rects

    def _start_visible_tile_render(self) -> None:
        context = self._tile_context
        if context is None or not self.engine.is_open or self._render_in_progress:
            return
        document_generation, content_revision, page_index, scale, preview_scale = context
        if (
            document_generation != self._document_generation
            or content_revision != self._content_revision
            or page_index != self.current_page
            or preview_scale + 0.001 >= scale
        ):
            return

        if self._tile_task is not None:
            active_context = self._tile_context
            self._cancel_tile_render(wait=True)
            self._tile_context = active_context
        self._tile_pool.clear()

        rects = self._tile_rects_for_visible_area()
        keys = {context + rect for rect in rects}
        self.page_view.retain_render_tiles(keys)
        missing: list[tuple[int, int, int, int]] = []
        for rect in rects:
            key = context + rect
            cached = self._tile_cache.get(key)
            if cached is None:
                self._tile_cache_misses += 1
                missing.append(rect)
                continue
            self._tile_cache_hits += 1
            x, y, pixmap, _cost = cached
            self._tile_cache.move_to_end(key)
            self.page_view.set_render_tile(key, pixmap, x, y)
        if not missing:
            return

        source_path = self._tile_source_path
        if source_path is None or not source_path.is_file():
            return
        try:
            self._tile_renderer.start(
                source_path,
                page_index,
                scale,
                tuple(missing),
                context=context,
                edits=tuple(self.edits.values()),
                # Inserted images remain sharp, interactive scene overlays.
                inserted_images=(),
                deleted_images=tuple(self.deleted_images),
                inserted_texts=tuple(self.inserted_texts),
            )
        except Exception:
            # The scaled preview remains usable if an individual high-detail
            # pass cannot be prepared.
            return

    def _tile_render_completed(self, outcome: TileRenderOutcome) -> None:
        if outcome.error is not None:
            self._operation_log.record(
                "tile_render_failed",
                worker="tile",
                outcome="failed",
                reason=error_reason(outcome.error),
                page_index=outcome.context[2],
            )
            return
        if outcome.context != self._tile_context:
            return
        for rendered in outcome.tiles:
            self._apply_rendered_tile(rendered)

    def _apply_rendered_tile(self, rendered: object) -> None:
        if (
            self._tile_context is None
            or not isinstance(rendered, RenderedTile)
        ):
            return
        image = QImage(
            rendered.samples,
            rendered.width,
            rendered.height,
            rendered.stride,
            QImage.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image)
        key = self._tile_context + rendered.requested_rect
        cost = max(1, pixmap.width() * pixmap.height() * 4)
        previous = self._tile_cache.pop(key, None)
        if previous is not None:
            self._tile_cache_bytes -= previous[3]
        self._tile_cache[key] = (rendered.x, rendered.y, pixmap, cost)
        self._tile_cache_bytes += cost
        while self._tile_cache_bytes > RENDER_TILE_CACHE_BYTES and len(self._tile_cache) > 1:
            _old_key, (_x, _y, _pixmap, old_cost) = self._tile_cache.popitem(last=False)
            self._tile_cache_bytes -= old_cost
            self._tile_cache_evictions += 1
        self.page_view.set_render_tile(key, pixmap, rendered.x, rendered.y)

    def _render_current_page(self) -> None:
        if not self.engine.is_open:
            self._render_pending = False
            return
        if (
            self.page_view.inline_editing
            or self.page_view.pointer_interaction_active
            or self._render_in_progress
        ):
            # Never destroy a focused QGraphicsProxyWidget while Qt is still
            # dispatching its mouse/focus event. A queued text-frame update can
            # otherwise race with a double click and remove the live scene.
            self._render_pending = True
            return
        self._render_pending = False
        self._render_in_progress = True
        # Context keys include document generation, content revision, page and
        # scale, so cached tiles remain safe across navigation and zoom.  Keep
        # the bounded LRU here; document activation/close still clears it.
        self._cancel_tile_render(clear_cache=False)
        self.page_view.clear_render_tiles()
        text_reference = self.page_view.selected_text_ref or self._text_toolbar_reference
        if text_reference is not None:
            selected_spec = self._text_spec(*text_reference)
            if selected_spec is None or selected_spec.page_index != self.current_page:
                self.page_view.selected_text_ref = None
                self._clear_text_toolbar_target()
        self.render_scale = min(
            self.render_scale,
            self.engine.max_render_scale(self.current_page),
        )
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            page_rect = self.engine.page_rect(self.current_page)
            page_area = max(1.0, float(page_rect.width) * float(page_rect.height))
            preview_scale = min(
                self.render_scale,
                max(0.25, math.sqrt(PREVIEW_RENDER_PIXELS / page_area)),
            )
            page_images = [
                item for item in self.inserted_images if item.page_index == self.current_page
            ]
            page_signatures = [
                item for item in self.signatures if item.page_index == self.current_page
            ]
            samples, width, height, stride = self.engine.render_page(
                self.current_page,
                preview_scale,
                self.edits.values(),
                page_signatures,
                page_images,
                self.deleted_images,
                self.inserted_texts,
            )
            image = QImage(samples, width, height, stride, QImage.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(image)
            runs = self.engine.text_runs(self.current_page)
            text_objects: list[tuple[str, str, tuple[float, float, float, float]]] = []
            for run in runs:
                edit = self.edits.get(run.key)
                text_objects.append(
                    ("source", run.key, edit.bbox if edit and edit.bbox is not None else run.bbox)
                )
            text_objects.extend(
                ("inserted", item.key, item.bbox)
                for item in self.inserted_texts
                if item.page_index == self.current_page
            )
            deleted_keys = {item.run.key for item in self.deleted_images}
            visual_items: list[ImageRun] = [
                item
                for item in self.engine.image_runs(self.current_page)
                if item.key not in deleted_keys
            ]
            form_fields = []
            if self._form_workspace_mode in {"preview", "fill"}:
                form_fields = [
                    field
                    for field in self.engine.form_fields()
                    if field.page_index == self.current_page
                ]
            form_values = dict(self._form_preview_values)
            if self._form_workspace_mode == "fill":
                for field in form_fields:
                    if field.type_code != pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
                        continue
                    x0, y0, x1, y1 = field.bbox
                    if any(
                        signature.page_index == field.page_index
                        and x0 <= (signature.bbox[0] + signature.bbox[2]) / 2 <= x1
                        and y0 <= (signature.bbox[1] + signature.bbox[3]) / 2 <= y1
                        for signature in self.signatures
                    ):
                        form_values[field.xref] = FORM_VISUAL_SIGNATURE_VALUE
            self.page_view.set_page(
                pixmap,
                text_objects,
                visual_items,
                page_signatures,
                self.render_scale,
                preview_scale,
                (
                    float(page_rect.width) * self.render_scale,
                    float(page_rect.height) * self.render_scale,
                ),
                inserted_images=page_images,
                form_fields=form_fields,
                form_mode=self._form_workspace_mode,
                form_values=form_values,
                sign_label=self.trx("form_signature_button"),
                signed_label=self.trx("form_signed"),
                visual_signature_added_label=self.trx(
                    "form_visual_signature_added"
                ),
            )
            self._tile_context = (
                self._document_generation,
                self._content_revision,
                self.current_page,
                round(self.render_scale, 6),
                round(preview_scale, 6),
            )
            if preview_scale + 0.001 < self.render_scale:
                self._tile_timer.start(0)
            self._restore_search_highlight()
            self._sync_zoom_display()
            mode = self.trx("editable_text") if text_objects else self.trx("ocr_required")
            self.status_label.setText(
                f"{self.trx('page_word')} {self.current_page + 1}/{self.engine.page_count}   |   "
                f"{self.render_scale * 100:.0f}%   |   {mode}   |   "
                f"{self.trx('images')}: {len(visual_items)}   |   "
                f"{self.trx('signatures')}: {len(page_signatures)}   |   "
                f"{self.trx('text_boxes')}: {len(text_objects)}"
            )
        except Exception as exc:
            QMessageBox.critical(self, self.trx("render_error_title"), str(exc))
        finally:
            QApplication.restoreOverrideCursor()
            self._render_in_progress = False
            if self._render_pending and not self.page_view.inline_editing:
                QTimer.singleShot(0, self._render_current_page)

    def _resume_deferred_render(self) -> None:
        if (
            self._render_pending
            and self.engine.is_open
            and not self.page_view.inline_editing
            and not self.page_view.pointer_interaction_active
        ):
            self._render_current_page()

    def _edit_run(self, key: str) -> None:
        if self.page_view.special_mode:
            return
        run = self.engine.find_run(key)
        if run is None:
            return
        dialog = EditTextDialog(run, self.edits.get(key), self, self.trx)
        if dialog.exec():
            next_edits = copy.deepcopy(self.edits)
            edited = dialog.make_edit(run)
            if key in self.edits:
                edited = replace(edited, bbox=self.edits[key].bbox)
            next_edits[key] = edited
            state = self._capture_state()
            state.edits = next_edits
            self._push_state(state, self.current_page)

    def _text_spec(self, kind: str, key: str) -> TextObjectSpec | None:
        if kind == "source":
            if not self.engine.is_open:
                return None
            run = self.engine.find_run(key)
            if run is None:
                return None
            edit = self.edits.get(key)
            return TextObjectSpec(
                kind="source",
                key=key,
                page_index=run.page_index,
                bbox=edit.bbox if edit and edit.bbox is not None else run.bbox,
                text=edit.new_text if edit else run.text,
                # Keep the exact PDF family for the engine.  Convert it to a
                # GUI-friendly family only when it is shown in Qt controls.
                font_family=(edit.font_family if edit and edit.font_family else run.font_name),
                font_size=edit.font_size if edit else run.font_size,
                bold=(run.bold if edit is None or edit.bold is None else edit.bold),
                italic=(run.italic if edit is None or edit.italic is None else edit.italic),
                underline=edit.underline if edit else False,
                color=(run.color if edit is None or edit.color is None else edit.color),
            )
        if kind == "inserted":
            placement = next((item for item in self.inserted_texts if item.key == key), None)
            if placement is None:
                return None
            return TextObjectSpec(
                kind="inserted",
                key=key,
                page_index=placement.page_index,
                bbox=placement.bbox,
                text=placement.text,
                font_family=placement.font_family,
                font_size=placement.font_size,
                bold=placement.bold,
                italic=placement.italic,
                underline=placement.underline,
                color=placement.color,
            )
        return None

    def _text_selection_changed(self, reference: tuple[str, str] | None) -> None:
        if not self.engine.is_open:
            return
        if reference is None:
            self._clear_text_toolbar_target()
            self._update_actions()
            return
        self._text_toolbar_reference = reference
        spec = self._text_spec(*reference)
        if spec is None:
            return
        self._sync_text_toolbar(spec)
        self.statusBar().showMessage(
            self.trx("select_text_hint"),
            5000,
        )
        self._update_actions()

    def _clear_text_toolbar_target(self) -> None:
        self._text_toolbar_reference = None
        self._text_toolbar_preserved_family = None
        self._text_font_user_changed = False

    def _sync_text_toolbar(self, spec: TextObjectSpec) -> None:
        self._text_toolbar_reference = (spec.kind, spec.key)
        self._text_font_user_changed = False
        if spec.kind == "source":
            run = self.engine.find_run(spec.key)
            existing = self.edits.get(spec.key)
            self._text_toolbar_preserved_family = (
                existing.font_family
                if existing is not None and existing.font_family
                else run.font_name if run is not None else spec.font_family
            )
        else:
            self._text_toolbar_preserved_family = spec.font_family
        self._syncing_text_toolbar = True
        try:
            display_family = self._display_font_family(spec)
            self.text_font_box.setCurrentFont(QFont(display_family))
            self._show_font_name_start()
            QTimer.singleShot(0, self._show_font_name_start)
            self._set_font_size_value(spec.font_size)
            self.text_bold_button.setChecked(spec.bold)
            self.text_italic_button.setChecked(spec.italic)
            self.text_underline_button.setChecked(spec.underline)
            self._text_color = QColor(
                (spec.color >> 16) & 255,
                (spec.color >> 8) & 255,
                spec.color & 255,
            )
            self._refresh_text_color_button()
        finally:
            self._syncing_text_toolbar = False

    def _display_font_family(self, spec: TextObjectSpec) -> str:
        if spec.kind != "source":
            return spec.font_family
        run = self.engine.find_run(spec.key) if self.engine.is_open else None
        existing = self.edits.get(spec.key)
        if (
            run is not None
            and existing is not None
            and existing.font_family
            and existing.font_family != run.font_name
        ):
            return existing.font_family
        return clean_pdf_font_name(run.font_name if run is not None else spec.font_family)

    def _font_selection_changed(self, *_args) -> None:
        self._show_font_name_start()
        QTimer.singleShot(0, self._show_font_name_start)
        if not self._syncing_text_toolbar:
            self._text_font_user_changed = True
        self._apply_selected_text_format()

    def _show_font_name_start(self) -> None:
        if not hasattr(self, "text_font_box"):
            return
        editor = self.text_font_box.lineEdit()
        if editor is None:
            return
        editor.deselect()
        editor.setCursorPosition(0)
        full_name = self.text_font_box.currentText().strip()
        if not full_name:
            full_name = self.text_font_box.currentFont().family()
        editor.setToolTip(full_name)

    def _show_font_size_start(self) -> None:
        if not hasattr(self, "text_size_box"):
            return
        editor = self.text_size_box.lineEdit()
        if editor is None:
            return
        editor.deselect()
        editor.setCursorPosition(0)
        editor.setToolTip(self.text_size_box.currentText().strip())

    @staticmethod
    def _format_font_size(value: float) -> str:
        rounded = round(value, 1)
        number = f"{rounded:.1f}".rstrip("0").rstrip(".")
        return f"{number} pt"

    def _set_font_size_value(self, value: float) -> None:
        self._font_size_value = round(min(200.0, max(3.0, float(value))), 1)
        self.text_size_box.blockSignals(True)
        try:
            self.text_size_box.setCurrentText(self._format_font_size(self._font_size_value))
        finally:
            self.text_size_box.blockSignals(False)
        self._show_font_size_start()
        QTimer.singleShot(0, self._show_font_size_start)

    def _font_size_changed(self, *_args) -> None:
        raw_value = self.text_size_box.currentText().lower().replace("pt", "").strip()
        try:
            value = float(raw_value.replace(",", "."))
            if not math.isfinite(value):
                raise ValueError
        except ValueError:
            self._set_font_size_value(self._font_size_value)
            return
        self._set_font_size_value(value)
        self._apply_selected_text_format()

    def _toolbar_text_values(self) -> tuple[str, float, bool, bool, bool, int]:
        color = (self._text_color.red() << 16) | (self._text_color.green() << 8) | self._text_color.blue()
        return (
            self.text_font_box.currentFont().family(),
            self._font_size_value,
            self.text_bold_button.isChecked(),
            self.text_italic_button.isChecked(),
            self.text_underline_button.isChecked(),
            color,
        )

    def _apply_selected_text_format(self) -> None:
        if self._syncing_text_toolbar or not self.engine.is_open:
            return
        reference = self.page_view.selected_text_ref or self._text_toolbar_reference
        if reference is None:
            return
        kind, key = reference
        spec = self._text_spec(kind, key)
        if spec is None or spec.page_index != self.current_page:
            return
        family, size, bold, italic, underline, color = self._toolbar_text_values()
        run = self.engine.find_run(key) if kind == "source" else None
        previous = self.edits.get(key) if kind == "source" else None
        if kind == "source":
            # QFontComboBox exposes the installed substitute family (for
            # example Nimbus Roman) even when the PDF used TimesNewRomanPS.
            # Until the user explicitly picks a different family, retain the
            # original PDF family so changing only the size/style cannot
            # silently change the typeface.
            effective_family = (
                family
                if self._text_font_user_changed
                else self._text_toolbar_preserved_family
                or (run.font_name if run is not None else spec.font_family)
            )
        else:
            effective_family = family
        if (
            (effective_family == (previous.font_family if previous and previous.font_family else run.font_name if run is not None else spec.font_family))
            and abs(size - spec.font_size) < 0.01
            and bold == spec.bold
            and italic == spec.italic
            and underline == spec.underline
            and color == spec.color
        ):
            return
        state = self._capture_state()
        if kind == "source":
            if run is None:
                return
            size_changed = abs(size - spec.font_size) >= 0.01
            state.edits[key] = TextEdit(
                run=run,
                new_text=spec.text,
                font_size=size,
                # An explicit point-size change must be visible.  Auto-fit is
                # useful for replacement text, but it used to silently shrink
                # 14 pt back to roughly the original 12 pt box width.
                fit_to_width=False if size_changed else previous.fit_to_width if previous else True,
                font_family=effective_family,
                bold=bold,
                italic=italic,
                underline=underline,
                color=color,
                bbox=previous.bbox if previous and previous.bbox is not None else None,
            )
        else:
            state.inserted_texts = [
                replace(
                    item,
                    font_family=family,
                    font_size=size,
                    bold=bold,
                    italic=italic,
                    underline=underline,
                    color=color,
                )
                if item.key == key
                else item
                for item in state.inserted_texts
            ]
        self.page_view.selected_text_ref = reference
        self._text_toolbar_reference = reference
        self._push_state(state, spec.page_index)

    def _choose_text_color(self) -> None:
        color = QColorDialog.getColor(self._text_color, self, self.trx("choose_text_color"))
        if not color.isValid():
            return
        self._text_color = color
        self._refresh_text_color_button()
        self._apply_selected_text_format()

    def _refresh_text_color_button(self) -> None:
        if not hasattr(self, "text_color_button"):
            return
        base = self._text_color.name()
        foreground = "#ffffff" if self._text_color.lightness() < 145 else "#111820"
        border = "#ffd166" if self._effective_dark else "#455463"
        self.text_color_button.setStyleSheet(
            "QToolButton {"
            f"background: {base}; color: {foreground}; border: 2px solid {border}; "
            "border-radius: 4px; font-weight: bold; padding: 1px; margin: 0; }"
            f"QToolButton:hover {{ border-color: #ffffff; background: {base}; }}"
        )

    def start_add_text(self) -> None:
        if not self.engine.is_open:
            return
        self.cancel_special_mode()
        self.page_view.selected_text_ref = None
        self._clear_text_toolbar_target()
        self.page_view.scene().clearSelection()
        self.page_view.set_text_box_mode(True)
        self.statusBar().showMessage(
            self.trx("add_text_hint")
        )

    def _create_text_box(self, bbox: tuple[float, float, float, float]) -> None:
        key = uuid4().hex
        self._pending_text_box = (key, bbox)
        family, size, bold, italic, underline, color = self._toolbar_text_values()
        self.page_view.start_inline_editor(
            "new",
            key,
            bbox,
            "",
            family,
            size,
            bold,
            italic,
            underline,
            color,
            self._effective_dark,
        )
        self.statusBar().showMessage(self.trx("type_text_hint"))

    def _start_inline_text_edit(self, kind: str, key: str) -> None:
        spec = self._text_spec(kind, key)
        if spec is None:
            return
        self._sync_text_toolbar(spec)
        self.page_view.start_inline_editor(
            kind,
            key,
            spec.bbox,
            spec.text,
            self._display_font_family(spec),
            spec.font_size,
            spec.bold,
            spec.italic,
            spec.underline,
            spec.color,
            self._effective_dark,
        )
        self.statusBar().showMessage(self.trx("direct_edit_hint"))

    def _finish_inline_text_edit(self, kind: str, key: str, text: str) -> None:
        if kind == "new":
            pending = self._pending_text_box
            self._pending_text_box = None
            if pending is None or pending[0] != key or not text:
                self.page_view.selected_text_ref = None
                self._update_actions()
                return
            family, size, bold, italic, underline, color = self._toolbar_text_values()
            text_bbox = self._expanded_text_bbox(self.current_page, pending[1], size, text)
            state = self._capture_state()
            state.inserted_texts.append(
                TextPlacement(
                    key=key,
                    page_index=self.current_page,
                    bbox=text_bbox,
                    text=text,
                    font_family=family,
                    font_size=size,
                    bold=bold,
                    italic=italic,
                    underline=underline,
                    color=color,
                )
            )
            self.page_view.selected_text_ref = ("inserted", key)
            self._push_state(state, self.current_page)
            self.statusBar().showMessage(self.trx("text_inserted"), 5000)
            return

        spec = self._text_spec(kind, key)
        if spec is None or text == spec.text:
            self._update_actions()
            return
        state = self._capture_state()
        text_bbox = self._expanded_text_bbox(spec.page_index, spec.bbox, spec.font_size, text)
        if kind == "source":
            run = self.engine.find_run(key)
            if run is None:
                return
            previous = self.edits.get(key)
            family = (
                self._toolbar_text_values()[0]
                if self._text_font_user_changed
                else previous.font_family
                if previous is not None and previous.font_family
                else run.font_name
            )
            state.edits[key] = TextEdit(
                run=run,
                new_text=text,
                font_size=spec.font_size,
                fit_to_width=previous.fit_to_width if previous else True,
                font_family=family,
                bold=spec.bold,
                italic=spec.italic,
                underline=spec.underline,
                color=spec.color,
                bbox=text_bbox if text_bbox != run.bbox else None,
            )
        elif kind == "inserted":
            if text:
                state.inserted_texts = [
                    replace(item, text=text, bbox=text_bbox) if item.key == key else item
                    for item in state.inserted_texts
                ]
            else:
                state.inserted_texts = [item for item in state.inserted_texts if item.key != key]
                self.page_view.selected_text_ref = None
        self._push_state(state, spec.page_index)
        self.statusBar().showMessage(self.trx("text_updated"), 4000)

    def _cancel_inline_text_edit(self, kind: str, key: str) -> None:
        if kind == "new" and self._pending_text_box and self._pending_text_box[0] == key:
            self._pending_text_box = None
            self.page_view.selected_text_ref = None
        self.statusBar().showMessage(self.trx("text_cancelled"), 2500)
        self._update_actions()

    def _normalized_text_bbox(
        self,
        page_index: int,
        bbox: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        page = self.engine.page_rect(page_index)
        x0, y0, x1, y1 = bbox
        width = min(max(12.0, x1 - x0), page.width)
        height = min(max(8.0, y1 - y0), page.height)
        x0 = min(max(page.x0, x0), page.x1 - width)
        y0 = min(max(page.y0, y0), page.y1 - height)
        return x0, y0, x0 + width, y0 + height

    def _expanded_text_bbox(
        self,
        page_index: int,
        bbox: tuple[float, float, float, float],
        font_size: float,
        text: str,
    ) -> tuple[float, float, float, float]:
        lines = max(1, text.count("\n") + 1)
        required_height = max(8.0, lines * max(3.0, font_size) * 1.2 + 5.0)
        if bbox[3] - bbox[1] >= required_height:
            return self._normalized_text_bbox(page_index, bbox)
        return self._normalized_text_bbox(
            page_index,
            (bbox[0], bbox[1], bbox[2], bbox[1] + required_height),
        )

    def _transform_text(
        self,
        kind: str,
        key: str,
        bbox: tuple[float, float, float, float],
    ) -> None:
        if not self.engine.is_open:
            return
        spec = self._text_spec(kind, key)
        if spec is None:
            return
        bbox = self._normalized_text_bbox(spec.page_index, bbox)
        if all(abs(left - right) < 0.01 for left, right in zip(spec.bbox, bbox)):
            return
        state = self._capture_state()
        if kind == "source":
            run = self.engine.find_run(key)
            if run is None:
                return
            previous = self.edits.get(key)
            state.edits[key] = TextEdit(
                run=run,
                new_text=spec.text,
                font_size=spec.font_size,
                fit_to_width=previous.fit_to_width if previous else True,
                font_family=spec.font_family,
                bold=spec.bold,
                italic=spec.italic,
                underline=spec.underline,
                color=spec.color,
                bbox=bbox,
            )
        else:
            state.inserted_texts = [
                replace(item, bbox=bbox) if item.key == key else item
                for item in state.inserted_texts
            ]
        self.page_view.selected_text_ref = (kind, key)
        self._push_state(state, spec.page_index)
        self.statusBar().showMessage(self.trx("text_frame_updated"), 3500)

    def delete_selected_text(self) -> None:
        if self.page_view.selected_text_ref is not None:
            self._delete_text(*self.page_view.selected_text_ref)

    def _delete_text(self, kind: str, key: str) -> None:
        if not self.engine.is_open:
            return
        spec = self._text_spec(kind, key)
        if spec is None:
            return
        state = self._capture_state()
        if kind == "source":
            if not spec.text:
                return
            run = self.engine.find_run(key)
            if run is None:
                return
            previous = self.edits.get(key)
            state.edits[key] = TextEdit(
                run=run,
                new_text="",
                font_size=spec.font_size,
                fit_to_width=previous.fit_to_width if previous else True,
                font_family=spec.font_family,
                bold=spec.bold,
                italic=spec.italic,
                underline=spec.underline,
                color=spec.color,
                bbox=spec.bbox if spec.bbox != run.bbox else None,
            )
        else:
            state.inserted_texts = [item for item in state.inserted_texts if item.key != key]
        self.page_view.selected_text_ref = None
        self._clear_text_toolbar_target()
        self._push_state(state, spec.page_index)
        self._operation_log.record(
            "text_deleted",
            operation="text_delete",
            outcome="succeeded",
            page_index=spec.page_index,
        )
        self.statusBar().showMessage(self.trx("text_removed"), 4000)

    def _show_object_context_menu(
        self,
        category: str,
        kind: str,
        key: str,
        global_position: object,
    ) -> None:
        """Show object actions for a right-click inside the page canvas."""

        if not self.engine.is_open or self._document_write_in_progress(False):
            return
        menu = QMenu(self)
        if category == "text":
            edit = menu.addAction(self.trx("edit_text"))
            edit.triggered.connect(
                lambda _checked=False, text_kind=kind, text_key=key:
                self._start_inline_text_edit(text_kind, text_key)
            )
            menu.addSeparator()
            delete = menu.addAction(self.trx("delete_text"))
            delete.triggered.connect(
                lambda _checked=False, text_kind=kind, text_key=key:
                self._delete_text(text_kind, text_key)
            )
            menu.addSeparator()
            highlight = menu.addAction(self.trx("highlight_text"))
            highlight.triggered.connect(
                lambda _checked=False, text_kind=kind, text_key=key:
                self._highlight_text(text_kind, text_key)
            )
        elif category == "visual":
            if kind == "source":
                edit = menu.addAction(self.trx("edit_original_image"))
                edit.triggered.connect(
                    lambda _checked=False, image_key=key:
                    self._promote_source_image(image_key)
                )
            delete = menu.addAction(self.trx("delete_image"))
            delete.triggered.connect(
                lambda _checked=False, image_kind=kind, image_key=key:
                self._delete_visual(image_kind, image_key)
            )
        else:
            return
        self._exec_context_menu(menu, global_position)

    def _push_state(self, state: EditorState, target_page: int) -> None:
        self._document_session.content_changed(history_index=self.history_index)
        del self.history[self.history_index + 1 :]
        self.history.append(copy.deepcopy(state))
        self.history_index += 1
        self._apply_state(self.history[self.history_index], target_page)
        self._operation_log.record(
            "state_changed",
            outcome="succeeded",
            history_index=self.history_index,
            page_index=target_page,
            content_revision=self._content_revision,
        )

    def _apply_state(self, state: EditorState, target_page: int) -> None:
        current_path = self.engine.path
        source_changed = not self.engine.is_open or self.engine.source_bytes != state.pdf_bytes
        if source_changed:
            tree_was_selected = self.sidebar_tabs.currentIndex() == self.outline_tab_index
            self._clear_outline_tree()
            self._cancel_tile_render(clear_cache=True)
            self.engine.load_bytes(state.pdf_bytes, current_path)
            self._prepare_tile_render_source()
        self.edits = copy.deepcopy(state.edits)
        self.inserted_texts = copy.deepcopy(state.inserted_texts)
        self.signatures = copy.deepcopy(state.signatures)
        self.inserted_images = copy.deepcopy(state.inserted_images)
        self.deleted_images = copy.deepcopy(state.deleted_images)
        if source_changed:
            self._load_thumbnails(target_page)
            self._load_outline_tree(select_tree=tree_was_selected)
            self._start_document_inspection()
        self._refresh_annotations_sidebar()
        self._refresh_forms_sidebar()
        self._select_and_render_page(target_page)
        self._update_actions()
        self._update_window_title()
        if self.find_bar.isVisible() and self.find_edit.text().strip():
            self._search_timer.start(0)
        self._sync_recovery_to_state()

    def undo(self) -> None:
        if self.history_index <= 0:
            return
        self.cancel_special_mode()
        self.history_index -= 1
        self._document_session.revision_changed()
        self._apply_state(self.history[self.history_index], min(self.current_page, self.engine.page_count - 1))

    def redo(self) -> None:
        if self.history_index >= len(self.history) - 1:
            return
        self.cancel_special_mode()
        self.history_index += 1
        self._document_session.revision_changed()
        self._apply_state(self.history[self.history_index], min(self.current_page, self.engine.page_count - 1))

    def _remap_content_pages(self, pdf_bytes: bytes, page_mapper) -> EditorState:
        state = self._capture_state()
        state.pdf_bytes = pdf_bytes
        remapped_edits: dict[str, TextEdit] = {}
        for edit in state.edits.values():
            page_index = page_mapper(edit.run.page_index)
            if page_index is None:
                continue
            run = replace(
                edit.run,
                page_index=page_index,
                key=(
                    f"{page_index}:{edit.run.block_index}:{edit.run.line_index}:"
                    f"{edit.run.span_index}"
                ),
            )
            remapped_edit = replace(edit, run=run)
            remapped_edits[run.key] = remapped_edit
        state.edits = remapped_edits
        state.inserted_texts = [
            replace(item, page_index=page_index)
            for item in state.inserted_texts
            if (page_index := page_mapper(item.page_index)) is not None
        ]
        state.signatures = [
            replace(item, page_index=page_index)
            for item in state.signatures
            if (page_index := page_mapper(item.page_index)) is not None
        ]
        state.inserted_images = [
            replace(item, page_index=page_index)
            for item in state.inserted_images
            if (page_index := page_mapper(item.page_index)) is not None
        ]
        remapped_deletions: list[ImageDeletion] = []
        for deletion in state.deleted_images:
            page_index = page_mapper(deletion.run.page_index)
            if page_index is None:
                continue
            occurrence = deletion.run.key.rsplit(":", 1)[-1]
            run = replace(
                deletion.run,
                page_index=page_index,
                key=f"image:{page_index}:{occurrence}",
            )
            remapped_deletions.append(ImageDeletion(run))
        state.deleted_images = remapped_deletions
        return state

    def add_blank_page(self) -> None:
        if not self.engine.is_open:
            return
        self.cancel_special_mode()
        insertion_index = self.current_page + 1
        temp = PdfEngine()
        try:
            temp.load_bytes(self.engine.source_bytes)
            new_bytes = temp.bytes_with_blank_page(self.current_page)
        except Exception as exc:
            QMessageBox.critical(self, self.trx("add_blank_page"), str(exc))
            return
        finally:
            temp.close()
        state = self._remap_content_pages(
            new_bytes,
            lambda page: page + 1 if page >= insertion_index else page,
        )
        self._push_state(state, insertion_index)

    def insert_pdf_pages(self) -> None:
        if not self.engine.is_open:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.trx("insert_pages"),
            "",
            self.trx("pdf_filter"),
        )
        if not path:
            return
        self.cancel_special_mode()
        insertion_index = self.current_page + 1
        temp = PdfEngine()
        try:
            temp.load_bytes(self.engine.source_bytes)
            password: str | None = None
            password_prompt = self.trx("pdf_password_prompt")
            while True:
                try:
                    new_bytes, inserted_count = temp.bytes_with_pdf_inserted(
                        self.current_page,
                        path,
                        password=password,
                    )
                    break
                except PdfPasswordRequiredError:
                    pass
                except PdfInvalidPasswordError:
                    password_prompt = self.trx("pdf_password_incorrect")
                password, accepted = QInputDialog.getText(
                    self,
                    self.trx("pdf_password_title"),
                    password_prompt,
                    QLineEdit.Password,
                )
                if not accepted:
                    return
        except Exception as exc:
            QMessageBox.critical(self, self.trx("insert_pages"), str(exc))
            return
        finally:
            temp.close()
        if inserted_count:
            state = self._remap_content_pages(
                new_bytes,
                lambda page: page + inserted_count if page >= insertion_index else page,
            )
            self._push_state(state, insertion_index)

    def delete_current_page(self) -> None:
        if self.engine.is_open:
            self._delete_page_at(self.current_page)

    def _delete_page_at(self, page_index: int) -> bool:
        if not self.engine.is_open or not 0 <= page_index < self.engine.page_count:
            return False
        if self.engine.page_count <= 1:
            QMessageBox.information(self, self.trx("delete_page"), self.trx("cannot_delete_page"))
            return False
        answer = QMessageBox.question(
            self,
            self.trx("delete_page"),
            self.trx("delete_page_question", page=page_index + 1),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return False
        self.cancel_special_mode()
        removed_page = page_index
        temp = PdfEngine()
        try:
            temp.load_bytes(self.engine.source_bytes)
            new_bytes = temp.bytes_without_page(page_index)
        except Exception as exc:
            QMessageBox.critical(self, self.trx("delete_page"), str(exc))
            return False
        finally:
            temp.close()
        new_page = min(page_index, self.engine.page_count - 2)
        state = self._remap_content_pages(
            new_bytes,
            lambda page: None if page == removed_page else page - 1 if page > removed_page else page,
        )
        self._push_state(state, new_page)
        self._operation_log.record(
            "page_deleted",
            operation="page_delete",
            outcome="succeeded",
            page_index=removed_page,
            page_count=self.engine.page_count,
        )
        return True

    @staticmethod
    def _moved_page_index(page: int, source: int, target: int) -> int:
        if page == source:
            return target
        if source < target and source < page <= target:
            return page - 1
        if target < source and target <= page < source:
            return page + 1
        return page

    def move_current_page_up(self) -> None:
        self._move_current_page(-1)

    def move_current_page_down(self) -> None:
        self._move_current_page(1)

    def rotate_current_page(self, quarter_turns: int) -> None:
        if self.engine.is_open:
            self._rotate_page(self.current_page, quarter_turns)

    def _rotate_page(self, page_index: int, quarter_turns: int) -> bool:
        """Rotate one logical page while preserving all pending editor work."""

        if not self.engine.is_open or not 0 <= page_index < self.engine.page_count:
            return False
        turns = int(quarter_turns)
        if turns == 0 or turns % 4 == 0:
            return False
        self.cancel_special_mode()
        temp = PdfEngine()
        try:
            # Materialize pending objects into the working snapshot before the
            # PDF page rotation. This makes text, images, signatures and their
            # deletions rotate together instead of drifting in screen space.
            composed = self.engine.compose_bytes(
                self.edits.values(),
                self.signatures,
                self.inserted_images,
                self.deleted_images,
                self.inserted_texts,
            )
            temp.load_bytes(composed)
            rotated_bytes = temp.bytes_with_page_rotated(page_index, turns)
        except Exception as exc:
            QMessageBox.critical(self, self.trx("menu_page"), str(exc))
            return False
        finally:
            temp.close()
        state = EditorState(rotated_bytes, {}, [], [], [], [])
        self._push_state(state, page_index)
        self._operation_log.record(
            "page_rotated",
            operation="page_rotate",
            outcome="succeeded",
            page_index=page_index,
            quarter_turns=turns,
            page_count=self.engine.page_count,
        )
        self.statusBar().showMessage(
            self.trx("page_rotated", page=page_index + 1),
            4000,
        )
        return True

    def _move_current_page(self, offset: int) -> None:
        if not self.engine.is_open:
            return
        source = self.current_page
        target = source + offset
        self._move_page(source, target)

    def _move_page(self, source: int, target: int) -> bool:
        """Move one logical page and every pending object attached to it."""

        if not self.engine.is_open:
            return False
        if not 0 <= target < self.engine.page_count:
            return False
        if not 0 <= source < self.engine.page_count or source == target:
            return False
        self.cancel_special_mode()
        temp = PdfEngine()
        try:
            temp.load_bytes(self.engine.source_bytes)
            new_bytes = temp.bytes_with_page_moved(source, target)
        except Exception as exc:
            QMessageBox.critical(self, self.trx("menu_page"), str(exc))
            return False
        finally:
            temp.close()
        state = self._remap_content_pages(
            new_bytes,
            lambda page: self._moved_page_index(page, source, target),
        )
        self._push_state(state, target)
        self._operation_log.record(
            "page_moved",
            operation="page_move",
            outcome="succeeded",
            from_page=source,
            to_page=target,
            page_count=self.engine.page_count,
        )
        self.statusBar().showMessage(self.trx("page_moved", page=target + 1), 3500)
        return True

    def add_image(self) -> None:
        if not self.engine.is_open:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.trx("insert_image"),
            "",
            self.trx("image_filter"),
        )
        if not path:
            return
        try:
            payload = Path(path).read_bytes()
            image = QImage.fromData(payload)
            if image.isNull():
                raise ValueError(self.trx("invalid_image_format"))
        except Exception as exc:
            QMessageBox.critical(self, self.trx("unable_open_image"), str(exc))
            return
        default_width = min(220.0, self.engine.page_rect(self.current_page).width * 0.4)
        width, accepted = QInputDialog.getDouble(
            self,
            self.trx("insert_image"),
            self.trx("image_width_prompt"),
            default_width,
            20.0,
            1000.0,
            1,
        )
        if accepted:
            self._begin_visual_placement("image", payload, width, Path(path).name)

    def start_edit_original_image(self) -> None:
        if not self.engine.is_open:
            return
        deleted_keys = {item.run.key for item in self.deleted_images}
        candidates = [
            item
            for item in self.engine.image_runs(self.current_page)
            if item.key not in deleted_keys
        ]
        if not candidates:
            QMessageBox.information(self, self.trx("no_image"), self.trx("no_image_message"))
            return
        self.cancel_special_mode()
        self.page_view.set_source_image_edit_mode(True)
        self.statusBar().showMessage(self.trx("edit_original_image_hint"))

    def _promote_source_image(self, key: str) -> None:
        if not self.engine.is_open:
            return
        run = self.engine.find_image_run(key)
        if run is None or any(item.run.key == key for item in self.deleted_images):
            return
        # The click itself is selection only. It must not create a history
        # entry, rewrite the source stream, or change rendered pixels.
        self.cancel_special_mode()
        self.page_view.selected_signature_key = key
        self.page_view.selected_visual_ref = ("source", key)
        self.statusBar().showMessage(self.trx("original_image_ready"), 5000)

    def add_signature(self) -> None:
        if not self.engine.is_open:
            return
        try:
            record_signature_trace("dialog_opening", context="free")
            dialog = SignatureDialog(self, self.trx)
            if not dialog.exec():
                record_signature_trace("dialog_cancelled", context="free")
                return
            record_signature_trace("dialog_accepted", context="free")
            payload, width, rotation, description = dialog.signature_data()
            image = QImage.fromData(payload)
            record_signature_trace(
                "payload_ready",
                context="free",
                image_width=image.width(),
                image_height=image.height(),
                payload_bytes=len(payload),
            )
        except Exception as exc:
            record_signature_trace("handled_error", context="free", outcome="failed")
            QMessageBox.critical(self, self.trx("unable_create_signature"), str(exc))
            return
        try:
            record_signature_trace("free_placement_started", context="free")
            self._begin_visual_placement(
                "signature", payload, width, description, rotation
            )
            record_signature_trace("free_placement_ready", context="free")
        except Exception as exc:
            record_signature_trace("handled_error", context="free", outcome="failed")
            self._pending_visual = None
            self.page_view.set_placement_mode(False)
            QMessageBox.critical(self, self.trx("unable_create_signature"), str(exc))

    def start_add_comment(self) -> None:
        if not self.engine.is_open:
            return
        self.cancel_special_mode()
        self.page_view.set_comment_placement_mode(True)
        self.statusBar().showMessage(self.trx("comment_place_hint"))

    def start_redact_area(self) -> None:
        if (
            not self.engine.is_open
            or self._write_process is not None
            or self._ocr_process is not None
        ):
            return
        self.cancel_special_mode()
        self._redaction_target_page = self.current_page
        self.page_view.set_redaction_mode(True)
        self.statusBar().showMessage(self.trx("redaction_draw_hint"))

    def _confirm_redaction(
        self,
        bbox: tuple[float, float, float, float],
        page_generation: int,
    ) -> None:
        target_page = self._redaction_target_page
        self._redaction_target_page = None
        if (
            target_page is None
            or target_page != self.current_page
            or page_generation != self.page_view._page_generation
            or not self.engine.is_open
        ):
            return
        answer = QMessageBox.warning(
            self,
            self.trx("redaction_title"),
            self.trx("redaction_confirm"),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            self.statusBar().showMessage(self.trx("redaction_cancelled"), 3000)
            return
        if self._materialize_pdf_change(
            lambda engine: engine.bytes_with_redaction(target_page, bbox),
            target_page,
            self.trx("redaction_title"),
        ):
            self._operation_log.record(
                "area_redacted",
                operation="redact",
                outcome="succeeded",
                page_index=target_page,
            )
            self.statusBar().showMessage(self.trx("redaction_complete"), 5000)

    def _materialize_pdf_change(
        self,
        callback,
        target_page: int,
        error_title: str,
    ) -> bool:
        """Apply one native PDF mutation as a complete Undo/Redo state."""

        temporary = PdfEngine()
        try:
            composed = self.engine.compose_bytes(
                self.edits.values(),
                self.signatures,
                self.inserted_images,
                self.deleted_images,
                self.inserted_texts,
            )
            temporary.load_bytes(composed)
            changed_bytes = callback(temporary)
        except Exception as exc:
            QMessageBox.critical(self, error_title, str(exc))
            return False
        finally:
            temporary.close()
        self._push_state(EditorState(changed_bytes, {}, [], [], [], []), target_page)
        return True

    def _materialize_annotation_change(self, callback, target_page: int) -> bool:
        return self._materialize_pdf_change(
            callback,
            target_page,
            self.trx("comments"),
        )

    def start_create_form_field(self) -> None:
        if (
            not self.engine.is_open
            or self._write_process is not None
            or self._ocr_process is not None
        ):
            return
        try:
            existing_names = {field.name for field in self.engine.form_fields()}
        except Exception:
            existing_names = set()
        number = 1
        while f"field_{number}" in existing_names:
            number += 1
        dialog = FormFieldDialog(f"field_{number}", self, self.trx)
        if not dialog.exec():
            return
        spec = dialog.field_spec()
        self.cancel_special_mode()
        self._pending_form_field = spec
        self._form_field_target_page = self.current_page
        self.page_view.set_form_field_mode(
            True,
            compact=spec.type_code == pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
            signature=spec.type_code == pymupdf.PDF_WIDGET_TYPE_SIGNATURE,
        )
        self.statusBar().showMessage(self.trx("form_draw_hint"))

    def _form_value_edited(self, field_xref: int, value: object) -> None:
        if self._form_workspace_mode not in {"preview", "fill"}:
            return
        field = next(
            (item for item in self.engine.form_fields() if item.xref == field_xref),
            None,
        )
        if field is None or field.read_only:
            return
        if self._form_workspace_mode == "preview":
            self._form_preview_values[field_xref] = value
            self.statusBar().showMessage(self.trx("form_preview_value_changed"), 1800)
            return
        if field.type_code == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
            return
        if self._materialize_pdf_change(
            lambda engine: engine.bytes_with_form_value(
                self._matching_form_xref(engine, field), value
            ),
            field.page_index,
            self.trx("fill_and_sign"),
        ):
            self._operation_log.record(
                "form_field_updated",
                operation="form_fill",
                outcome="succeeded",
                page_index=field.page_index,
            )
            self.statusBar().showMessage(self.trx("form_value_saved"), 3000)

    def clear_form_values(self) -> None:
        if not self.engine.is_open or self._form_workspace_mode != "fill":
            return
        answer = QMessageBox.question(
            self,
            self.trx("fill_and_sign"),
            self.trx("clear_form_question"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if self._materialize_pdf_change(
            lambda engine: engine.bytes_with_cleared_form_values(),
            self.current_page,
            self.trx("fill_and_sign"),
        ):
            self._form_preview_values.clear()
            self._operation_log.record(
                "form_values_cleared",
                operation="form_fill",
                outcome="succeeded",
            )
            self.statusBar().showMessage(self.trx("form_values_cleared"), 3500)

    def _form_signature_requested(self, field_xref: int) -> None:
        record_signature_trace("field_request_received", context="field")
        field = next(
            (item for item in self.engine.form_fields() if item.xref == field_xref),
            None,
        )
        if field is None or field.type_code != pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
            record_signature_trace("handled_error", context="field", outcome="failed")
            return
        record_signature_trace(
            "field_resolved",
            context="field",
            page_index=field.page_index,
            read_only=field.read_only,
            required=field.required,
        )
        if self._form_workspace_mode == "preview":
            self._form_preview_values[field_xref] = FORM_VISUAL_SIGNATURE_VALUE
            self._render_current_page()
            self.statusBar().showMessage(self.trx("signature_preview_only"), 4500)
            return
        if self._form_workspace_mode != "fill" or field.read_only:
            return
        try:
            record_signature_trace(
                "dialog_opening", context="field", page_index=field.page_index
            )
            dialog = SignatureDialog(self, self.trx)
            if not dialog.exec():
                record_signature_trace(
                    "dialog_cancelled", context="field", page_index=field.page_index
                )
                return
            record_signature_trace(
                "dialog_accepted", context="field", page_index=field.page_index
            )
            payload, _width, rotation, description = dialog.signature_data()
            image = QImage.fromData(payload)
            if image.isNull():
                raise ValueError(self.trx("invalid_image_data"))
            record_signature_trace(
                "payload_ready",
                context="field",
                page_index=field.page_index,
                image_width=image.width(),
                image_height=image.height(),
                payload_bytes=len(payload),
            )
        except Exception as exc:
            record_signature_trace("handled_error", context="field", outcome="failed")
            QMessageBox.critical(self, self.trx("unable_create_signature"), str(exc))
            return
        x0, y0, x1, y1 = field.bbox
        available_width = max(1.0, x1 - x0)
        available_height = max(1.0, y1 - y0)
        visual_width, visual_height = _rotated_outer_size(
            image.width(), image.height(), rotation
        )
        factor = min(
            available_width / max(1.0, visual_width),
            available_height / max(1.0, visual_height),
        )
        width = max(1.0, visual_width * factor)
        height = max(1.0, visual_height * factor)
        bbox = (
            x0 + (available_width - width) / 2,
            y0 + (available_height - height) / 2,
            x0 + (available_width + width) / 2,
            y0 + (available_height + height) / 2,
        )
        record_signature_trace(
            "bbox_ready", context="field", page_index=field.page_index
        )
        state = self._capture_state()
        record_signature_trace(
            "state_captured",
            context="field",
            page_index=field.page_index,
            signature_count=len(state.signatures),
        )
        state.signatures.append(
            SignaturePlacement(
                field.page_index,
                bbox,
                payload,
                description,
                uuid4().hex,
                _normalized_angle(rotation),
            )
        )
        record_signature_trace(
            "state_appended",
            context="field",
            page_index=field.page_index,
            signature_count=len(state.signatures),
        )
        record_signature_trace(
            "state_push_started", context="field", page_index=field.page_index
        )
        self._push_state(state, field.page_index)
        record_signature_trace(
            "state_push_finished",
            context="field",
            page_index=field.page_index,
            signature_count=len(state.signatures),
        )
        record_signature_trace("notice_started", context="field")
        QMessageBox.information(
            self,
            self.trx("visual_signature_title"),
            self.trx("visual_signature_not_digital"),
        )
        record_signature_trace("notice_finished", context="field")

    def _create_form_field(
        self,
        bbox: tuple[float, float, float, float],
        page_generation: int,
    ) -> None:
        spec = self._pending_form_field
        target_page = self._form_field_target_page
        self._pending_form_field = None
        self._form_field_target_page = None
        if (
            spec is None
            or target_page is None
            or target_page != self.current_page
            or page_generation != self.page_view._page_generation
            or not self.engine.is_open
        ):
            return
        if self._materialize_pdf_change(
            lambda engine: engine.bytes_with_new_form_field(target_page, bbox, spec),
            target_page,
            self.trx("forms"),
        ):
            self.right_sidebar.setCurrentIndex(self.forms_tool_index)
            self._operation_log.record(
                "form_field_created",
                operation="form_create",
                outcome="succeeded",
                page_index=target_page,
            )
            self.statusBar().showMessage(self.trx("form_created"), 5000)

    def delete_selected_form_field(self) -> None:
        field = self._form_field_for_item(self.forms_list.currentItem())
        if field is None:
            return
        answer = QMessageBox.question(
            self,
            self.trx("forms"),
            self.trx("delete_form_field_question"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if self._materialize_pdf_change(
            lambda engine: engine.bytes_without_form_field(
                self._matching_form_xref(engine, field)
            ),
            field.page_index,
            self.trx("forms"),
        ):
            self._operation_log.record(
                "form_field_deleted",
                operation="form_delete",
                outcome="succeeded",
                page_index=field.page_index,
            )
            self.statusBar().showMessage(self.trx("form_deleted"), 5000)

    def edit_selected_form_field(self) -> None:
        field = self._form_field_for_item(self.forms_list.currentItem())
        if field is None:
            return
        if field.read_only:
            QMessageBox.information(
                self,
                self.trx("forms"),
                self.trx("form_read_only_message"),
            )
            return

        accepted = True
        value: str | bool
        if field.type_code == pymupdf.PDF_WIDGET_TYPE_TEXT:
            if field.multiline:
                value, accepted = QInputDialog.getMultiLineText(
                    self,
                    self.trx("edit_form_field"),
                    field.label or field.name or self.trx("form_value"),
                    field.value,
                )
            else:
                value, accepted = QInputDialog.getText(
                    self,
                    self.trx("edit_form_field"),
                    field.label or field.name or self.trx("form_value"),
                    QLineEdit.Normal,
                    field.value,
                )
        elif field.type_code == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
            value = not field.checked
        elif field.type_code == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
            if field.checked:
                return
            value = True
        elif field.type_code in (
            pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
            pymupdf.PDF_WIDGET_TYPE_LISTBOX,
        ):
            if not field.choices:
                QMessageBox.information(
                    self,
                    self.trx("forms"),
                    self.trx("form_no_choices"),
                )
                return
            current = field.choices.index(field.value) if field.value in field.choices else 0
            value, accepted = QInputDialog.getItem(
                self,
                self.trx("edit_form_field"),
                field.label or field.name or self.trx("form_value"),
                list(field.choices),
                current,
                False,
            )
        else:
            QMessageBox.information(
                self,
                self.trx("forms"),
                self.trx("form_unsupported"),
            )
            return
        if not accepted:
            return
        if isinstance(value, str) and value == field.value:
            return
        if isinstance(value, bool) and value == field.checked:
            return

        if self._materialize_pdf_change(
            lambda engine: engine.bytes_with_form_value(
                self._matching_form_xref(engine, field),
                value,
            ),
            field.page_index,
            self.trx("forms"),
        ):
            self._operation_log.record(
                "form_field_updated",
                operation="form_fill",
                outcome="succeeded",
                page_index=field.page_index,
            )
            self.statusBar().showMessage(self.trx("form_updated"), 4000)

    def _place_comment(self, scene_x: float, scene_y: float) -> None:
        if not self.engine.is_open or not self.page_view.comment_placement_mode:
            return
        content, accepted = QInputDialog.getMultiLineText(
            self,
            self.trx("add_comment"),
            self.trx("comment_text_prompt"),
        )
        if not accepted:
            self.cancel_special_mode()
            return
        if not content.strip():
            QMessageBox.information(
                self,
                self.trx("add_comment"),
                self.trx("comment_empty"),
            )
            return
        page_index = self.current_page
        point = (scene_x / self.render_scale, scene_y / self.render_scale)
        self.cancel_special_mode()
        if self._materialize_annotation_change(
            lambda engine: engine.bytes_with_text_comment(page_index, point, content),
            page_index,
        ):
            self._operation_log.record(
                "annotation_added",
                operation="comment_add",
                outcome="succeeded",
                page_index=page_index,
            )
            self.statusBar().showMessage(self.trx("comment_added"), 4000)

    def _highlight_text(self, kind: str, key: str) -> None:
        spec = self._text_spec(kind, key)
        if spec is None:
            return
        self.cancel_special_mode()
        if self._materialize_annotation_change(
            lambda engine: engine.bytes_with_highlight(spec.page_index, spec.bbox),
            spec.page_index,
        ):
            self._operation_log.record(
                "annotation_added",
                operation="highlight_add",
                outcome="succeeded",
                page_index=spec.page_index,
            )
            self.statusBar().showMessage(self.trx("highlight_added"), 4000)

    def edit_selected_comment(self) -> None:
        annotation = self._annotation_for_item(self.comments_list.currentItem())
        if annotation is None:
            return
        content, accepted = QInputDialog.getMultiLineText(
            self,
            self.trx("edit_comment"),
            self.trx("comment_text_prompt"),
            annotation.content,
        )
        if not accepted or content == annotation.content:
            return
        if self._materialize_annotation_change(
            lambda engine: engine.bytes_with_annotation_content(annotation.xref, content),
            annotation.page_index,
        ):
            self._operation_log.record(
                "annotation_updated",
                operation="annotation_update",
                outcome="succeeded",
                page_index=annotation.page_index,
            )
            self.statusBar().showMessage(self.trx("comment_updated"), 4000)

    def delete_selected_annotation(self) -> None:
        annotation = self._annotation_for_item(self.comments_list.currentItem())
        if annotation is None:
            return
        answer = QMessageBox.question(
            self,
            self.trx("delete_annotation"),
            self.trx("delete_annotation_question"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if self._materialize_annotation_change(
            lambda engine: engine.bytes_without_annotation(annotation.xref),
            annotation.page_index,
        ):
            self._operation_log.record(
                "annotation_deleted",
                operation="annotation_delete",
                outcome="succeeded",
                page_index=annotation.page_index,
            )
            self.statusBar().showMessage(self.trx("annotation_deleted"), 4000)

    def _begin_visual_placement(
        self,
        kind: str,
        payload: bytes,
        width: float,
        description: str,
        rotation: float = 0.0,
    ) -> None:
        self.cancel_special_mode()
        self._pending_visual = (kind, payload, width, description, rotation)
        self.page_view.set_placement_mode(True)
        self.statusBar().showMessage(
            self.trx("visual_place_hint", kind=kind)
        )

    def _place_visual(self, scene_x: float, scene_y: float) -> None:
        if not self.engine.is_open or self._pending_visual is None:
            return
        kind, payload, desired_width, description, rotation = self._pending_visual
        image = QImage.fromData(payload)
        if image.isNull():
            QMessageBox.critical(
                self,
                self.trx("unable_place_image"),
                self.trx("invalid_image_data"),
            )
            self.cancel_special_mode()
            return

        page_rect = self.engine.page_rect(self.current_page)
        width = min(desired_width, page_rect.width)
        visual_width, visual_height = _rotated_outer_size(
            image.width(), image.height(), rotation
        )
        height = max(8.0, width * visual_height / max(1.0, visual_width))
        height = min(height, page_rect.height)
        center_x = scene_x / self.render_scale
        center_y = scene_y / self.render_scale
        x0 = min(max(page_rect.x0, center_x - width / 2), page_rect.x1 - width)
        y0 = min(max(page_rect.y0, center_y - height / 2), page_rect.y1 - height)
        bbox = (x0, y0, x0 + width, y0 + height)
        key = uuid4().hex
        state = self._capture_state()
        if kind == "signature":
            state.signatures.append(
                SignaturePlacement(
                    self.current_page,
                    bbox,
                    payload,
                    description,
                    key,
                    _normalized_angle(rotation),
                )
            )
        else:
            state.inserted_images.append(
                ImagePlacement(
                    key,
                    self.current_page,
                    bbox,
                    payload,
                    description,
                    _normalized_angle(rotation),
                )
            )
        self.cancel_special_mode()
        self._push_state(state, self.current_page)
        if kind == "signature":
            message = self.trx("signature_inserted")
        else:
            message = self.trx("image_inserted")
        self.statusBar().showMessage(message, 5000)

    def _transform_visual(
        self,
        kind: str,
        key: str,
        bbox: tuple[float, float, float, float],
        rotation: float,
    ) -> None:
        if not self.engine.is_open:
            return
        source_run = None
        if kind == "signature":
            original = next((item for item in self.signatures if item.key == key), None)
        elif kind == "inserted":
            original = next((item for item in self.inserted_images if item.key == key), None)
        elif kind == "source":
            source_run = self.engine.find_image_run(key)
            original = source_run
            if source_run is not None and any(
                item.run.key == key for item in self.deleted_images
            ):
                original = None
        else:
            return
        if original is None:
            return
        page_rect = self.engine.page_rect(original.page_index)
        x0, y0, x1, y1 = bbox
        width = max(1.0, x1 - x0)
        height = max(1.0, y1 - y0)
        fit = min(1.0, page_rect.width / width, page_rect.height / height)
        center_x = (x0 + x1) / 2
        center_y = (y0 + y1) / 2
        width *= fit
        height *= fit
        x0 = center_x - width / 2
        y0 = center_y - height / 2
        x1 = center_x + width / 2
        y1 = center_y + height / 2
        if x0 < page_rect.x0:
            x1 += page_rect.x0 - x0
            x0 = page_rect.x0
        if x1 > page_rect.x1:
            x0 -= x1 - page_rect.x1
            x1 = page_rect.x1
        if y0 < page_rect.y0:
            y1 += page_rect.y0 - y0
            y0 = page_rect.y0
        if y1 > page_rect.y1:
            y0 -= y1 - page_rect.y1
            y1 = page_rect.y1
        normalized_rotation = _normalized_angle(rotation)
        normalized_bbox = (x0, y0, x1, y1)
        if (
            all(abs(left - right) < 0.01 for left, right in zip(original.bbox, normalized_bbox))
            and abs(_normalized_angle(original.rotation_degrees - normalized_rotation)) < 0.01
        ):
            return
        state = self._capture_state()
        if kind == "signature":
            state.signatures = [
                replace(item, bbox=normalized_bbox, rotation_degrees=normalized_rotation)
                if item.key == key
                else item
                for item in state.signatures
            ]
        elif kind == "inserted":
            state.inserted_images = [
                replace(item, bbox=normalized_bbox, rotation_degrees=normalized_rotation)
                if item.key == key
                else item
                for item in state.inserted_images
            ]
        elif kind == "source" and source_run is not None:
            try:
                payload = self.engine.extract_image_payload(source_run)
            except Exception as exc:
                QMessageBox.critical(self, self.trx("edit_original_image"), str(exc))
                self._render_current_page()
                return
            state.deleted_images.append(
                ImageDeletion(source_run, fill_removed_area=False)
            )
            state.inserted_images.append(
                ImagePlacement(
                    key,
                    source_run.page_index,
                    normalized_bbox,
                    payload,
                    self.trx("original_image"),
                    normalized_rotation,
                    False,
                )
            )
        else:
            return
        self.page_view.selected_signature_key = key
        self._push_state(state, original.page_index)
        self.statusBar().showMessage(
            self.trx("signature_updated" if kind == "signature" else "image_updated"),
            4000,
        )

    def _signature_selection_changed(self, key: str | None) -> None:
        if key:
            message_key = (
                "original_image_ready"
                if self.page_view.selected_visual_ref == ("source", key)
                else "signature_select_hint"
            )
            self.statusBar().showMessage(
                self.trx(message_key),
                5000,
            )

    def start_delete_image(self) -> None:
        if not self.engine.is_open:
            return
        source_keys = {item.run.key for item in self.deleted_images}
        candidates = [item for item in self.engine.image_runs(self.current_page) if item.key not in source_keys]
        candidates.extend(item for item in self.inserted_images if item.page_index == self.current_page)
        candidates.extend(item for item in self.signatures if item.page_index == self.current_page)
        if not candidates:
            QMessageBox.information(self, self.trx("no_image"), self.trx("no_image_message"))
            return
        self.cancel_special_mode()
        self.page_view.set_delete_image_mode(True)
        self.statusBar().showMessage(self.trx("delete_visual_hint"))

    def _delete_visual(self, kind: str, key: str) -> None:
        if not self.engine.is_open:
            return
        state = self._capture_state()
        if kind == "source":
            run = self.engine.find_image_run(key)
            if run is None:
                return
            state.deleted_images.append(ImageDeletion(run))
        elif kind == "inserted":
            state.inserted_images = [item for item in state.inserted_images if item.key != key]
        elif kind == "signature":
            state.signatures = [item for item in state.signatures if item.key != key]
        else:
            return
        self.cancel_special_mode()
        self._push_state(state, self.current_page)
        self._operation_log.record(
            "visual_deleted",
            operation="visual_delete",
            outcome="succeeded",
            page_index=self.current_page,
        )
        self.statusBar().showMessage(self.trx("image_removed"), 4000)

    def cancel_special_mode(self) -> None:
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        self._pending_visual = None
        self._pending_text_box = None
        self._redaction_target_page = None
        self._pending_form_field = None
        self._form_field_target_page = None
        self.page_view.set_placement_mode(False)
        self.page_view.set_comment_placement_mode(False)
        self.page_view.set_delete_image_mode(False)
        self.page_view.set_source_image_edit_mode(False)
        self.page_view.set_text_box_mode(False)
        self.page_view.set_redaction_mode(False)
        self.page_view.set_form_field_mode(False)
        self.statusBar().clearMessage()

    def step_zoom(self, direction: int) -> None:
        current = self.render_scale * 100
        if direction > 0:
            target = next((level for level in ZOOM_LEVELS if level > current + 0.1), ZOOM_LEVELS[-1])
        else:
            target = next((level for level in reversed(ZOOM_LEVELS) if level < current - 0.1), ZOOM_LEVELS[0])
        self.set_zoom_percent(float(target))

    def set_zoom_percent(self, percent: float) -> None:
        if not self.engine.is_open:
            return
        requested = min(4.0, max(0.25, percent / 100.0))
        maximum = self.engine.max_render_scale(self.current_page)
        self.render_scale = min(requested, maximum)
        if self.render_scale + 0.001 < requested:
            self.statusBar().showMessage(
                f"{self.trx('current_zoom')}: {self.render_scale * 100:.0f}%",
                4000,
            )
        self._render_current_page()

    def _zoom_entered(self, *args) -> None:
        text = self.zoom_combo.currentText().strip().replace("%", "").replace(",", ".")
        try:
            percent = float(text)
        except ValueError:
            self._sync_zoom_display()
            return
        self.set_zoom_percent(percent)

    def _sync_zoom_display(self) -> None:
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentText(f"{self.render_scale * 100:.0f}%")
        self.zoom_combo.blockSignals(False)

    def fit_width(self) -> None:
        if not self.engine.is_open:
            return
        available = max(100, self.page_view.viewport().width() - 28)
        page_width = self.engine.page_rect(self.current_page).width
        self.set_zoom_percent(100 * available / max(1.0, page_width))

    def print_document(self) -> None:
        if not self.engine.is_open:
            return
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)

        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(
            self.document_path.name if self.document_path else self.trx("untitled")
        )
        first_page = self.engine.page_rect(0)
        portrait_size = QSizeF(
            min(first_page.width, first_page.height),
            max(first_page.width, first_page.height),
        )
        printer.setPageSize(QPageSize(portrait_size, QPageSize.Point, "PDF page"))
        printer.setPageOrientation(
            QPageLayout.Landscape
            if first_page.width > first_page.height
            else QPageLayout.Portrait
        )

        preview = QPrintPreviewDialog(printer, self)
        preview.setWindowTitle(f"Nettongia PDF Editor - {self.trx('print_preview')}")
        preview.resize(1100, 800)
        preview_errors: list[Exception] = []

        def paint_preview(preview_printer: QPrinter) -> None:
            if preview_errors:
                return
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._render_print_job(
                    preview_printer,
                    list(range(self.engine.page_count)),
                )
            except Exception as exc:
                preview_errors.append(exc)
            finally:
                QApplication.restoreOverrideCursor()

        preview.paintRequested.connect(paint_preview)
        self._redirect_preview_print_action(preview, printer)
        preview.exec()
        if preview_errors:
            QMessageBox.critical(
                self,
                self.trx("print_failed"),
                str(preview_errors[0]),
            )

    def _redirect_preview_print_action(
        self,
        preview: QPrintPreviewDialog,
        printer: QPrinter,
    ) -> None:
        toolbars = preview.findChildren(QToolBar)
        if not toolbars:
            return
        actions = toolbars[0].actions()
        if not actions or actions[-1].isSeparator():
            return
        print_action = actions[-1]
        try:
            print_action.triggered.disconnect()
        except RuntimeError:
            return
        print_action.triggered.connect(
            lambda: self._print_from_preview(preview, printer)
        )

    def _print_from_preview(
        self,
        preview: QPrintPreviewDialog,
        printer: QPrinter,
    ) -> None:
        # Windows labels its native print window with the host executable name
        # ("Python" when the source version is launched via pythonw.exe). Use
        # Qt's application-owned dialog for this operation so its title is
        # under our control. Restore the application attribute immediately so
        # file pickers and other dialogs retain their normal native appearance.
        previous_non_native = QApplication.testAttribute(
            Qt.AA_DontUseNativeDialogs
        )
        QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
        try:
            dialog = QPrintDialog(printer, preview)
            dialog.setWindowTitle(
                f"Nettongia PDF Editor - {self.trx('print').rstrip('.')}"
            )
            dialog.setMinMax(1, self.engine.page_count)
            dialog.setFromTo(1, self.engine.page_count)
            dialog.setOption(QAbstractPrintDialog.PrintPageRange, True)
            dialog.setOption(QAbstractPrintDialog.PrintCurrentPage, True)
            accepted = bool(dialog.exec())
        finally:
            QApplication.setAttribute(
                Qt.AA_DontUseNativeDialogs,
                previous_non_native,
            )
        if not accepted:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            preview_widget = preview.findChild(QPrintPreviewWidget)
            current_preview_page = (
                preview_widget.currentPage() - 1
                if preview_widget is not None
                else self.current_page
            )
            page_count = self._render_print_job(
                printer,
                self._print_page_indices(printer, current_preview_page),
            )
        except Exception as exc:
            QMessageBox.critical(preview, self.trx("print_failed"), str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(
            self.trx("print_complete", count=page_count),
            5000,
        )
        preview.accept()

    def _print_page_indices(
        self,
        printer: QPrinter,
        current_page: int | None = None,
    ) -> list[int]:
        if printer.printRange() in (QPrinter.CurrentPage, QPrinter.Selection):
            selected_page = self.current_page if current_page is None else current_page
            page_indices = [
                min(self.engine.page_count - 1, max(0, selected_page))
            ]
        elif printer.printRange() == QPrinter.PageRange:
            page_indices = []
            ranges = printer.pageRanges().toRangeList()
            if ranges:
                for page_range in ranges:
                    first = max(1, page_range.from_)
                    last = min(self.engine.page_count, page_range.to)
                    page_indices.extend(range(first - 1, last))
            else:
                first = min(self.engine.page_count, max(1, printer.fromPage() or 1))
                last = min(
                    self.engine.page_count,
                    max(first, printer.toPage() or self.engine.page_count),
                )
                page_indices = list(range(first - 1, last))
        else:
            page_indices = list(range(self.engine.page_count))
        if printer.pageOrder() == QPrinter.LastPageFirst:
            page_indices.reverse()
        return page_indices

    def _render_print_job(self, printer: QPrinter, page_indices: list[int]) -> int:
        if not page_indices:
            return 0
        document = self.engine.build_document(
            self.edits.values(),
            self.signatures,
            self.inserted_images,
            self.deleted_images,
            self.inserted_texts,
        )
        painter = QPainter()
        try:
            printer.setFullPage(True)
            if not painter.begin(printer):
                raise RuntimeError(self.trx("print_failed"))
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            printer_resolution = max(72, printer.resolution())
            render_scale = min(300, max(150, printer_resolution)) / 72.0

            for ordinal, page_index in enumerate(page_indices):
                if ordinal and not printer.newPage():
                    raise RuntimeError(self.trx("print_failed"))
                page = document[page_index]
                # Printing uses the same raster path as the preview.  Apply
                # the page-aware memory cap here as well, otherwise an A0
                # page could still allocate an unsafe buffer even when the
                # editor view itself was capped.
                page_scale = min(render_scale, self.engine.max_render_scale(page_index))
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(page_scale, page_scale),
                    alpha=False,
                    annots=True,
                )
                image = QImage(
                    pixmap.samples,
                    pixmap.width,
                    pixmap.height,
                    pixmap.stride,
                    QImage.Format_RGB888,
                ).copy()

                paint_rect = QRectF(
                    printer.pageLayout().paintRectPixels(printer_resolution)
                )
                fitted_size = QSizeF(image.width(), image.height())
                fitted_size.scale(paint_rect.size(), Qt.KeepAspectRatio)
                target = QRectF(
                    paint_rect.x() + (paint_rect.width() - fitted_size.width()) / 2,
                    paint_rect.y() + (paint_rect.height() - fitted_size.height()) / 2,
                    fitted_size.width(),
                    fitted_size.height(),
                )
                painter.drawImage(target, image)
                QApplication.processEvents()
        finally:
            if painter.isActive():
                painter.end()
            document.close()
        return len(page_indices)

    def _choose_ocr_language(self) -> str | None:
        languages = available_ocr_languages()
        if not languages:
            QMessageBox.warning(self, self.trx("ocr_title"), self.trx("ocr_unavailable"))
            return None
        preferred = {
            "cs": "ces", "de": "deu", "en": "eng", "fr": "fra",
            "hu": "hun", "it": "ita", "nl": "nld", "pl": "pol",
            "pt": "por", "ro": "ron", "ru": "rus", "sk": "slk",
            "es": "spa", "tr": "tur", "uk": "ukr",
        }.get(self.language_code, "eng")
        codes = list(languages)
        labels = [f"{languages[code]} ({code})" for code in codes]
        selected_index = codes.index(preferred) if preferred in codes else 0
        label, accepted = QInputDialog.getItem(
            self,
            self.trx("ocr_title"),
            self.trx("ocr_language_prompt"),
            labels,
            selected_index,
            False,
        )
        return codes[labels.index(label)] if accepted else None

    def ocr_current_page(self) -> None:
        if not self.engine.is_open or self._document_write_in_progress():
            return
        language = self._choose_ocr_language()
        if language is not None:
            self._start_ocr((self.current_page,), language)

    def ocr_document(self) -> None:
        if not self.engine.is_open or self._document_write_in_progress():
            return
        language = self._choose_ocr_language()
        if language is not None:
            self._start_ocr(tuple(range(self.engine.page_count)), language)

    def _start_ocr(self, page_indices: tuple[int, ...], language: str) -> bool:
        if not self.engine.is_open or self._document_write_in_progress():
            return False
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        context = OcrContext(
            document_generation=self._document_generation,
            content_revision=self._content_revision,
        )
        try:
            self._ocr_coordinator.start(
                self.engine.source_bytes,
                page_indices,
                language,
                context=context,
                dpi=200,
            )
        except Exception as exc:
            QMessageBox.critical(self, self.trx("ocr_title"), str(exc))
            return False
        progress = QProgressDialog(
            self.trx("ocr_working"), self.trx("cancel"), 0, 0, self
        )
        progress.setWindowTitle(self.trx("ocr_title"))
        progress.setWindowModality(Qt.NonModal)
        progress.setAutoClose(False)
        progress.canceled.connect(self._cancel_ocr)
        self._ocr_progress = progress
        self._update_actions()
        progress.show()
        self._operation_log.record(
            "ocr_started",
            worker="ocr",
            operation="ocr",
            outcome="started",
            processed_pages=len(page_indices),
            language=language,
            content_revision=self._content_revision,
        )
        return True

    def _cancel_ocr(self) -> None:
        cancelled = self._ocr_coordinator.cancel()
        if self._ocr_progress is not None:
            self._ocr_progress.close()
            self._ocr_progress.deleteLater()
        self._ocr_progress = None
        self._update_actions()
        if cancelled:
            self._operation_log.record(
                "ocr_finished",
                worker="ocr",
                operation="ocr",
                outcome="cancelled",
            )

    def _ocr_finished(
        self,
        outcome: OcrOutcome,
    ) -> None:
        progress = self._ocr_progress
        valid_context = (
            outcome.context.document_generation == self._document_generation
            and outcome.context.content_revision == self._content_revision
        )
        self._ocr_progress = None
        if progress is not None:
            progress.close()
            progress.deleteLater()
        log_details: dict[str, object] = {
            "worker": "ocr",
            "operation": "ocr",
            "outcome": "discarded" if not valid_context else "failed" if outcome.error else "succeeded",
            "reason": (
                "stale_result"
                if not valid_context
                else error_reason(outcome.error)
                if outcome.error
                else "unknown"
            ),
        }
        if outcome.result is not None:
            log_details["processed_pages"] = outcome.result.get("processed_pages", 0)
            log_details["words_inserted"] = outcome.result.get("words_inserted", 0)
        self._operation_log.record("ocr_finished", **log_details)
        try:
            if not valid_context:
                self.statusBar().showMessage(self.trx("ocr_discarded"), 6000)
            elif outcome.error is not None:
                QMessageBox.critical(self, self.trx("ocr_title"), outcome.error)
            elif (
                outcome.result is not None
                and outcome.result["processed_pages"]
                and outcome.output_bytes is not None
            ):
                state = self._capture_state()
                state.pdf_bytes = outcome.output_bytes
                self._push_state(state, self.current_page)
                self.statusBar().showMessage(
                    self.trx(
                        "ocr_complete",
                        pages=outcome.result["processed_pages"],
                        words=outcome.result["words_inserted"],
                    ),
                    8000,
                )
            else:
                self.statusBar().showMessage(self.trx("ocr_nothing"), 7000)
        finally:
            self._update_actions()

    def save_document(
        self,
        show_confirmation: bool = False,
        *,
        background: bool = True,
    ) -> bool:
        if not self.engine.is_open:
            return False
        if self._document_write_in_progress():
            return False
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        if self.save_target_path is None:
            return self.save_as(background=background)
        if background:
            return self._start_document_write(
                self.save_target_path,
                show_confirmation=show_confirmation,
            )
        return self._save_to_path(
            self.save_target_path,
            show_confirmation=show_confirmation,
        )

    def save_as(self, _checked: bool = False, *, background: bool = True) -> bool:
        if not self.engine.is_open:
            return False
        if self._document_write_in_progress():
            return False
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        source = self.document_path
        if self.save_target_path is not None:
            suggested = self.save_target_path
        else:
            suggested = source.with_name(f"{source.stem}_edited.pdf") if source else Path(self.trx("untitled"))
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.trx("save_pdf_title"),
            str(suggested),
            self.trx("pdf_filter"),
        )
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if background:
            return self._start_document_write(
                Path(path),
                show_confirmation=True,
            )
        return self._save_to_path(Path(path), show_confirmation=True)

    def save_copy(self, _checked: bool = False, *, background: bool = True) -> bool:
        """Write a snapshot without changing the active document's identity."""

        if not self.engine.is_open or self._document_write_in_progress():
            return False
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        source = self.save_target_path or self.document_path
        suggested = (
            source.with_name(f"{source.stem}_copy.pdf")
            if source is not None
            else Path("document_copy.pdf")
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.trx("save_copy").rstrip("."),
            str(suggested),
            self.trx("pdf_filter"),
        )
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if background:
            return self._start_document_write(
                Path(path),
                show_confirmation=True,
                update_document_identity=False,
            )
        return self._save_to_path(
            Path(path),
            show_confirmation=True,
            update_document_identity=False,
        )

    def _document_write_in_progress(self, notify: bool = True) -> bool:
        if self._write_process is None and self._ocr_process is None:
            return False
        if notify:
            progress = self._write_progress or self._ocr_progress
            if progress is not None:
                progress.show()
                progress.raise_()
                progress.activateWindow()
                self.statusBar().showMessage(progress.labelText(), 4000)
        return True

    def _confirm_document_write_compatibility(self) -> bool:
        if self._inspection_process is not None:
            self.statusBar().showMessage(self.trx("compatibility_checking"), 5000)
            return False
        report = self._inspection_report
        if report is None and self._inspection_error and not self._compatibility_risk_acknowledged:
            answer = QMessageBox.warning(
                self,
                self.trx("document_compatibility").rstrip("."),
                self.trx("compatibility_failed", error=self._inspection_error),
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer == QMessageBox.Yes:
                self._compatibility_risk_acknowledged = True
                return True
            return False
        if (
            report is None
            or not report.signed_digital_signatures
            or self._compatibility_risk_acknowledged
        ):
            return True
        answer = QMessageBox.warning(
            self,
            self.trx("document_compatibility").rstrip("."),
            self.trx("compatibility_signature_risk"),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer == QMessageBox.Yes:
            self._compatibility_risk_acknowledged = True
            return True
        return False

    def _start_document_write(
        self,
        path: Path,
        *,
        show_confirmation: bool = False,
        compression_profile: str | None = None,
        update_document_identity: bool = True,
    ) -> bool:
        if not self.engine.is_open or self._document_write_in_progress():
            return False
        if not self._confirm_document_write_compatibility():
            return False
        state = self._capture_state()
        normalized_path = self._normalized_file_path(path)
        snapshot = RecoverySnapshot(
            pdf_bytes=state.pdf_bytes,
            edits=tuple(sorted(state.edits.values(), key=lambda item: item.run.key)),
            inserted_texts=tuple(state.inserted_texts),
            signatures=tuple(state.signatures),
            inserted_images=tuple(state.inserted_images),
            deleted_images=tuple(state.deleted_images),
            document_path=str(self.document_path) if self.document_path else None,
            save_target_path=str(self.save_target_path) if self.save_target_path else None,
            current_page=self.current_page,
            render_scale=self.render_scale,
        )
        context = DocumentWriteContext(
            path=normalized_path,
            document_generation=self._document_generation,
            content_revision=self._content_revision,
            compression_profile=compression_profile,
            show_confirmation=show_confirmation,
            update_document_identity=update_document_identity,
        )
        try:
            self._document_writer.start(snapshot, context)
        except Exception as exc:
            QMessageBox.critical(
                self,
                self.trx(
                    "compression_failed"
                    if compression_profile is not None
                    else "unable_save"
                ),
                str(exc),
            )
            return False

        operation = (
            "compress"
            if compression_profile is not None
            else "save_copy"
            if not update_document_identity
            else "save"
        )
        self._operation_log.record(
            "document_write_started",
            worker="write",
            operation=operation,
            outcome="started",
            copy=not update_document_identity,
            profile=compression_profile or "none",
            content_revision=context.content_revision,
        )

        label = (
            self.trx("compress_title")
            if compression_profile is not None
            else self.trx("save_pdf_title")
        )
        progress = QProgressDialog(label, self.trx("cancel"), 0, 0, self)
        progress.setObjectName("documentWriteProgress")
        progress.setWindowTitle("Nettongia PDF Editor")
        progress.setWindowModality(Qt.NonModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self._cancel_document_write)
        progress.show()
        self._write_progress = progress
        self.statusBar().showMessage(label)
        self._update_actions()
        return True

    def _cancel_document_write(self) -> None:
        if not self._document_writer.cancel():
            return
        progress = self._write_progress
        if progress is not None:
            progress.setLabelText(f"{self.trx('cancel')}…")
            progress.setCancelButton(None)

    def _document_write_finished(
        self,
        outcome: DocumentWriteOutcome,
    ) -> None:
        context = outcome.context
        path = context.path
        compression_profile = context.compression_profile
        show_confirmation = context.show_confirmation
        same_document, _same_revision = context.matches(self._document_session)
        progress = self._write_progress
        self._write_progress = None
        if progress is not None:
            progress.close()
            progress.deleteLater()
        self.statusBar().clearMessage()
        self._update_actions()

        operation = (
            "compress"
            if compression_profile is not None
            else "save_copy"
            if not context.update_document_identity
            else "save"
        )
        self._operation_log.record(
            "document_write_finished",
            worker="write",
            operation=operation,
            outcome=(
                "cancelled"
                if outcome.cancelled
                else "failed"
                if outcome.error is not None
                else "succeeded"
            ),
            reason=error_reason(outcome.error) if outcome.error else "unknown",
            copy=not context.update_document_identity,
            profile=compression_profile or "none",
            content_revision=context.content_revision,
        )

        if outcome.cancelled:
            self.statusBar().showMessage(self.trx("cancel"), 3000)
            return
        if outcome.error is not None:
            QMessageBox.critical(
                self,
                self.trx(
                    "compression_failed"
                    if compression_profile is not None
                    else "unable_save"
                ),
                outcome.error,
            )
            return
        if compression_profile is not None:
            if not isinstance(outcome.result, CompressionResult):
                QMessageBox.critical(
                    self,
                    self.trx("compression_failed"),
                    self.trx("compression_failed"),
                )
                return
            self._show_compression_result(path, outcome.result)
            return
        if not same_document or not self.engine.is_open:
            return

        if not context.update_document_identity:
            if show_confirmation:
                QMessageBox.information(
                    self,
                    self.trx("pdf_saved"),
                    self.trx("pdf_saved_message", path=path),
                )
            else:
                self.statusBar().showMessage(self.trx("saved_status", path=path), 3000)
            return

        current_snapshot = self._document_session.saved(
            path,
            history_index=self.history_index,
            snapshot_revision=context.content_revision,
        )
        if current_snapshot:
            self._clear_recovery(wait=False)
        self._add_recent_file(path)
        self._update_window_title()
        if show_confirmation:
            QMessageBox.information(
                self,
                self.trx("pdf_saved"),
                self.trx("pdf_saved_message", path=path),
            )
        else:
            self.statusBar().showMessage(self.trx("saved_status", path=path), 3000)

    def _save_to_path(
        self,
        path: Path,
        show_confirmation: bool,
        *,
        update_document_identity: bool = True,
    ) -> bool:
        if not self._confirm_document_write_compatibility():
            return False
        operation = "save_copy" if not update_document_identity else "save"
        self._operation_log.record(
            "document_write_started",
            worker="write",
            operation=operation,
            outcome="started",
            copy=not update_document_identity,
            profile="none",
            content_revision=self._content_revision,
        )
        try:
            self.engine.save(
                str(path),
                self.edits.values(),
                self.signatures,
                self.inserted_images,
                self.deleted_images,
                self.inserted_texts,
            )
        except Exception as exc:
            self._operation_log.record(
                "document_write_finished",
                worker="write",
                operation=operation,
                outcome="failed",
                reason=error_reason(str(exc)),
                copy=not update_document_identity,
                profile="none",
                content_revision=self._content_revision,
            )
            QMessageBox.critical(self, self.trx("unable_save"), str(exc))
            return False
        path = self._normalized_file_path(path)
        if update_document_identity:
            self._document_session.saved(path, history_index=self.history_index)
            self._clear_recovery(wait=True)
            self._add_recent_file(path)
            self._update_window_title()
        if show_confirmation:
            QMessageBox.information(
                self,
                self.trx("pdf_saved"),
                self.trx("pdf_saved_message", path=path),
            )
        else:
            self.statusBar().showMessage(self.trx("saved_status", path=path), 3000)
        self._operation_log.record(
            "document_write_finished",
            worker="write",
            operation=operation,
            outcome="succeeded",
            copy=not update_document_identity,
            profile="none",
            content_revision=self._content_revision,
        )
        return True

    def compress_pdf(self) -> None:
        if not self.engine.is_open:
            return
        if self._document_write_in_progress():
            return
        dialog = CompressionDialog(self, self.trx)
        if not dialog.exec():
            return
        source = self.document_path or self.engine.path
        suggested = source.with_name(f"{source.stem}_compressed.pdf") if source else Path("compressed.pdf")
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.trx("save_compressed_title"),
            str(suggested),
            self.trx("pdf_filter"),
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._start_document_write(
            Path(path),
            compression_profile=dialog.profile,
        )

    def _show_compression_result(
        self,
        path: Path,
        result: CompressionResult,
    ) -> None:
        reduction = 100 * (1 - result.output_size / max(1, result.original_size))
        if reduction >= 0:
            change_text = self.trx("reduction", value=reduction)
        else:
            change_text = self.trx("increase", value=-reduction)
        QMessageBox.information(
            self,
            self.trx("compression_complete"),
            f"{self.trx('original_working')}: {self._format_size(result.original_size)}\n"
            f"{self.trx('compressed_copy')}: {self._format_size(result.output_size)}\n"
            f"{change_text}\n"
            f"{self.trx('recompressed_images')}: {result.recompressed_images}\n\n{path}",
        )

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{size} B"

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape and self.find_bar.isVisible():
            self.hide_find_bar()
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self.page_view.special_mode:
            self.cancel_special_mode()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        controls = getattr(self, "text_controls_widget", None)
        if (
            controls is not None
            and event.type() == QEvent.MouseButtonPress
            and (watched is controls or controls.isAncestorOf(watched))
            and self.page_view.inline_editing
        ):
            # Commit before the combo/button begins handling this click.  If
            # focus-out commits while a native combo popup is already open,
            # the page rebuild can invalidate that popup and discard the
            # user's selected size on Windows.
            self.page_view.finish_inline_editor(True)
        if (
            watched is getattr(self, "find_edit", None)
            and event.type() == QEvent.KeyPress
            and event.key() == Qt.Key_Escape
        ):
            self.hide_find_bar()
            return True
        if watched is getattr(self, "toolbar", None) and event.type() in (
            QEvent.Resize,
            QEvent.Show,
            QEvent.LayoutRequest,
        ):
            self._position_language_button()
        return super().eventFilter(watched, event)

    def _position_language_button(self) -> None:
        if not hasattr(self, "language_button"):
            return
        right_inset = 4
        x = max(0, self.toolbar.width() - self.language_button.width() - right_inset)
        y = max(0, (self.toolbar.height() - self.language_button.height()) // 2)
        self.language_button.move(x, y)
        self.language_button.raise_()
        self.language_button.show()

    def _update_actions(self) -> None:
        opened = self.engine.is_open
        writing = self._write_process is not None
        ocr_running = self._ocr_process is not None
        busy = writing or ocr_running
        inspecting = self._inspection_process is not None
        self.new_action.setEnabled(not busy)
        self.open_action.setEnabled(not busy)
        self.close_document_action.setEnabled(opened and not busy)
        self.exit_action.setEnabled(not busy)
        self.recent_menu.setEnabled(not busy)
        self.find_action.setEnabled(opened)
        self.compatibility_action.setEnabled(opened)
        for action in (
            self.print_action,
            self.add_text_action,
            self.zoom_in_action,
            self.zoom_out_action,
            self.fit_width_action,
            self.add_blank_page_action,
            self.insert_pdf_action,
            self.delete_page_action,
            self.rotate_page_left_action,
            self.rotate_page_right_action,
            self.edit_original_image_action,
            self.add_image_action,
            self.delete_image_action,
            self.signature_action,
            self.add_comment_action,
            self.redact_area_action,
            self.create_form_action,
        ):
            action.setEnabled(opened and not ocr_running)
        self.ocr_page_action.setEnabled(opened and not busy)
        self.ocr_document_action.setEnabled(opened and not busy)
        self.move_page_up_action.setEnabled(
            opened and not ocr_running and self.current_page > 0
        )
        self.move_page_down_action.setEnabled(
            opened
            and not ocr_running
            and self.current_page + 1 < self.engine.page_count
        )
        can_reorder_thumbnails = (
            opened
            and not busy
            and not self._thumbnail_reorder_pending
            and self.engine.page_count > 1
        )
        self.page_list.setDragEnabled(can_reorder_thumbnails)
        self.page_list.setAcceptDrops(can_reorder_thumbnails)
        for action in (
            self.save_action,
            self.save_as_action,
            self.save_copy_action,
            self.compress_action,
        ):
            action.setEnabled(opened and not busy and not inspecting)
        selected_text = (
            self.page_view.selected_text_ref is not None
            or self._text_toolbar_reference is not None
        )
        self.delete_text_action.setEnabled(opened and selected_text)
        selected_annotation = self.comments_list.currentItem() is not None
        self.edit_comment_action.setEnabled(opened and selected_annotation and not busy)
        self.delete_comment_action.setEnabled(opened and selected_annotation and not busy)
        selected_form = self.forms_list.currentItem() is not None
        form_editing = self._form_workspace_mode not in {"preview", "fill"}
        self.create_form_action.setEnabled(opened and not busy and form_editing)
        self.edit_form_action.setEnabled(
            opened and selected_form and not busy and form_editing
        )
        self.delete_form_action.setEnabled(
            opened and selected_form and not busy and form_editing
        )
        self.add_comment_side_button.setEnabled(opened and not busy)
        self.edit_comment_side_button.setEnabled(opened and selected_annotation and not busy)
        self.delete_comment_side_button.setEnabled(opened and selected_annotation and not busy)
        self.create_form_side_button.setEnabled(opened and not busy and form_editing)
        self.edit_form_side_button.setEnabled(
            opened and selected_form and not busy and form_editing
        )
        self.delete_form_side_button.setEnabled(
            opened and selected_form and not busy and form_editing
        )
        self.form_edit_mode_button.setEnabled(opened and not busy)
        self.form_preview_mode_button.setEnabled(opened and not busy)
        self.reset_form_preview_button.setEnabled(
            opened and not busy and self._form_workspace_mode == "preview"
        )
        self.clear_form_values_button.setEnabled(
            opened and not busy and self._form_workspace_mode == "fill"
        )
        self.add_visual_signature_button.setEnabled(
            opened and not busy and self._form_workspace_mode == "fill"
        )
        if hasattr(self, "text_font_box"):
            for widget in (
                self.text_font_box,
                self.text_size_box,
                self.text_bold_button,
                self.text_italic_button,
                self.text_underline_button,
                self.text_color_button,
            ):
                widget.setEnabled(opened)
        self.zoom_combo.setEnabled(opened)
        self.undo_action.setEnabled(self.history_index > 0)
        self.redo_action.setEnabled(0 <= self.history_index < len(self.history) - 1)
        self._update_find_controls()

    def _diagnostic_session_snapshot(self) -> dict[str, object]:
        report = self._inspection_report
        compatibility = (
            report.compatibility_level
            if report is not None
            else "failed"
            if self._inspection_error
            else "unknown"
        )
        source_size = len(self.engine.source_bytes) if self.engine.is_open else 0
        return {
            "document_open": self.engine.is_open,
            "page_count": self.engine.page_count if self.engine.is_open else 0,
            "current_page": self.current_page + 1 if self.engine.is_open else 0,
            "file_size_bucket": file_size_bucket(source_size),
            "language": self.language_code,
            "theme": self.theme_mode,
            "compatibility": compatibility,
            "unsaved_changes": self.has_unsaved_changes,
            "history_entries": len(self.history),
            "pending_text_edits": len(self.edits),
            "pending_inserted_texts": len(self.inserted_texts),
            "pending_images": len(self.inserted_images),
            "pending_signatures": len(self.signatures),
            "pending_image_deletions": len(self.deleted_images),
            "tile_cache_hits": self._tile_cache_hits,
            "tile_cache_misses": self._tile_cache_misses,
            "tile_cache_evictions": self._tile_cache_evictions,
        }

    def export_diagnostics(self) -> bool:
        answer = QMessageBox.question(
            self,
            self.trx("diagnostics_title"),
            self.trx("diagnostics_review"),
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return False
        suggested = Path(
            f"Nettongia_PDF_Editor_diagnostics_{datetime.now():%Y%m%d-%H%M%S}.zip"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.trx("export_diagnostics"),
            str(suggested),
            self.trx("diagnostics_filter"),
        )
        if not path:
            return False
        if not path.lower().endswith(".zip"):
            path += ".zip"
        self._operation_log.record(
            "diagnostic_exported",
            operation="export_diagnostics",
            outcome="started",
        )
        try:
            result = build_diagnostic_bundle(
                path,
                operation_log=self._operation_log,
                session_snapshot=self._diagnostic_session_snapshot(),
                crash_path=self._crash_log_path,
            )
        except Exception as exc:
            self._operation_log.record(
                "diagnostic_exported",
                operation="export_diagnostics",
                outcome="failed",
                reason=error_reason(str(exc)),
            )
            QMessageBox.critical(
                self,
                self.trx("diagnostics_title"),
                self.trx("diagnostics_failed", error=exc),
            )
            return False
        self._operation_log.record(
            "diagnostic_exported",
            operation="export_diagnostics",
            outcome="succeeded",
        )
        QMessageBox.information(
            self,
            self.trx("diagnostics_title"),
            self.trx(
                "diagnostics_saved",
                path=result.path,
                records=result.operation_records,
            ),
        )
        return True

    def show_about(self) -> None:
        body_lines = self.trx("about_body").splitlines()
        if body_lines:
            body_lines[0] = f"Nettongia PDF Editor {__version__}"
        QMessageBox.about(
            self,
            self.trx("about_title"),
            "\n".join(body_lines),
        )

    def start_automatic_update_check(self) -> None:
        """Check at most once per day without delaying application startup."""

        self._start_update_check(manual=False)

    def check_for_updates(self) -> None:
        """Run an immediate, user-requested release check."""

        self._start_update_check(manual=True)

    def _start_update_check(self, *, manual: bool) -> None:
        if self._update_closing or self._update_task is not None:
            return
        now = int(datetime.now().timestamp())
        if not manual:
            if not self.automatic_updates_action.isChecked():
                return
            try:
                last_check = int(self.settings.value("updates/last_check_epoch", 0))
            except (TypeError, ValueError):
                last_check = 0
            if 0 <= now - last_check < 24 * 60 * 60:
                return
        self.settings.setValue("updates/last_check_epoch", now)
        task = VersionCheckTask()
        self._update_task = task
        self._update_manual = manual
        task.signals.finished.connect(self._update_check_finished, Qt.QueuedConnection)
        task.signals.failed.connect(self._update_check_failed, Qt.QueuedConnection)
        self._update_pool.start(task)

    @Slot(bool)
    def _set_automatic_updates(self, enabled: bool) -> None:
        self.settings.setValue("updates/enabled", enabled)

    @Slot(object)
    def _update_check_finished(self, release: object) -> None:
        manual = self._update_manual
        self._update_task = None
        if self._update_closing or (not manual and not self.automatic_updates_action.isChecked()):
            return
        if not isinstance(release, ReleaseInfo):
            self._update_check_failed()
            return
        if not is_newer(__version__, release.version):
            if manual:
                QMessageBox.information(
                    self,
                    self.trx("update_check_title"),
                    self.trx("no_update_available", version=__version__),
                )
            return
        try:
            last_notified = str(self.settings.value("updates/last_notified_version", ""))
        except (TypeError, ValueError):
            last_notified = ""
        if not manual and last_notified == release.version:
            return
        self.settings.setValue("updates/last_notified_version", release.version)
        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Information)
        prompt.setWindowTitle(self.trx("update_check_title"))
        prompt.setText(
            self.trx(
                "update_available",
                version=release.version,
                current=__version__,
            )
        )
        open_button = prompt.addButton(
            self.trx("open_release_page"), QMessageBox.AcceptRole
        )
        prompt.addButton(self.trx("cancel"), QMessageBox.RejectRole)
        prompt.exec()
        if prompt.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(release.page_url))

    @Slot()
    def _update_check_failed(self) -> None:
        self._update_task = None
        if self._update_manual and not self._update_closing:
            QMessageBox.information(
                self,
                self.trx("update_check_title"),
                self.trx("update_check_failed"),
            )

    def closeEvent(self, event) -> None:
        if self._document_write_in_progress():
            event.ignore()
            return
        if self.page_view.inline_editing:
            self.page_view.finish_inline_editor(True)
        if self._maybe_save_changes():
            self._update_closing = True
            self._clear_recovery(wait=True)
            self._cancel_document_inspection()
            self._cancel_search_task()
            self._search_timer.stop()
            self._cancel_thumbnail_loading()
            self._cancel_tile_render(wait=True, clear_cache=True)
            self._clear_tile_render_source()
            self._clear_outline_tree()
            self.page_view.clear_page()
            self.engine.close()
            event.accept()
        else:
            event.ignore()

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].toLocalFile().lower().endswith(".pdf"):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.open_pdf(event.mimeData().urls()[0].toLocalFile())
