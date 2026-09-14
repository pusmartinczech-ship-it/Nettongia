from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .engine import TextEdit, TextRun
from .i18n import translate
from .text_layer import clean_pdf_font_name


Translator = Callable[..., str]


def _translator(value: Translator | None) -> Translator:
    return value or (lambda key, **items: translate("en", key, **items))


class NewDocumentDialog(QDialog):
    PAGE_SIZES_MM = (
        ("A4 (210 x 297 mm)", 210.0, 297.0),
        ("A3 (297 x 420 mm)", 297.0, 420.0),
        ("A5 (148 x 210 mm)", 148.0, 210.0),
        ("Letter (215.9 x 279.4 mm)", 215.9, 279.4),
        ("Legal (215.9 x 355.6 mm)", 215.9, 355.6),
    )

    def __init__(self, parent=None, translator: Translator | None = None) -> None:
        super().__init__(parent)
        self._tr = _translator(translator)
        self.setWindowTitle(self._tr("new_title"))
        self.setMinimumWidth(470)

        self.page_size_box = QComboBox()
        for label, width, height in self.PAGE_SIZES_MM:
            self.page_size_box.addItem(label, (width, height))
        self.page_size_box.addItem(self._tr("custom_size"), None)

        self.orientation_box = QComboBox()
        self.orientation_box.addItem(self._tr("portrait"), "portrait")
        self.orientation_box.addItem(self._tr("landscape"), "landscape")

        self.width_box = QDoubleSpinBox()
        self.width_box.setRange(25.0, 2000.0)
        self.width_box.setDecimals(1)
        self.width_box.setSuffix(" mm")
        self.height_box = QDoubleSpinBox()
        self.height_box.setRange(25.0, 2000.0)
        self.height_box.setDecimals(1)
        self.height_box.setSuffix(" mm")

        self.page_count_box = QSpinBox()
        self.page_count_box.setRange(1, 100)
        self.page_count_box.setValue(1)

        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow(self._tr("page_size"), self.page_size_box)
        form.addRow(self._tr("orientation"), self.orientation_box)
        form.addRow(self._tr("width"), self.width_box)
        form.addRow(self._tr("height"), self.height_box)
        form.addRow(self._tr("page_count"), self.page_count_box)
        form.addRow(self._tr("result"), self.preview_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self._tr("create"))
        buttons.button(QDialogButtonBox.Cancel).setText(self._tr("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self._tr("blank_pdf_intro")))
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.page_size_box.currentIndexChanged.connect(self._page_size_changed)
        self.orientation_box.currentIndexChanged.connect(self._update_preview)
        self.width_box.valueChanged.connect(self._update_preview)
        self.height_box.valueChanged.connect(self._update_preview)
        self.page_count_box.valueChanged.connect(self._update_preview)
        self._page_size_changed()

    def _page_size_changed(self, *args) -> None:
        dimensions = self.page_size_box.currentData()
        custom = dimensions is None
        if dimensions is not None:
            self.width_box.setValue(float(dimensions[0]))
            self.height_box.setValue(float(dimensions[1]))
        self.width_box.setEnabled(custom)
        self.height_box.setEnabled(custom)
        self._update_preview()

    def _update_preview(self, *args) -> None:
        width, height = self.page_dimensions_mm
        self.preview_label.setText(
            f"{width:.1f} x {height:.1f} mm, {self._tr('page_count')}: {self.page_count_box.value()}"
        )

    @property
    def page_dimensions_mm(self) -> tuple[float, float]:
        width = self.width_box.value()
        height = self.height_box.value()
        if self.orientation_box.currentData() == "landscape":
            width, height = height, width
        return width, height

    def document_settings(self) -> tuple[float, float, int]:
        width_mm, height_mm = self.page_dimensions_mm
        points_per_mm = 72.0 / 25.4
        return (
            width_mm * points_per_mm,
            height_mm * points_per_mm,
            self.page_count_box.value(),
        )


def _int_to_qcolor(value: int) -> QColor:
    return QColor((value >> 16) & 255, (value >> 8) & 255, value & 255)


def _qcolor_to_int(color: QColor) -> int:
    return (color.red() << 16) | (color.green() << 8) | color.blue()


class EditTextDialog(QDialog):
    def __init__(
        self,
        run: TextRun,
        existing: TextEdit | None,
        parent=None,
        translator: Translator | None = None,
    ) -> None:
        super().__init__(parent)
        self._tr = _translator(translator)
        self.setWindowTitle("Edit text and formatting")
        self.setMinimumWidth(640)
        self._color = _int_to_qcolor(existing.color if existing and existing.color is not None else run.color)

        intro = QLabel(
            f"Source font: {run.font_name}   |   Position: {run.bbox[0]:.1f}, {run.bbox[1]:.1f} pt"
        )
        intro.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.new_text = QLineEdit(existing.new_text if existing else run.text)
        self.new_text.setClearButtonEnabled(True)

        self.font_family = QFontComboBox()
        family = existing.font_family if existing and existing.font_family else clean_pdf_font_name(run.font_name)
        self.font_family.setCurrentFont(QFont(family))
        self._initial_font_combo_family = self.font_family.currentFont().family()
        self._preserved_source_family = (
            existing.font_family
            if existing and existing.font_family
            else run.font_name
        )

        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(3.0, 200.0)
        self.font_size.setDecimals(1)
        self.font_size.setSuffix(" pt")
        self.font_size.setValue(existing.font_size if existing else run.font_size)

        self.bold_button = self._style_button("B", self._tr("bold"), run.bold if not existing else bool(existing.bold))
        bold_font = self.bold_button.font()
        bold_font.setBold(True)
        self.bold_button.setFont(bold_font)
        self.italic_button = self._style_button("I", self._tr("italic"), run.italic if not existing else bool(existing.italic))
        italic_font = self.italic_button.font()
        italic_font.setItalic(True)
        self.italic_button.setFont(italic_font)
        self.underline_button = self._style_button("U", self._tr("underline"), existing.underline if existing else False)
        underline_font = self.underline_button.font()
        underline_font.setUnderline(True)
        self.underline_button.setFont(underline_font)

        self.color_button = QPushButton(self._tr("text_color"))
        self.color_button.clicked.connect(self._choose_color)
        self._update_color_button()

        style_row = QHBoxLayout()
        style_row.setContentsMargins(0, 0, 0, 0)
        style_row.addWidget(self.bold_button)
        style_row.addWidget(self.italic_button)
        style_row.addWidget(self.underline_button)
        style_row.addSpacing(10)
        style_row.addWidget(self.color_button)
        style_row.addStretch(1)
        style_widget = QWidget()
        style_widget.setLayout(style_row)

        self.fit_width = QCheckBox("Shrink text when it exceeds the original width")
        self.fit_width.setChecked(existing.fit_to_width if existing else True)

        form = QFormLayout()
        form.addRow("Replacement", self.new_text)
        form.addRow(self._tr("font"), self.font_family)
        form.addRow(self._tr("font_size"), self.font_size)
        form.addRow(self._tr("style"), style_widget)
        form.addRow("", self.fit_width)

        hint = QLabel(
            "The selected PDF font may be a limited embedded subset. Nettongia PDF Editor uses the closest installed font for new text."
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(self._tr("save"))
        buttons.button(QDialogButtonBox.Cancel).setText(self._tr("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.new_text.setFocus()
        self.new_text.selectAll()

    @staticmethod
    def _style_button(text: str, tooltip: str, checked: bool) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setCheckable(True)
        button.setChecked(checked)
        button.setFixedSize(32, 28)
        return button

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(self._color, self, self._tr("choose_text_color"))
        if color.isValid():
            self._color = color
            self._update_color_button()

    def _update_color_button(self) -> None:
        foreground = "white" if self._color.lightness() < 120 else "black"
        self.color_button.setStyleSheet(
            f"background-color: {self._color.name()}; color: {foreground}; padding: 4px 10px;"
        )

    def make_edit(self, run: TextRun) -> TextEdit:
        selected_family = self.font_family.currentFont().family()
        font_family = (
            selected_family
            if selected_family != self._initial_font_combo_family
            else self._preserved_source_family
        )
        return TextEdit(
            run=run,
            new_text=self.new_text.text(),
            font_size=self.font_size.value(),
            fit_to_width=self.fit_width.isChecked(),
            font_family=font_family,
            bold=self.bold_button.isChecked(),
            italic=self.italic_button.isChecked(),
            underline=self.underline_button.isChecked(),
            color=_qcolor_to_int(self._color),
        )


class SignaturePad(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(620, 190)
        self.setCursor(Qt.CrossCursor)
        self.setStyleSheet("background: white; border: 1px solid #aeb4bb;")
        self._image = QImage(1240, 380, QImage.Format_ARGB32_Premultiplied)
        self._image.fill(Qt.transparent)
        self._last_point: QPointF | None = None
        self._has_ink = False

    @property
    def has_ink(self) -> bool:
        return self._has_ink

    def clear(self) -> None:
        self._image.fill(Qt.transparent)
        self._has_ink = False
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.white)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(self.rect(), self._image)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._last_point = self._map_point(event.position())
            self._has_ink = True
            painter = QPainter(self._image)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(Qt.black, 5.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPoint(self._last_point)
            painter.end()
            self.update()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._last_point is None or not event.buttons() & Qt.LeftButton:
            return
        point = self._map_point(event.position())
        painter = QPainter(self._image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(Qt.black, 5.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawLine(self._last_point, point)
        painter.end()
        self._last_point = point
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._last_point = None
        event.accept()

    def _map_point(self, point: QPointF) -> QPointF:
        return QPointF(
            point.x() * self._image.width() / max(1, self.width()),
            point.y() * self._image.height() / max(1, self.height()),
        )

    def signature_image(self) -> QImage:
        return _crop_transparent(self._image)


class SignatureDialog(QDialog):
    def __init__(self, parent=None, translator: Translator | None = None) -> None:
        super().__init__(parent)
        self._tr = _translator(translator)
        self.setWindowTitle(self._tr("signature_title"))
        self.setMinimumWidth(680)

        warning = QLabel(
            self._tr("signature_warning")
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "background: #fff4ce; border: 1px solid #e5c365; padding: 8px; color: #5d4800;"
        )

        self.draw_mode = QRadioButton(self._tr("draw_signature"))
        self.type_mode = QRadioButton(self._tr("type_signature"))
        self.draw_mode.setChecked(True)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.draw_mode)
        mode_row.addWidget(self.type_mode)
        mode_row.addStretch(1)

        self.pad = SignaturePad()
        clear_button = QPushButton(self._tr("clear_drawing"))
        clear_button.clicked.connect(self.pad.clear)
        draw_page = QWidget()
        draw_layout = QVBoxLayout(draw_page)
        draw_layout.setContentsMargins(0, 0, 0, 0)
        draw_layout.addWidget(QLabel(self._tr("draw_hint")))
        draw_layout.addWidget(self.pad)
        draw_layout.addWidget(clear_button, alignment=Qt.AlignRight)

        self.typed_text = QLineEdit()
        self.typed_text.setPlaceholderText(self._tr("your_name"))
        self.typed_font = QFontComboBox()
        for preferred in ("Segoe Script", "Lucida Handwriting", "Brush Script MT"):
            self.typed_font.setCurrentFont(QFont(preferred))
            if self.typed_font.currentFont().family().lower() == preferred.lower():
                break
        self.typed_size = QDoubleSpinBox()
        self.typed_size.setRange(18, 96)
        self.typed_size.setValue(48)
        self.typed_size.setSuffix(" pt")
        self.typed_bold = QCheckBox(self._tr("bold"))
        self.typed_italic = QCheckBox(self._tr("italic"))
        self.typed_italic.setChecked(True)
        type_form = QFormLayout()
        type_form.addRow(self._tr("signature_text"), self.typed_text)
        type_form.addRow(self._tr("font"), self.typed_font)
        type_form.addRow(self._tr("size"), self.typed_size)
        type_style = QHBoxLayout()
        type_style.addWidget(self.typed_bold)
        type_style.addWidget(self.typed_italic)
        type_style.addStretch(1)
        type_style_widget = QWidget()
        type_style_widget.setLayout(type_style)
        type_form.addRow(self._tr("style"), type_style_widget)
        type_page = QWidget()
        type_page.setLayout(type_form)

        self.stack = QStackedWidget()
        self.stack.addWidget(draw_page)
        self.stack.addWidget(type_page)
        self.draw_mode.toggled.connect(lambda checked: self.stack.setCurrentIndex(0 if checked else 1))

        self.width_box = QDoubleSpinBox()
        self.width_box.setRange(40, 360)
        self.width_box.setValue(160)
        self.width_box.setSuffix(" pt")
        self.angle_box = QDoubleSpinBox()
        self.angle_box.setRange(-180, 180)
        self.angle_box.setDecimals(1)
        self.angle_box.setSingleStep(5)
        self.angle_box.setSuffix("°")
        self.angle_box.setToolTip(self._tr("rotation"))
        size_form = QFormLayout()
        size_form.addRow(self._tr("width_on_page"), self.width_box)
        size_form.addRow(self._tr("rotation"), self.angle_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText(self._tr("cancel"))
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(warning)
        layout.addLayout(mode_row)
        layout.addWidget(self.stack)
        layout.addLayout(size_form)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        if self.draw_mode.isChecked() and not self.pad.has_ink:
            QMessageBox.warning(self, self._tr("empty_signature"), self._tr("empty_draw"))
            return
        if self.type_mode.isChecked() and not self.typed_text.text().strip():
            QMessageBox.warning(self, self._tr("empty_signature"), self._tr("empty_type"))
            return
        self.accept()

    def signature_data(self) -> tuple[bytes, float, float, str]:
        if self.draw_mode.isChecked():
            image = self.pad.signature_image()
            description = self._tr("drawn_signature_desc")
        else:
            image = self._typed_signature_image()
            description = self._tr("typed_signature_desc", text=self.typed_text.text().strip())
        angle = self.angle_box.value()
        return _image_to_png(image), self.width_box.value(), angle, description

    def _typed_signature_image(self) -> QImage:
        image = QImage(1800, 440, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        font = QFont(self.typed_font.currentFont().family())
        font.setPixelSize(int(self.typed_size.value() * 4))
        font.setBold(self.typed_bold.isChecked())
        font.setItalic(self.typed_italic.isChecked())
        painter.setFont(font)
        painter.setPen(Qt.black)
        painter.drawText(image.rect().adjusted(24, 12, -24, -12), Qt.AlignCenter, self.typed_text.text().strip())
        painter.end()
        return _crop_transparent(image)


def _crop_transparent(image: QImage, margin: int = 10) -> QImage:
    left, top = image.width(), image.height()
    right = bottom = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 8:
                left = min(left, x)
                top = min(top, y)
                right = max(right, x)
                bottom = max(bottom, y)
    if right < left or bottom < top:
        empty = QImage(2, 2, QImage.Format_ARGB32_Premultiplied)
        empty.fill(Qt.transparent)
        return empty
    left = max(0, left - margin)
    top = max(0, top - margin)
    right = min(image.width() - 1, right + margin)
    bottom = min(image.height() - 1, bottom + margin)
    return image.copy(left, top, right - left + 1, bottom - top + 1)


def _image_to_png(image: QImage) -> bytes:
    payload = QByteArray()
    buffer = QBuffer(payload)
    if not buffer.open(QIODevice.WriteOnly):
        raise RuntimeError("Unable to create signature image buffer.")
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Unable to encode signature as PNG.")
    buffer.close()
    return bytes(payload)


class CompressionDialog(QDialog):
    def __init__(self, parent=None, translator: Translator | None = None) -> None:
        super().__init__(parent)
        self._tr = _translator(translator)
        self.setWindowTitle(self._tr("compress_title"))
        self.setMinimumWidth(500)

        self.profile_box = QComboBox()
        self.profile_box.addItem(self._tr("lossless"), "lossless")
        self.profile_box.addItem(self._tr("balanced"), "balanced")
        self.profile_box.addItem(self._tr("strong"), "strong")
        self.profile_box.setCurrentIndex(1)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setStyleSheet("padding: 8px 0;")
        self.profile_box.currentIndexChanged.connect(self._update_description)
        self._update_description()

        note = QLabel(self._tr("compression_note"))
        note.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText(self._tr("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow(self._tr("compression_profile"), self.profile_box)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.description)
        layout.addWidget(note)
        layout.addWidget(buttons)

    @property
    def profile(self) -> str:
        return str(self.profile_box.currentData())

    def _update_description(self, *args) -> None:
        self.description.setText(self._tr(f"{self.profile}_desc"))
