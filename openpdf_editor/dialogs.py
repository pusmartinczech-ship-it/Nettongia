from __future__ import annotations

from collections.abc import Callable
from datetime import date
from math import ceil, sqrt
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance

try:
    import pymupdf
except ImportError:  # PyMuPDF before 1.24
    import fitz as pymupdf

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .crash_trace import record_signature_trace
from .engine import DocumentMarksSpec, FormFieldSpec, TextEdit, TextRun
from .document_compare import DocumentComparison
from .digital_signature_worker import validate_timestamp_url
from .i18n import translate
from .text_layer import clean_pdf_font_name


Translator = Callable[..., str]


def _translator(value: Translator | None) -> Translator:
    return value or (lambda key, **items: translate("en", key, **items))


class PasswordProtectionDialog(QDialog):
    """Collect and confirm an opening password without persisting it."""

    MINIMUM_LENGTH = 8

    def __init__(self, parent=None, translator: Translator | None = None) -> None:
        super().__init__(parent)
        self._tr = _translator(translator)
        self.setWindowTitle(self._tr("add_password_protection").rstrip("."))
        self.setMinimumWidth(440)

        intro = QLabel(self._tr("protect_pdf_intro"))
        intro.setWordWrap(True)
        self.password_edit = QLineEdit()
        self.password_edit.setObjectName("protectionPassword")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMaxLength(40)
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setObjectName("protectionPasswordConfirm")
        self.confirm_edit.setEchoMode(QLineEdit.Password)
        self.confirm_edit.setMaxLength(40)
        self.show_password_box = QCheckBox(self._tr("show_password"))
        self.validation_label = QLabel()
        self.validation_label.setObjectName("passwordValidation")
        self.validation_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow(self._tr("new_password"), self.password_edit)
        form.addRow(self._tr("confirm_password"), self.confirm_edit)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self.save_button = self.buttons.button(QDialogButtonBox.Save)
        self.save_button.setText(self._tr("save_copy").rstrip("."))
        self.buttons.button(QDialogButtonBox.Cancel).setText(self._tr("cancel"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.show_password_box)
        layout.addWidget(self.validation_label)
        layout.addWidget(self.buttons)

        self.password_edit.textChanged.connect(self._validate)
        self.confirm_edit.textChanged.connect(self._validate)
        self.show_password_box.toggled.connect(self._set_password_visible)
        self._validate()

    @property
    def password(self) -> str:
        return self.password_edit.text()

    def _set_password_visible(self, visible: bool) -> None:
        mode = QLineEdit.Normal if visible else QLineEdit.Password
        self.password_edit.setEchoMode(mode)
        self.confirm_edit.setEchoMode(mode)

    def _validate(self) -> None:
        password = self.password_edit.text()
        confirmation = self.confirm_edit.text()
        if len(password) < self.MINIMUM_LENGTH:
            message = self._tr("password_too_short", count=self.MINIMUM_LENGTH)
        elif password != confirmation:
            message = self._tr("password_mismatch")
        else:
            message = ""
        self.validation_label.setText(message)
        self.save_button.setEnabled(not message)


class CertificateSignatureDialog(QDialog):
    """Collect PKCS#12 signing inputs without retaining the password."""

    def __init__(
        self,
        unsigned_fields: list[str],
        suggested_field_name: str,
        parent=None,
        translator: Translator | None = None,
        *,
        page_count: int = 1,
        current_page: int = 0,
    ) -> None:
        super().__init__(parent)
        self._tr = _translator(translator)
        self.setWindowTitle(self._tr("certificate_signing_title"))
        self.setMinimumWidth(580)

        intro = QLabel(self._tr("certificate_signing_intro"))
        intro.setWordWrap(True)
        self.certificate_edit = QLineEdit()
        self.certificate_edit.setObjectName("certificatePath")
        self.browse_button = QPushButton(self._tr("browse"))
        self.browse_button.clicked.connect(self._browse_certificate)
        certificate_row = QHBoxLayout()
        certificate_row.setContentsMargins(0, 0, 0, 0)
        certificate_row.addWidget(self.certificate_edit, 1)
        certificate_row.addWidget(self.browse_button)
        certificate_widget = QWidget()
        certificate_widget.setLayout(certificate_row)

        self.password_edit = QLineEdit()
        self.password_edit.setObjectName("certificatePassword")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMaxLength(256)
        self.show_password_box = QCheckBox(self._tr("show_password"))
        self.show_password_box.toggled.connect(
            lambda visible: self.password_edit.setEchoMode(
                QLineEdit.Normal if visible else QLineEdit.Password
            )
        )
        password_widget = QWidget()
        password_layout = QHBoxLayout(password_widget)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.addWidget(self.password_edit, 1)
        password_layout.addWidget(self.show_password_box)

        self.target_combo = QComboBox()
        for field_name in unsigned_fields:
            self.target_combo.addItem(field_name, (field_name, False))
        if unsigned_fields:
            self.target_combo.insertSeparator(self.target_combo.count())
        self.target_combo.addItem(
            self._tr("new_invisible_signature_field"),
            (suggested_field_name, True, False),
        )
        self.target_combo.addItem(
            self._tr("new_visible_signature_field"),
            (suggested_field_name, True, True),
        )
        self.page_combo = QComboBox()
        for page in range(page_count):
            self.page_combo.addItem(self._tr("signature_page_number", number=page + 1), page)
        self.page_combo.setCurrentIndex(min(max(current_page, 0), page_count - 1))
        self.page_combo.setEnabled(False)
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        self.reason_edit = QLineEdit()
        self.reason_edit.setMaxLength(512)
        self.location_edit = QLineEdit()
        self.location_edit.setMaxLength(512)
        self.contact_edit = QLineEdit()
        self.contact_edit.setMaxLength(512)
        self.timestamp_box = QCheckBox(self._tr("add_trusted_timestamp"))
        self.timestamp_edit = QLineEdit()
        self.timestamp_edit.setObjectName("timestampServerUrl")
        self.timestamp_edit.setMaxLength(2048)
        self.timestamp_edit.setPlaceholderText("https://tsa.example.com")
        self.timestamp_edit.setEnabled(False)
        self.timestamp_box.toggled.connect(self._timestamp_toggled)
        self.revocation_box = QCheckBox(self._tr("embed_revocation_info"))
        self.revocation_box.setToolTip(self._tr("embed_revocation_info_hint"))
        self.revocation_box.toggled.connect(self._revocation_toggled)

        form = QFormLayout()
        form.addRow(self._tr("certificate_file"), certificate_widget)
        form.addRow(self._tr("certificate_password"), password_widget)
        form.addRow(self._tr("signature_target"), self.target_combo)
        form.addRow(self._tr("visible_signature_page"), self.page_combo)
        form.addRow(self._tr("signature_reason"), self.reason_edit)
        form.addRow(self._tr("signature_location"), self.location_edit)
        form.addRow(self._tr("signature_contact"), self.contact_edit)
        form.addRow("", self.timestamp_box)
        form.addRow(self._tr("timestamp_server"), self.timestamp_edit)
        form.addRow("", self.revocation_box)

        notice = QLabel(self._tr("certificate_signature_visual_notice"))
        notice.setWordWrap(True)
        timestamp_notice = QLabel(self._tr("timestamp_server_notice"))
        timestamp_notice.setWordWrap(True)
        revocation_notice = QLabel(self._tr("embed_revocation_info_hint"))
        revocation_notice.setWordWrap(True)
        revocation_notice.setVisible(False)
        self.revocation_box.toggled.connect(revocation_notice.setVisible)
        self.validation_label = QLabel()
        self.validation_label.setObjectName("certificateSignatureValidation")
        self.validation_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self.sign_button = self.buttons.button(QDialogButtonBox.Save)
        self.sign_button.setText(self._tr("sign_copy"))
        self.buttons.button(QDialogButtonBox.Cancel).setText(self._tr("cancel"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(notice)
        visible_notice = QLabel(self._tr("certificate_signature_placement_notice"))
        visible_notice.setWordWrap(True)
        layout.addWidget(visible_notice)
        layout.addWidget(timestamp_notice)
        layout.addWidget(revocation_notice)
        layout.addWidget(self.validation_label)
        layout.addWidget(self.buttons)
        self.certificate_edit.textChanged.connect(self._validate)
        self.password_edit.textChanged.connect(self._validate)
        self.timestamp_edit.textChanged.connect(self._validate)
        self._validate()

    def _timestamp_toggled(self, enabled: bool) -> None:
        self.timestamp_edit.setEnabled(enabled)
        if not enabled:
            self.revocation_box.setChecked(False)
        self._validate()

    def _revocation_toggled(self, enabled: bool) -> None:
        if enabled:
            self.timestamp_box.setChecked(True)
        self._validate()

    def _target_changed(self, _index: int) -> None:
        target = self.target_combo.currentData()
        self.page_combo.setEnabled(bool(target and len(target) > 2 and target[2]))

    def _browse_certificate(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            self._tr("certificate_file"),
            self.certificate_edit.text(),
            self._tr("certificate_filter"),
        )
        if path:
            self.certificate_edit.setText(path)

    def _validate(self) -> None:
        path = Path(self.certificate_edit.text().strip())
        if path.suffix.lower() not in {".p12", ".pfx"} or not path.is_file():
            message = self._tr("certificate_choose_file")
        elif not self.password_edit.text():
            message = self._tr("certificate_enter_password")
        elif self.timestamp_box.isChecked():
            try:
                timestamp_url = validate_timestamp_url(self.timestamp_edit.text())
            except ValueError:
                message = self._tr("timestamp_server_invalid")
            else:
                message = "" if timestamp_url else self._tr("timestamp_server_invalid")
        else:
            message = ""
        self.validation_label.setText(message)
        self.sign_button.setEnabled(not message)

    def signature_settings(self) -> dict[str, object]:
        target = self.target_combo.currentData()
        field_name, create_field = target[:2]
        visible = bool(len(target) > 2 and target[2])
        return {
            "certificate_path": self.certificate_edit.text().strip(),
            "certificate_password": self.password_edit.text(),
            "field_name": str(field_name),
            "create_field": bool(create_field),
            "visible": visible,
            "page_index": int(self.page_combo.currentData()) if visible else 0,
            "reason": self.reason_edit.text().strip(),
            "location": self.location_edit.text().strip(),
            "contact_info": self.contact_edit.text().strip(),
            "timestamp_url": (
                self.timestamp_edit.text().strip()
                if self.timestamp_box.isChecked()
                else ""
            ),
            "embed_revocation_info": self.revocation_box.isChecked(),
        }


class ComparisonDialog(QDialog):
    """Show page-level results and on-demand side-by-side visual previews."""

    def __init__(
        self,
        current_pdf: bytes,
        comparison_pdf: bytes,
        result: DocumentComparison,
        comparison_name: str,
        parent=None,
        translator: Translator | None = None,
    ) -> None:
        super().__init__(parent)
        self._tr = _translator(translator)
        self._result = result
        self._current_document = pymupdf.open(stream=current_pdf, filetype="pdf")
        self._comparison_document = pymupdf.open(
            stream=comparison_pdf, filetype="pdf"
        )
        self.setWindowTitle(self._tr("compare_pdf_title"))
        self.resize(1180, 760)

        summary = QLabel(
            self._tr(
                "comparison_summary",
                changed=result.changed_page_count,
                total=len(result.pages),
                name=comparison_name,
            )
        )
        summary.setWordWrap(True)

        self.table = QTableWidget(len(result.pages), 3)
        self.table.setObjectName("comparisonResults")
        self.table.setHorizontalHeaderLabels(
            (
                self._tr("page_word"),
                self._tr("comparison_result"),
                self._tr("comparison_changed_area"),
            )
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        status_keys = {
            "identical": "comparison_identical",
            "changed": "comparison_changed",
            "geometry": "comparison_geometry",
            "current_only": "comparison_current_only",
            "comparison_only": "comparison_other_only",
        }
        for row, page in enumerate(result.pages):
            self.table.setItem(row, 0, QTableWidgetItem(str(page.page_index + 1)))
            self.table.setItem(
                row,
                1,
                QTableWidgetItem(self._tr(status_keys[page.status])),
            )
            ratio = f"{page.changed_ratio * 100:.2f}%" if page.total_pixels else "—"
            self.table.setItem(row, 2, QTableWidgetItem(ratio))
        self.table.currentCellChanged.connect(self._selection_changed)

        previews = QSplitter(Qt.Horizontal)
        self.current_preview = self._preview_panel(
            previews, self._tr("comparison_current")
        )
        self.other_preview = self._preview_panel(
            previews, self._tr("comparison_selected")
        )
        self.diff_preview = self._preview_panel(
            previews, self._tr("comparison_differences")
        )
        previews.setSizes((390, 390, 390))

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.table, 2)
        layout.addWidget(previews, 5)
        layout.addWidget(buttons)
        if result.pages:
            first_changed = next(
                (index for index, page in enumerate(result.pages) if page.status != "identical"),
                0,
            )
            self.table.setCurrentCell(first_changed, 0)

    def _preview_panel(self, parent: QWidget, title: str) -> QLabel:
        panel = QWidget(parent)
        layout = QVBoxLayout(panel)
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignCenter)
        image = QLabel()
        image.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(image)
        layout.addWidget(heading)
        layout.addWidget(scroll)
        return image

    @staticmethod
    def _render_page(document: pymupdf.Document, page_index: int) -> Image.Image | None:
        if not 0 <= page_index < document.page_count:
            return None
        page = document[page_index]
        area = max(1.0, page.rect.width * page.rect.height)
        scale = max(0.15, min(1.0, sqrt(900_000 / area)))
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale),
            colorspace=pymupdf.csRGB,
            alpha=False,
            annots=True,
        )
        return Image.frombytes(
            "RGB",
            (pixmap.width, pixmap.height),
            bytes(pixmap.samples),
            "raw",
            "RGB",
            pixmap.stride,
            1,
        )

    @staticmethod
    def _pixmap(image: Image.Image) -> QPixmap:
        payload = image.tobytes()
        qimage = QImage(
            payload,
            image.width,
            image.height,
            image.width * 3,
            QImage.Format_RGB888,
        ).copy()
        return QPixmap.fromImage(qimage)

    def _selection_changed(self, row: int, _column: int, *_args) -> None:
        if not 0 <= row < len(self._result.pages):
            return
        page = self._result.pages[row]
        current = self._render_page(self._current_document, page.page_index)
        other = self._render_page(self._comparison_document, page.page_index)
        self._set_preview(self.current_preview, current)
        self._set_preview(self.other_preview, other)
        if current is None or other is None or current.size != other.size:
            self.diff_preview.setPixmap(QPixmap())
            self.diff_preview.setText(self._tr("comparison_preview_unavailable"))
            return
        difference = ImageChops.difference(current, other)
        channels = difference.split()
        maximum = ImageChops.lighter(
            ImageChops.lighter(channels[0], channels[1]), channels[2]
        )
        mask = maximum.point(lambda value: 255 if value > 12 else 0)
        muted = ImageEnhance.Brightness(current).enhance(0.7)
        highlighted = Image.composite(
            Image.new("RGB", current.size, (230, 52, 52)), muted, mask
        )
        self._set_preview(self.diff_preview, highlighted)

    def _set_preview(self, label: QLabel, image: Image.Image | None) -> None:
        label.setText("")
        if image is None:
            label.setPixmap(QPixmap())
            label.setText(self._tr("comparison_page_missing"))
        else:
            label.setPixmap(self._pixmap(image))

    def done(self, result: int) -> None:
        self._current_document.close()
        self._comparison_document.close()
        super().done(result)


