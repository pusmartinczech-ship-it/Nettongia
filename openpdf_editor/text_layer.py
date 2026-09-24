from __future__ import annotations

import re

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFocusEvent, QFont, QKeyEvent, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsRectItem,
    QPlainTextEdit,
    QWidget,
)


def clean_pdf_font_name(name: str) -> str:
    """Return a Qt-friendly family name without the PDF style suffix.

    PDF font names commonly use PostScript spellings such as
    ``TimesNewRomanPS-BoldItalicMT``.  Passing that spelling directly to Qt
    selects the default GUI font on Windows, which is especially confusing
    because the bold/italic buttons can still look correct.  Keep a small set
    of canonical Windows family spellings and make a readable fallback for
    other CamelCase PostScript names.
    """

    family = (name or "").split("+")[-1].strip()
    family = re.sub(
        r"(?i)[\s,_-]*(?:bolditalic|boldoblique|semibolditalic|"
        r"semibold|demibold|bold|italic|oblique|regular)(?:mt)?$",
        "",
        family,
    )
    family = re.sub(r"(?i)(?:ps)?mt$", "", family)
    family = re.sub(r"(?i)ps$", "", family)
    compact = re.sub(r"[^a-z0-9]+", "", family.lower())
    if compact.startswith("timesnewroman"):
        return "Times New Roman"
    if compact.startswith("arial"):
        return "Arial"
    if compact.startswith("couriernew"):
        return "Courier New"
    if compact.startswith("nimbussans"):
        return "Nimbus Sans"
    if compact.startswith("nimbusroman"):
        return "Nimbus Roman"
    family = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", family)
    return family.replace("-", " ").strip() or "Arial"