class _DocumentMarksPreview(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.spec = DocumentMarksSpec()
        self.setMinimumSize(250, 330)

    def set_spec(self, spec: DocumentMarksSpec) -> None:
        self.spec = spec
        self.update()

    @staticmethod
    def _sample(text: str, title: str) -> str:
        return (
            text.replace("{page}", "1")
            .replace("{pages}", "5")
            .replace("{date}", date.today().isoformat())
            .replace("{title}", title or "Document")
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.palette().window())
        available = self.rect().adjusted(12, 12, -12, -12)
        height = min(available.height(), int(available.width() * 1.414))
        width = int(height / 1.414)
        if width > available.width():
            width = available.width()
            height = int(width * 1.414)
        page = QRectF(
            available.center().x() - width / 2,
            available.center().y() - height / 2,
            width,
            height,
        )
        painter.fillRect(page, Qt.white)
        painter.setPen(QPen(QColor("#9aa4ad"), 1))
        painter.drawRect(page)

        scale = page.width() / 595.0
        margin = max(5.0, self.spec.margin * scale)
        font = QFont(self.spec.font_family)
        font.setPointSizeF(max(5.0, self.spec.font_size * scale * 1.4))
        painter.setFont(font)
        painter.setPen(_int_to_qcolor(self.spec.color))
        third = (page.width() - margin * 2) / 3
        title = self.spec.document_title
        headers = (
            self.spec.header_left,
            self.spec.header_center,
            self.spec.header_right,
        )
        footers = (
            self.spec.footer_left,
            self.spec.footer_center,
            self.spec.footer_right,
        )
        alignments = (Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight)
        for index, alignment in enumerate(alignments):
            x = page.left() + margin + index * third
            header = QRectF(x, page.top() + margin, third, 20)
            footer = QRectF(x, page.bottom() - margin - 20, third, 20)
            painter.drawText(
                header,
                alignment | Qt.AlignTop,
                self._sample(headers[index], title),
            )
            painter.drawText(
                footer,
                alignment | Qt.AlignBottom,
                self._sample(footers[index], title),
            )

        watermark = self._sample(self.spec.watermark_text, title)
        if watermark:
            painter.save()
            painter.translate(page.center())
            painter.rotate(self.spec.watermark_rotation)
            painter.setOpacity(self.spec.watermark_opacity)
            watermark_font = QFont(self.spec.font_family)
            watermark_font.setPointSizeF(
                max(8.0, self.spec.watermark_font_size * scale * 1.15)
            )
            painter.setFont(watermark_font)
            painter.setPen(_int_to_qcolor(self.spec.watermark_color))
            painter.drawText(
                QRectF(-page.width() * 0.45, -40, page.width() * 0.9, 80),
                Qt.AlignCenter,
                watermark,
            )
            painter.restore()
        painter.end()


class DocumentMarksDialog(QDialog):
    """Configure headers, footers and a reusable text watermark."""

    def __init__(
        self,
        document_title: str,
        has_existing_marks: bool,
        parent=None,
        translator: Translator | None = None,
    ) -> None:
        super().__init__(parent)
        self._tr = _translator(translator)
        self._document_title = document_title
        self._header_color = QColor(0, 0, 0)
        self._watermark_color = QColor(111, 119, 130)
        self.remove_requested = False
        self.setWindowTitle(self._tr("document_marks_title"))
        self.resize(900, 650)

        tabs = QTabWidget()
        header_page = QWidget()
        header_grid = QGridLayout(header_page)
        self.header_left = QLineEdit()
        self.header_center = QLineEdit()
        self.header_right = QLineEdit()
        self.footer_left = QLineEdit()
        self.footer_center = QLineEdit()
        self.footer_center.setPlaceholderText("{page} / {pages}")
        self.footer_right = QLineEdit()
        header_grid.addWidget(QLabel(self._tr("header_left")), 0, 0)
        header_grid.addWidget(QLabel(self._tr("header_center")), 0, 1)
        header_grid.addWidget(QLabel(self._tr("header_right")), 0, 2)
        header_grid.addWidget(self.header_left, 1, 0)
        header_grid.addWidget(self.header_center, 1, 1)
        header_grid.addWidget(self.header_right, 1, 2)
        header_grid.addWidget(QLabel(self._tr("footer_left")), 2, 0)
        header_grid.addWidget(QLabel(self._tr("footer_center")), 2, 1)
        header_grid.addWidget(QLabel(self._tr("footer_right")), 2, 2)
        header_grid.addWidget(self.footer_left, 3, 0)
        header_grid.addWidget(self.footer_center, 3, 1)
        header_grid.addWidget(self.footer_right, 3, 2)
        token_hint = QLabel(self._tr("document_mark_tokens"))
        token_hint.setWordWrap(True)
        header_grid.addWidget(token_hint, 4, 0, 1, 3)
        tabs.addTab(header_page, self._tr("header_footer"))

        watermark_page = QWidget()
        watermark_form = QFormLayout(watermark_page)
        self.watermark_text = QLineEdit()
        self.watermark_text.setPlaceholderText("CONFIDENTIAL")
        self.watermark_size = QDoubleSpinBox()
        self.watermark_size.setRange(8, 240)
        self.watermark_size.setValue(54)
        self.watermark_size.setSuffix(" pt")
        self.watermark_opacity = QSpinBox()
        self.watermark_opacity.setRange(1, 100)
        self.watermark_opacity.setValue(18)
        self.watermark_opacity.setSuffix(" %")
        self.watermark_rotation = QComboBox()
        for value in (-45, 0, 45, 90):
            self.watermark_rotation.addItem(f"{value}°", value)
        self.watermark_overlay = QCheckBox(self._tr("watermark_in_front"))
        self.watermark_color_button = QPushButton(self._tr("text_color"))
        self.watermark_color_button.clicked.connect(self._choose_watermark_color)
        watermark_form.addRow(self._tr("watermark_text"), self.watermark_text)
        watermark_form.addRow(self._tr("font_size"), self.watermark_size)
        watermark_form.addRow(self._tr("opacity"), self.watermark_opacity)
        watermark_form.addRow(self._tr("rotation"), self.watermark_rotation)
        watermark_form.addRow(self._tr("text_color"), self.watermark_color_button)
        watermark_form.addRow("", self.watermark_overlay)
        tabs.addTab(watermark_page, self._tr("watermark"))

        self.font_family = QFontComboBox()
        self.font_family.setCurrentFont(QFont("Arial"))
        self.header_size = QDoubleSpinBox()
        self.header_size.setRange(4, 36)
        self.header_size.setValue(9)
        self.header_size.setSuffix(" pt")
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 144)
        self.margin.setValue(24)
        self.margin.setSuffix(" pt")
        self.header_color_button = QPushButton(self._tr("text_color"))
        self.header_color_button.clicked.connect(self._choose_header_color)
        self.page_scope = QComboBox()
        self.page_scope.addItem(self._tr("all_pages"), "all")
        self.page_scope.addItem(self._tr("odd_pages"), "odd")
        self.page_scope.addItem(self._tr("even_pages"), "even")
        self.skip_first = QCheckBox(self._tr("skip_first_page"))
        options = QFormLayout()
        options.addRow(self._tr("font"), self.font_family)
        options.addRow(self._tr("font_size"), self.header_size)
        options.addRow(self._tr("page_margin"), self.margin)
        options.addRow(self._tr("text_color"), self.header_color_button)
        options.addRow(self._tr("page_scope"), self.page_scope)
        options.addRow("", self.skip_first)

        self.preview = _DocumentMarksPreview()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(tabs)
        left_layout.addLayout(options)
        body = QSplitter(Qt.Horizontal)
        body.addWidget(left)
        body.addWidget(self.preview)
        body.setSizes((580, 300))

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Apply | QDialogButtonBox.Cancel
        )
        apply_button = self.buttons.button(QDialogButtonBox.Apply)
        apply_button.setText(self._tr("apply"))
        self.buttons.button(QDialogButtonBox.Cancel).setText(self._tr("cancel"))
        apply_button.clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        if has_existing_marks:
            remove = self.buttons.addButton(
                self._tr("remove_document_marks"), QDialogButtonBox.DestructiveRole
            )
            remove.clicked.connect(self._request_remove)

        layout = QVBoxLayout(self)
        layout.addWidget(body)
        layout.addWidget(self.buttons)

        for edit in (
            self.header_left,
            self.header_center,
            self.header_right,
            self.footer_left,
            self.footer_center,
            self.footer_right,
            self.watermark_text,
        ):
            edit.textChanged.connect(self._update_preview)
        for spin in (
            self.header_size,
            self.margin,
            self.watermark_size,
            self.watermark_opacity,
        ):
            spin.valueChanged.connect(self._update_preview)
        self.font_family.currentFontChanged.connect(self._update_preview)
        self.watermark_rotation.currentIndexChanged.connect(self._update_preview)
        self.watermark_overlay.toggled.connect(self._update_preview)
        self.page_scope.currentIndexChanged.connect(self._update_preview)
        self.skip_first.toggled.connect(self._update_preview)
        self._update_color_buttons()
        self._update_preview()

    def _request_remove(self) -> None:
        self.remove_requested = True
        super().accept()

    def _choose_header_color(self) -> None:
        color = QColorDialog.getColor(
            self._header_color, self, self._tr("choose_text_color")
        )
        if color.isValid():
            self._header_color = color
            self._update_color_buttons()
            self._update_preview()

    def _choose_watermark_color(self) -> None:
        color = QColorDialog.getColor(
            self._watermark_color, self, self._tr("choose_text_color")
        )
        if color.isValid():
            self._watermark_color = color
            self._update_color_buttons()
            self._update_preview()

    def _update_color_buttons(self) -> None:
        for button, color in (
            (self.header_color_button, self._header_color),
            (self.watermark_color_button, self._watermark_color),
        ):
            foreground = "#000000" if color.lightness() > 145 else "#ffffff"
            button.setStyleSheet(
                f"background-color: {color.name()}; color: {foreground};"
            )

    def marks_spec(self) -> DocumentMarksSpec:
        return DocumentMarksSpec(
            header_left=self.header_left.text(),
            header_center=self.header_center.text(),
            header_right=self.header_right.text(),
            footer_left=self.footer_left.text(),
            footer_center=self.footer_center.text(),
            footer_right=self.footer_right.text(),
            font_family=self.font_family.currentFont().family(),
            font_size=self.header_size.value(),
            color=_qcolor_to_int(self._header_color),
            margin=self.margin.value(),
            watermark_text=self.watermark_text.text(),
            watermark_font_size=self.watermark_size.value(),
            watermark_color=_qcolor_to_int(self._watermark_color),
            watermark_opacity=self.watermark_opacity.value() / 100.0,
            watermark_rotation=float(self.watermark_rotation.currentData()),
            watermark_overlay=self.watermark_overlay.isChecked(),
            page_mode=str(self.page_scope.currentData()),
            skip_first_page=self.skip_first.isChecked(),
            document_title=self._document_title,
        )

    def _update_preview(self, *_args) -> None:
        self.preview.set_spec(self.marks_spec())

    def accept(self) -> None:
        spec = self.marks_spec()
        if not any(
            value.strip()
            for value in (
                spec.header_left,
                spec.header_center,
                spec.header_right,
                spec.footer_left,
                spec.footer_center,
                spec.footer_right,
                spec.watermark_text,
            )
        ):
            QMessageBox.warning(
                self, self._tr("document_marks_title"), self._tr("document_marks_empty")
            )
            return
        super().accept()