class InlineTextEditor(QPlainTextEdit):
    accepted = Signal(str)
    rejected = Signal()

    def __init__(
        self,
        text: str,
        family: str,
        font_size: float,
        bold: bool,
        italic: bool,
        underline: bool,
        color: QColor,
        dark: bool,
        focus_guard: QWidget | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._finished = False
        self._focus_commit_timer = QTimer(self)
        self._focus_commit_timer.setSingleShot(True)
        self._focus_commit_timer.timeout.connect(self._commit_after_focus_out)
        self._key_finish_timer = QTimer(self)
        self._key_finish_timer.setSingleShot(True)
        self._key_finish_timer.timeout.connect(self._finish_after_key)
        self._key_finish_accept = True
        self._focus_guard = focus_guard
        self._dark = dark
        font = QFont(family)
        font.setPixelSize(max(8, round(font_size)))
        font.setBold(bold)
        font.setItalic(italic)
        font.setUnderline(underline)
        self.setFont(font)
        self.setPlainText(text)
        self.selectAll()
        self.setTabChangesFocus(False)
        self._apply_text_style(color)
        self.setToolTip("Ctrl+Enter: confirm   |   Esc: cancel")

    def apply_format(
        self,
        family: str,
        font_size: float,
        bold: bool,
        italic: bool,
        underline: bool,
        color: QColor,
    ) -> None:
        """Keep the live editor synchronized with the ribbon controls."""

        font = QFont(family)
        font.setPixelSize(max(8, round(font_size)))
        font.setBold(bold)
        font.setItalic(italic)
        font.setUnderline(underline)
        self.setFont(font)
        self._apply_text_style(color)

    def _apply_text_style(self, color: QColor) -> None:
        # This editor sits directly over the PDF page, so it should resemble
        # the paper rather than the application chrome even in dark mode.
        background = "rgba(255, 255, 255, 252)"
        foreground = color.name()
        border = "#0067b8" if not self._dark else "#174f78"
        self.setStyleSheet(
            "QPlainTextEdit {"
            f"background: {background}; color: {foreground}; border: 2px solid {border};"
            "border-radius: 3px; padding: 3px; selection-background-color: #168ad4;"
            "selection-color: white; }"
        )

    def finish(self, accept: bool) -> None:
        if self._finished:
            return
        self._focus_commit_timer.stop()
        self._key_finish_timer.stop()
        self._finished = True
        if accept:
            self.accepted.emit(self.toPlainText())
        else:
            self.rejected.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self._request_key_finish(False)
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self._request_key_finish(True)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        # Removing a QGraphicsProxyWidget synchronously from its own
        # focusOutEvent is unsafe on Windows and can terminate Qt without a
        # Python exception.  Commit on the next event-loop turn, after Qt has
        # completed the focus transfer to the toolbar or save dialog.
        if not self._finished:
            self._focus_commit_timer.start(0)

    def focusInEvent(self, event: QFocusEvent) -> None:
        self._focus_commit_timer.stop()
        super().focusInEvent(event)

    def _commit_after_focus_out(self) -> None:
        focused = QApplication.focusWidget()
        if self._focus_guard is not None and (
            focused is self._focus_guard
            or (focused is not None and self._focus_guard.isAncestorOf(focused))
            or QApplication.activePopupWidget() is not None
        ):
            self._focus_commit_timer.start(50)
            return
        if not self.hasFocus():
            self.finish(True)

    def _request_key_finish(self, accept: bool) -> None:
        # Like focus-out, a key event must return before its proxy widget can
        # safely be removed from the graphics scene.
        self._key_finish_accept = accept
        self._key_finish_timer.start(0)

    def _finish_after_key(self) -> None:
        self.finish(self._key_finish_accept)


class TextResizeHandle(QGraphicsEllipseItem):
    def __init__(self, owner: "TextObjectGraphicsItem") -> None:
        super().__init__(-6, -6, 12, 12, owner)
        self.owner = owner
        self.setZValue(4)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setCursor(Qt.SizeFDiagCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.owner.begin_resize(event.scenePos())
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self.owner.update_resize(event.scenePos())
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.owner.finish_resize()
            event.accept()
            return
        event.ignore()


class TextObjectGraphicsItem(QGraphicsRectItem):
    def __init__(
        self,
        kind: str,
        key: str,
        bbox: tuple[float, float, float, float],
        render_scale: float,
        host,
        z_value: float,
    ) -> None:
        x0, y0, x1, y1 = bbox
        super().__init__(
            x0 * render_scale,
            y0 * render_scale,
            max(8.0, (x1 - x0) * render_scale),
            max(8.0, (y1 - y0) * render_scale),
        )
        self.kind = kind
        self.key = key
        self.render_scale = render_scale
        self.host = host
        self._hovered = False
        self._geometry_at_press: QRectF | None = None
        self._resize_origin: QPointF | None = None
        self._resize_rect: QRectF | None = None

        self.setZValue(z_value)
        self.setAcceptHoverEvents(True)
        self.setBrush(Qt.NoBrush)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.IBeamCursor)
        self.resize_handle = TextResizeHandle(self)
        self._update_handle()
        self.refresh_visuals()

    def _update_handle(self) -> None:
        self.resize_handle.setPos(self.rect().bottomRight())

    def refresh_visuals(self) -> None:
        visible = self.isSelected() or self._hovered
        accent = self.host.text_accent
        pen = QPen(accent, 1.7, Qt.SolidLine if self.isSelected() else Qt.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen if visible else QPen(Qt.transparent, 0))
        self.resize_handle.setPen(QPen(accent.darker(145), 1.1))
        self.resize_handle.setBrush(accent)
        self.resize_handle.setVisible(self.isSelected() and not self.host.special_mode)
        enabled = not self.host.special_mode
        self.setFlag(QGraphicsItem.ItemIsMovable, enabled)
        self.setFlag(QGraphicsItem.ItemIsSelectable, enabled)

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        if not self.host.special_mode:
            self.refresh_visuals()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.refresh_visuals()
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self.host.special_mode and event.button() == Qt.LeftButton:
            self.host.inline_edit_requested.emit(self.kind, self.key)
            event.accept()
            return
        event.ignore()

    def mousePressEvent(self, event) -> None:
        if self.host.special_mode:
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            self._geometry_at_press = self._scene_rect()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self.setCursor(Qt.IBeamCursor)
        self._commit_if_changed()

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.refresh_visuals()
        return result

    def begin_resize(self, scene_position: QPointF) -> None:
        self.setSelected(True)
        self._geometry_at_press = self._scene_rect()
        self._resize_origin = scene_position
        self._resize_rect = QRectF(self.rect())

    def update_resize(self, scene_position: QPointF) -> None:
        if self._resize_origin is None or self._resize_rect is None:
            return
        delta = scene_position - self._resize_origin
        rect = QRectF(self._resize_rect)
        rect.setWidth(max(24.0, rect.width() + delta.x()))
        rect.setHeight(max(16.0, rect.height() + delta.y()))
        self.setRect(rect)
        self._update_handle()

    def finish_resize(self) -> None:
        self._resize_origin = None
        self._resize_rect = None
        self._commit_if_changed()

    def _commit_if_changed(self) -> None:
        if self._geometry_at_press is None:
            return
        old = self._geometry_at_press
        self._geometry_at_press = None
        current = self._scene_rect()
        width_changed = abs(current.width() - old.width()) >= 0.05
        height_changed = abs(current.height() - old.height()) >= 0.05
        horizontal_move = current.left() - old.left()
        vertical_move = current.top() - old.top()
        if (
            not width_changed
            and not height_changed
            and max(abs(horizontal_move), abs(vertical_move)) < 3.0
        ):
            # A double click commonly contains one or two pixels of pointer
            # jitter. QGraphicsItem would otherwise treat it as a real move,
            # queue a full page render, and race the editor opened by the
            # second click. Restore the original position for such tiny drags.
            self.moveBy(-horizontal_move, -vertical_move)
            return
        if (
            abs(horizontal_move) < 0.05
            and abs(vertical_move) < 0.05
            and not width_changed
            and not height_changed
        ):
            return
        bbox = (
            current.left() / self.render_scale,
            current.top() / self.render_scale,
            current.right() / self.render_scale,
            current.bottom() / self.render_scale,
        )
        self.host.text_transform_requested.emit(self.kind, self.key, bbox)

    def _scene_rect(self) -> QRectF:
        mapped = self.mapRectToScene(self.rect())
        return mapped.boundingRect() if hasattr(mapped, "boundingRect") else QRectF(mapped)