class PageCropDialog(QDialog):
    """Collect non-destructive visual crop margins and their page scope."""

    POINTS_PER_MM = 72.0 / 25.4

    def __init__(
        self,
        current_size: tuple[float, float],
        selected_sizes: list[tuple[float, float]],
        all_sizes: list[tuple[float, float]],
        parent=None,
        translator: Translator | None = None,
    ) -> None:
        super().__init__(parent)
        self._tr = _translator(translator)
        self._current_size = current_size
        self._selected_sizes = selected_sizes or [current_size]
        self._all_sizes = all_sizes or [current_size]
        self.setWindowTitle(self._tr("crop_pages_title"))
        self.setMinimumWidth(460)

        intro = QLabel(self._tr("crop_pages_intro"))
        intro.setWordWrap(True)

        self.scope_box = QComboBox()
        self.scope_box.addItem(self._tr("current_page"), "current")
        if len(self._selected_sizes) > 1:
            self.scope_box.addItem(
                self._tr("selected_pages", count=len(self._selected_sizes)),
                "selected",
            )
            self.scope_box.setCurrentIndex(1)
        self.scope_box.addItem(self._tr("all_pages"), "all")

        self.left_box = self._margin_box()
        self.top_box = self._margin_box()
        self.right_box = self._margin_box()
        self.bottom_box = self._margin_box()
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.validation_label = QLabel()
        self.validation_label.setObjectName("cropValidation")
        self.validation_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow(self._tr("page_scope"), self.scope_box)
        form.addRow(self._tr("crop_left"), self.left_box)
        form.addRow(self._tr("crop_top"), self.top_box)
        form.addRow(self._tr("crop_right"), self.right_box)
        form.addRow(self._tr("crop_bottom"), self.bottom_box)
        form.addRow(self._tr("result"), self.result_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Apply | QDialogButtonBox.Cancel
        )
        self.apply_button = self.buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText(self._tr("apply"))
        self.buttons.button(QDialogButtonBox.Cancel).setText(self._tr("cancel"))
        self.apply_button.clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.validation_label)
        layout.addWidget(self.buttons)

        self.scope_box.currentIndexChanged.connect(self._update_validation)
        for box in (self.left_box, self.top_box, self.right_box, self.bottom_box):
            box.valueChanged.connect(self._update_validation)
        self._update_validation()

    @staticmethod
    def _margin_box() -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(0.0, 1000.0)
        box.setDecimals(1)
        box.setSingleStep(1.0)
        box.setSuffix(" mm")
        return box

    @property
    def scope(self) -> str:
        return str(self.scope_box.currentData())

    @property
    def margins_points(self) -> tuple[float, float, float, float]:
        return tuple(
            box.value() * self.POINTS_PER_MM
            for box in (self.left_box, self.top_box, self.right_box, self.bottom_box)
        )

    def _target_sizes(self) -> list[tuple[float, float]]:
        if self.scope == "all":
            return self._all_sizes
        if self.scope == "selected":
            return self._selected_sizes
        return [self._current_size]

    def _update_validation(self, *_args) -> None:
        left, top, right, bottom = self.margins_points
        targets = self._target_sizes()
        minimum_width = min(size[0] for size in targets)
        minimum_height = min(size[1] for size in targets)
        result_width = minimum_width - left - right
        result_height = minimum_height - top - bottom
        self.result_label.setText(
            self._tr(
                "crop_result",
                width=max(0.0, result_width) / self.POINTS_PER_MM,
                height=max(0.0, result_height) / self.POINTS_PER_MM,
            )
        )
        if not any(value > 0 for value in (left, top, right, bottom)):
            message = self._tr("crop_enter_margin")
        elif result_width < 36.0 or result_height < 36.0:
            message = self._tr("crop_too_small")
        else:
            message = ""
        self.validation_label.setText(message)
        self.apply_button.setEnabled(not message)


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


class PageResizeDialog(QDialog):
    """Choose a physical page size, content handling, and page scope."""

    POINTS_PER_MM = 72.0 / 25.4
    PAGE_SIZES_MM = NewDocumentDialog.PAGE_SIZES_MM

    def __init__(
        self,
        current_size: tuple[float, float],
        selected_count: int,
        page_count: int,
        parent=None,
        translator: Translator | None = None,
    ) -> None:
        super().__init__(parent)
        self._tr = _translator(translator)
        self._current_size = current_size
        self._selected_count = max(1, int(selected_count))
        self._page_count = max(1, int(page_count))
        self.setWindowTitle(self._tr("resize_pages_title"))
        self.setMinimumWidth(500)

        intro = QLabel(self._tr("resize_pages_intro"))
        intro.setWordWrap(True)

        current_mm = tuple(value / self.POINTS_PER_MM for value in current_size)
        self.page_size_box = QComboBox()
        self.page_size_box.addItem(
            self._tr(
                "current_page_size",
                width=current_mm[0],
                height=current_mm[1],
            ),
            current_mm,
        )
        for label, width, height in self.PAGE_SIZES_MM:
            self.page_size_box.addItem(label, (width, height))
        self.page_size_box.addItem(self._tr("custom_size"), None)

        self.orientation_box = QComboBox()
        self.orientation_box.addItem(self._tr("portrait"), "portrait")
        self.orientation_box.addItem(self._tr("landscape"), "landscape")
        if current_mm[0] > current_mm[1]:
            self.orientation_box.setCurrentIndex(1)

        self.width_box = QDoubleSpinBox()
        self.width_box.setRange(25.0, 2000.0)
        self.width_box.setDecimals(1)
        self.width_box.setSuffix(" mm")
        self.height_box = QDoubleSpinBox()
        self.height_box.setRange(25.0, 2000.0)
        self.height_box.setDecimals(1)
        self.height_box.setSuffix(" mm")

        self.mode_box = QComboBox()
        self.mode_box.addItem(self._tr("resize_fit_content"), "fit")
        self.mode_box.addItem(self._tr("resize_canvas_only"), "canvas")

        self.scope_box = QComboBox()
        self.scope_box.addItem(self._tr("current_page"), "current")
        if self._selected_count > 1:
            self.scope_box.addItem(
                self._tr("selected_pages", count=self._selected_count),
                "selected",
            )
            self.scope_box.setCurrentIndex(1)
        self.scope_box.addItem(self._tr("all_pages"), "all")

        self.result_label = QLabel()
        self.result_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow(self._tr("page_size"), self.page_size_box)
        form.addRow(self._tr("orientation"), self.orientation_box)
        form.addRow(self._tr("width"), self.width_box)
        form.addRow(self._tr("height"), self.height_box)
        form.addRow(self._tr("resize_mode"), self.mode_box)
        form.addRow(self._tr("page_scope"), self.scope_box)
        form.addRow(self._tr("result"), self.result_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Apply | QDialogButtonBox.Cancel
        )
        self.apply_button = self.buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText(self._tr("apply"))
        self.buttons.button(QDialogButtonBox.Cancel).setText(self._tr("cancel"))
        self.apply_button.clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

        self.page_size_box.currentIndexChanged.connect(self._page_size_changed)
        self.orientation_box.currentIndexChanged.connect(self._update_result)
        self.width_box.valueChanged.connect(self._update_result)
        self.height_box.valueChanged.connect(self._update_result)
        self.mode_box.currentIndexChanged.connect(self._update_result)
        self.scope_box.currentIndexChanged.connect(self._update_result)
        self._page_size_changed()

    @property
    def scope(self) -> str:
        return str(self.scope_box.currentData())

    @property
    def resize_mode(self) -> str:
        return str(self.mode_box.currentData())

    @property
    def page_dimensions_mm(self) -> tuple[float, float]:
        width = self.width_box.value()
        height = self.height_box.value()
        if self.orientation_box.currentData() == "landscape":
            width, height = height, width
        return width, height

    @property
    def target_dimensions_points(self) -> tuple[float, float]:
        width, height = self.page_dimensions_mm
        return width * self.POINTS_PER_MM, height * self.POINTS_PER_MM

    def _page_size_changed(self, *_args) -> None:
        dimensions = self.page_size_box.currentData()
        custom = dimensions is None
        if dimensions is not None:
            width, height = (float(value) for value in dimensions)
            self.width_box.setValue(min(width, height))
            self.height_box.setValue(max(width, height))
        self.width_box.setEnabled(custom)
        self.height_box.setEnabled(custom)
        self._update_result()

    def _target_count(self) -> int:
        if self.scope == "all":
            return self._page_count
        if self.scope == "selected":
            return self._selected_count
        return 1

    def _update_result(self, *_args) -> None:
        width, height = self.page_dimensions_mm
        self.result_label.setText(
            self._tr(
                "resize_result",
                width=width,
                height=height,
                count=self._target_count(),
            )
        )


class FormFieldDialog(QDialog):
    """Collect properties for a new standard AcroForm field."""

    def __init__(
        self,
        suggested_name: str,
        parent=None,
        translator: Translator | None = None,
    ) -> None:
        super().__init__(parent)
        import pymupdf

        self._tr = _translator(translator)
        self.setWindowTitle(self._tr("create_form_field"))
        self.setMinimumWidth(480)

        self.type_box = QComboBox()
        self.type_box.addItem(self._tr("form_type_text"), pymupdf.PDF_WIDGET_TYPE_TEXT)
        self.type_box.addItem(
            self._tr("form_type_checkbox"), pymupdf.PDF_WIDGET_TYPE_CHECKBOX
        )
        self.type_box.addItem(
            self._tr("form_type_combo"), pymupdf.PDF_WIDGET_TYPE_COMBOBOX
        )
        self.type_box.addItem(
            self._tr("form_type_list"), pymupdf.PDF_WIDGET_TYPE_LISTBOX
        )
        self.type_box.addItem(
            self._tr("form_type_signature"), pymupdf.PDF_WIDGET_TYPE_SIGNATURE
        )
        self.name_edit = QLineEdit(suggested_name)
        self.name_edit.setClearButtonEnabled(True)
        self.label_edit = QLineEdit()
        self.value_edit = QLineEdit()
        self.choices_edit = QPlainTextEdit()
        self.choices_edit.setMaximumHeight(90)
        self.choices_edit.setPlaceholderText(self._tr("form_choices_hint"))
        self.default_checked = QCheckBox(self._tr("form_default_checked"))
        self.multiline = QCheckBox(self._tr("form_multiline"))
        self.read_only = QCheckBox(self._tr("form_read_only"))
        self.required = QCheckBox(self._tr("form_required"))

        form = QFormLayout()
        form.addRow(self._tr("form_field_type"), self.type_box)
        form.addRow(self._tr("form_field_name"), self.name_edit)
        form.addRow(self._tr("form_field_label"), self.label_edit)
        form.addRow(self._tr("form_default_value"), self.value_edit)
        form.addRow(self._tr("form_choices"), self.choices_edit)
        form.addRow("", self.default_checked)
        form.addRow("", self.multiline)
        form.addRow("", self.required)
        form.addRow("", self.read_only)

        hint = QLabel(self._tr("form_shared_name_hint"))
        hint.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self._tr("create"))
        buttons.button(QDialogButtonBox.Cancel).setText(self._tr("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.type_box.currentIndexChanged.connect(self._type_changed)
        self._type_changed()
        self.name_edit.selectAll()
        self.name_edit.setFocus()

    def _type_changed(self, *args) -> None:
        import pymupdf

        field_type = int(self.type_box.currentData())
        choice = field_type in (
            pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
            pymupdf.PDF_WIDGET_TYPE_LISTBOX,
        )
        checkbox = field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX
        text = field_type == pymupdf.PDF_WIDGET_TYPE_TEXT
        self.choices_edit.setVisible(choice)
        label = self.layout().itemAt(0).layout().labelForField(self.choices_edit)
        if label is not None:
            label.setVisible(choice)
        self.value_edit.setVisible(text or choice)
        label = self.layout().itemAt(0).layout().labelForField(self.value_edit)
        if label is not None:
            label.setVisible(text or choice)
        self.default_checked.setVisible(checkbox)
        self.multiline.setVisible(text)

    def accept(self) -> None:
        import pymupdf

        if not self.name_edit.text().strip():
            QMessageBox.warning(
                self,
                self._tr("create_form_field"),
                self._tr("form_name_required"),
            )
            return
        if not self.label_edit.text().strip():
            QMessageBox.warning(
                self, self._tr("create_form_field"), self._tr("form_label_required")
            )
            return
        field_type = int(self.type_box.currentData())
        if field_type in (
            pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
            pymupdf.PDF_WIDGET_TYPE_LISTBOX,
        ) and len(self._choices()) < 2:
            QMessageBox.warning(
                self,
                self._tr("create_form_field"),
                self._tr("form_choices_required"),
            )
            return
        super().accept()

    def _choices(self) -> tuple[str, ...]:
        return tuple(
            value.strip()
            for value in self.choices_edit.toPlainText().splitlines()
            if value.strip()
        )

    def field_spec(self) -> FormFieldSpec:
        import pymupdf

        field_type = int(self.type_box.currentData())
        value = self.value_edit.text()
        if field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
            value = "Yes" if self.default_checked.isChecked() else "Off"
        return FormFieldSpec(
            type_code=field_type,
            name=self.name_edit.text().strip(),
            label=self.label_edit.text().strip(),
            value=value,
            choices=self._choices(),
            read_only=self.read_only.isChecked(),
            required=self.required.isChecked(),
            multiline=self.multiline.isChecked(),
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
        self.draw_mode.toggled.connect(self._signature_mode_changed)

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
        record_signature_trace("dialog_initialized", mode=self._signature_mode())

    def _signature_mode(self) -> str:
        return "drawn" if self.draw_mode.isChecked() else "typed"

    def _signature_mode_changed(self, checked: bool) -> None:
        self.stack.setCurrentIndex(0 if checked else 1)
        record_signature_trace("mode_changed", mode=self._signature_mode())

    def _validate_and_accept(self) -> None:
        record_signature_trace(
            "accept_requested",
            mode=self._signature_mode(),
            text_length=len(self.typed_text.text().strip()),
        )
        if self.draw_mode.isChecked() and not self.pad.has_ink:
            QMessageBox.warning(self, self._tr("empty_signature"), self._tr("empty_draw"))
            return
        if self.type_mode.isChecked() and not self.typed_text.text().strip():
            QMessageBox.warning(self, self._tr("empty_signature"), self._tr("empty_type"))
            return
        self.accept()

    def signature_data(self) -> tuple[bytes, float, float, str]:
        mode = self._signature_mode()
        record_signature_trace(
            "signature_data_started",
            mode=mode,
            text_length=len(self.typed_text.text().strip()),
        )
        if self.draw_mode.isChecked():
            record_signature_trace("drawn_crop_started", mode=mode)
            image = self.pad.signature_image()
            record_signature_trace(
                "drawn_crop_finished",
                mode=mode,
                image_width=image.width(),
                image_height=image.height(),
            )
            description = self._tr("drawn_signature_desc")
        else:
            image = self._typed_signature_image()
            description = self._tr("typed_signature_desc", text=self.typed_text.text().strip())
        angle = self.angle_box.value()
        return _image_to_png(image), self.width_box.value(), angle, description

    def _typed_signature_image(self) -> QImage:
        text = self.typed_text.text().strip()
        record_signature_trace(
            "typed_metrics_started", mode="typed", text_length=len(text)
        )
        font = QFont(self.typed_font.currentFont().family())
        font.setPixelSize(int(self.typed_size.value() * 4))
        font.setBold(self.typed_bold.isChecked())
        font.setItalic(self.typed_italic.isChecked())
        bounds = QFontMetricsF(font).tightBoundingRect(text)
        margin = 24
        max_content_width = 4096 - margin * 2
        max_content_height = 1024 - margin * 2
        fit_factor = min(
            1.0,
            max_content_width / max(1.0, bounds.width()),
            max_content_height / max(1.0, bounds.height()),
        )
        if fit_factor < 1.0:
            font.setPixelSize(max(1, int(font.pixelSize() * fit_factor)))
            bounds = QFontMetricsF(font).tightBoundingRect(text)
        record_signature_trace("typed_metrics_ready", mode="typed")
        image = QImage(
            min(4096, max(2, ceil(bounds.width()) + margin * 2)),
            min(1024, max(2, ceil(bounds.height()) + margin * 2)),
            QImage.Format_ARGB32_Premultiplied,
        )
        if image.isNull():
            raise RuntimeError("Unable to allocate the typed signature image.")
        record_signature_trace(
            "typed_image_allocated",
            mode="typed",
            image_width=image.width(),
            image_height=image.height(),
        )
        image.fill(Qt.transparent)
        painter = QPainter(image)
        if not painter.isActive():
            raise RuntimeError("Unable to render the typed signature image.")
        record_signature_trace("typed_painter_started", mode="typed")
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setFont(font)
        painter.setPen(Qt.black)
        record_signature_trace("typed_draw_started", mode="typed")
        painter.drawText(
            QPointF(margin - bounds.left(), margin - bounds.top()),
            text,
        )
        painter.end()
        record_signature_trace(
            "typed_draw_finished",
            mode="typed",
            image_width=image.width(),
            image_height=image.height(),
        )
        return image


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
    record_signature_trace(
        "png_encode_started",
        image_width=image.width(),
        image_height=image.height(),
    )
    payload = QByteArray()
    buffer = QBuffer(payload)
    if not buffer.open(QIODevice.WriteOnly):
        raise RuntimeError("Unable to create signature image buffer.")
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Unable to encode signature as PNG.")
    buffer.close()
    result = bytes(payload)
    record_signature_trace(
        "png_encode_finished",
        image_width=image.width(),
        image_height=image.height(),
        payload_bytes=len(result),
    )
    return result


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
