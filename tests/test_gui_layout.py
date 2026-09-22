import json
import os
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
import pytest
from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QEventLoop,
    QModelIndex,
    QPoint,
    QPointF,
    QRect,
    QSettings,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFocusEvent,
    QFont,
    QFontDatabase,
    QImage,
    QKeySequence,
    QPalette,
    QPixmap,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QGraphicsPixmapItem,
    QMenu,
    QMessageBox,
    QToolBar,
)

import openpdf_editor.main_window as main_window_module
from openpdf_editor.engine import FormFieldSpec, PdfEngine
from openpdf_editor.main_window import (
    FONT_SIZE_PRESETS,
    MainWindow,
    PageView,
    SignatureGraphicsItem,
    VisualImageItem,
)
from openpdf_editor.text_layer import InlineTextEditor, TextObjectGraphicsItem


SAMPLES = Path(os.environ.get("OPENPDF_TEST_SAMPLES", Path(__file__).resolve().parents[2] / "upload"))


def _application() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("Nettongia PDF Editor Tests")
    app.setApplicationName("Nettongia PDF Editor Tests")
    return app


def _form_pdf_bytes() -> bytes:
    document = fitz.open()
    page = document.new_page(width=420, height=300)
    for field_type, name, label, rect, value, choices in (
        (fitz.PDF_WIDGET_TYPE_TEXT, "customer", "Customer", (40, 40, 240, 70), "Old", None),
        (fitz.PDF_WIDGET_TYPE_CHECKBOX, "approved", "Approved", (40, 90, 60, 110), None, None),
        (fitz.PDF_WIDGET_TYPE_COMBOBOX, "country", "Country", (40, 130, 240, 160), "Czechia", ["Czechia", "Poland"]),
    ):
        widget = fitz.Widget()
        widget.field_type = field_type
        widget.field_name = name
        widget.field_label = label
        widget.rect = fitz.Rect(rect)
        if value is not None:
            widget.field_value = value
        if choices is not None:
            widget.choice_values = choices
        page.add_widget(widget)
    try:
        return document.tobytes()
    finally:
        document.close()


def test_text_controls_use_one_toolbar_without_overlap() -> None:
    app = _application()
    window = MainWindow()
    window.resize(910, 720)
    window.set_theme("dark")
    window.show()
    app.processEvents()

    assert len(window.findChildren(QToolBar)) == 1
    assert window.toolbar.height() < 60
    assert window.text_controls_widget.isVisible()
    assert window.language_button.isVisible()
    assert window.toolbar.widgetForAction(window.print_action).isVisible()
    assert window.toolbar.width() - 1 - window.language_button.geometry().right() <= 4
    assert len(window.language_actions) == 21
    assert all(not action.icon().isNull() for action in window.language_actions.values())
    assert not window.sidebar_tabs.isTabEnabled(window.outline_tab_index)

    action_order = window.toolbar.actions()
    assert action_order.index(window.save_action) < action_order.index(
        window.print_action
    )
    assert action_order.index(window.print_action) < action_order.index(
        window.undo_action
    )
    assert window.save_action.shortcut() == QKeySequence(QKeySequence.Save)
    assert window.save_as_action.shortcut() == QKeySequence(QKeySequence.SaveAs)
    assert window.save_copy_action.shortcut() == QKeySequence("Ctrl+Alt+S")
    assert window.move_page_up_action.shortcut() == QKeySequence("Alt+Shift+Up")
    assert window.move_page_down_action.shortcut() == QKeySequence("Alt+Shift+Down")
    assert window.rotate_page_left_action.shortcut() == QKeySequence("Ctrl+Shift+Left")
    assert window.rotate_page_right_action.shortcut() == QKeySequence("Ctrl+Shift+Right")
    file_actions = window.file_menu.actions()
    assert file_actions.index(window.save_action) < file_actions.index(
        window.save_as_action
    )
    assert file_actions.index(window.save_as_action) < file_actions.index(
        window.save_copy_action
    )
    assert window.edit_original_image_action in window.image_menu.actions()
    assert window.export_diagnostics_action in window.help_menu.actions()
    assert window.move_page_up_action in window.page_menu.actions()
    assert window.move_page_down_action in window.page_menu.actions()
    assert window.rotate_page_left_action in window.page_menu.actions()
    assert window.rotate_page_right_action in window.page_menu.actions()

    widgets = (
        window.text_font_box,
        window.text_size_box,
        window.text_bold_button,
        window.text_italic_button,
        window.text_underline_button,
        window.text_color_button,
    )
    rects = []
    for widget in widgets:
        position = widget.mapTo(window.text_controls_widget, QPoint(0, 0))
        rects.append(QRect(position, widget.size()))
    for left, right in zip(rects, rects[1:]):
        assert right.left() - left.right() - 1 >= 3

    assert window.text_size_box.isEditable()
    assert window.text_size_box.count() == len(FONT_SIZE_PRESETS)
    assert window.text_size_box.currentText() == "12 pt"
    assert window.text_size_box.itemText(0) == "6 pt"
    assert window.text_size_box.itemText(window.text_size_box.count() - 1) == "200 pt"
    window.text_size_box.setCurrentText("13,5 pt")
    window._font_size_changed()
    assert window._font_size_value == 13.5
    assert window.text_size_box.currentText() == "13.5 pt"
    window.text_size_box.setCurrentText("200 pt")
    window._font_size_changed()
    app.processEvents()
    size_editor = window.text_size_box.lineEdit()
    assert window.text_size_box.width() == 72
    assert size_editor.alignment() & Qt.AlignLeft
    assert size_editor.cursorPosition() == 0
    assert size_editor.toolTip() == "200 pt"
    assert "border-bottom" not in window.text_color_button.styleSheet()

    popup_palette = window.text_font_box.view().palette()
    assert popup_palette.color(QPalette.Active, QPalette.Base) == QColor("#ffffff")
    assert popup_palette.color(QPalette.Active, QPalette.Text) == QColor("#111820")
    size_popup_palette = window.text_size_box.view().palette()
    assert size_popup_palette.color(QPalette.Active, QPalette.Base) == QColor("#ffffff")
    assert size_popup_palette.color(QPalette.Active, QPalette.Text) == QColor("#111820")

    # Headless Windows runners can expose no system font families even though
    # the same Qt build enumerates them in an interactive desktop session.
    families = QFontDatabase.families()
    longest_family = max(families, key=len) if families else "Unavailable Test Font Family"
    window.text_font_box.setCurrentFont(QFont(longest_family))
    app.processEvents()
    font_editor = window.text_font_box.lineEdit()
    assert font_editor.cursorPosition() == 0
    expected_font_name = (
        window.text_font_box.currentText().strip()
        or window.text_font_box.currentFont().family()
    )
    assert font_editor.toolTip() == expected_font_name

    editor = InlineTextEditor("Text", "Arial", 12, False, False, False, QColor("#000000"), True)
    assert "background:rgba(255,255,255,252)" in editor.styleSheet().replace(" ", "")

    editor.deleteLater()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_anonymized_diagnostics_are_reviewed_before_export(
    tmp_path: Path, monkeypatch
) -> None:
    app = _application()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setValue("ui/language", "cs")
    target = tmp_path / "diagnostics.zip"
    window = MainWindow(
        settings=settings,
        recovery_path=tmp_path / "recovery",
        operation_log_path=tmp_path / "operation-log.jsonl",
    )
    review: dict[str, str] = {}

    def approve(_parent, title, body, *_args):
        review["title"] = title
        review["body"] = body
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", approve)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(target), "ZIP"),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: None)

    assert window.export_diagnostics()
    assert review["title"] == "Anonymizovaná diagnostika"
    assert "Nezahrnuto:" in review["body"]
    assert "názvy souborů, cesty" in review["body"]
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        session = json.loads(archive.read("session.json"))
        assert session["document_open"] is False
        operations = json.loads(archive.read("operations.json"))["records"]
        assert any(item["event"] == "diagnostic_exported" for item in operations)

    window.close()
    window.deleteLater()
    app.processEvents()


def test_thumbnail_internal_move_reorders_pdf_and_is_undoable(tmp_path: Path) -> None:
    app = _application()
    document = fitz.open()
    for label in ("PAGE A", "PAGE B", "PAGE C"):
        page = document.new_page(width=420, height=300)
        page.insert_text((50, 90), label, fontsize=28)
    engine = PdfEngine()
    engine.load_bytes(document.tobytes())
    document.close()

    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, None, already_saved=True)
    assert window.page_list.dragDropMode() == QAbstractItemView.InternalMove
    assert window.page_list.model().moveRow(
        QModelIndex(), 0, QModelIndex(), 3
    )
    app.processEvents(QEventLoop.AllEvents, 200)

    assert [window.engine._source[index].get_text().strip() for index in range(3)] == [
        "PAGE B",
        "PAGE C",
        "PAGE A",
    ]
    assert window.current_page == 2
    assert window.history_index == 1

    window.undo()
    assert [window.engine._source[index].get_text().strip() for index in range(3)] == [
        "PAGE A",
        "PAGE B",
        "PAGE C",
    ]
    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_thumbnail_delete_key_removes_selected_page_and_undo_restores(
    tmp_path: Path, monkeypatch
) -> None:
    app = _application()
    document = fitz.open()
    for label in ("PAGE A", "PAGE B", "PAGE C"):
        page = document.new_page(width=420, height=300)
        page.insert_text((50, 90), label, fontsize=28)
    engine = PdfEngine()
    engine.load_bytes(document.tobytes())
    document.close()

    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, None, already_saved=True)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    window.page_list.setCurrentRow(1)
    window.page_list.setFocus()
    QTest.keyClick(window.page_list, Qt.Key_Delete)
    app.processEvents(QEventLoop.AllEvents, 200)

    assert window.engine.page_count == 2
    assert [window.engine._source[index].get_text().strip() for index in range(2)] == [
        "PAGE A",
        "PAGE C",
    ]
    assert window.current_page == 1
    assert window.history_index == 1

    window.undo()
    assert window.engine.page_count == 3
    assert [window.engine._source[index].get_text().strip() for index in range(3)] == [
        "PAGE A",
        "PAGE B",
        "PAGE C",
    ]

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_thumbnail_context_menu_deletes_the_right_page(
    tmp_path: Path, monkeypatch
) -> None:
    app = _application()
    document = fitz.open()
    for label in ("PAGE A", "PAGE B", "PAGE C"):
        page = document.new_page(width=420, height=300)
        page.insert_text((50, 90), label, fontsize=28)
    engine = PdfEngine()
    engine.load_bytes(document.tobytes())
    document.close()

    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, None, already_saved=True)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

    def choose_delete(menu: QMenu, _position: QPoint):
        action = next(
            action for action in menu.actions() if action.text() == window.trx("delete_page")
        )
        action.trigger()
        return action

    monkeypatch.setattr(window, "_exec_context_menu", choose_delete)
    window._show_page_context_menu(1, QPoint(0, 0))
    app.processEvents(QEventLoop.AllEvents, 200)

    assert [window.engine._source[index].get_text().strip() for index in range(2)] == [
        "PAGE A",
        "PAGE C",
    ]
    assert window.current_page == 1

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_page_rotation_is_undoable_and_available_from_thumbnail_menu(
    tmp_path: Path, monkeypatch
) -> None:
    app = _application()
    document = fitz.open()
    page = document.new_page(width=420, height=300)
    page.insert_text((50, 90), "ROTATE ME", fontsize=28)
    engine = PdfEngine()
    engine.load_bytes(document.tobytes())
    document.close()

    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, None, already_saved=True)

    def choose_rotate_right(menu: QMenu, _position: QPoint):
        action = next(
            action
            for action in menu.actions()
            if action.text() == window.trx("rotate_page_right")
        )
        action.trigger()
        return action

    monkeypatch.setattr(window, "_exec_context_menu", choose_rotate_right)
    window._show_page_context_menu(0, QPoint(0, 0))
    app.processEvents(QEventLoop.AllEvents, 200)

    assert window.engine._source[0].rotation == 90
    assert window.engine.page_rect(0).width == pytest.approx(300)
    assert window.history_index == 1
    assert window.has_unsaved_changes

    window.undo()
    assert window.engine._source[0].rotation == 0
    assert window.engine.page_rect(0).width == pytest.approx(420)
    window.redo()
    assert window.engine._source[0].rotation == 90

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_native_comments_and_highlights_are_listed_and_undoable(
    tmp_path: Path, monkeypatch
) -> None:
    app = _application()
    document = fitz.open()
    page = document.new_page(width=420, height=300)
    page.insert_text((50, 90), "COMMENT TARGET", fontsize=20)
    engine = PdfEngine()
    engine.load_bytes(document.tobytes())
    document.close()

    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, None, already_saved=True)
    window.show()
    app.processEvents()

    monkeypatch.setattr(
        main_window_module.QInputDialog,
        "getMultiLineText",
        lambda *args, **kwargs: ("Verify the drawing note", True),
    )
    window.start_add_comment()
    assert window.page_view.comment_placement_mode
    window._place_comment(100 * window.render_scale, 120 * window.render_scale)
    assert len(window.engine.annotations()) == 1
    assert window.comments_list.count() == 1
    assert "Verify the drawing note" in window.comments_list.item(0).text()
    assert window.history_index == 1

    run = window.engine.text_runs(0)[0]
    window._highlight_text("source", run.key)
    assert [item.type_name for item in window.engine.annotations()] == ["Text", "Highlight"]
    assert window.comments_list.count() == 2
    assert window.history_index == 2

    window.undo()
    assert [item.type_name for item in window.engine.annotations()] == ["Text"]
    assert window.comments_list.count() == 1
    window.redo()
    assert len(window.engine.annotations()) == 2

    window.comments_list.setCurrentRow(0)
    monkeypatch.setattr(
        main_window_module.QInputDialog,
        "getMultiLineText",
        lambda *args, **kwargs: ("Updated review comment", True),
    )
    window.edit_selected_comment()
    assert window.engine.annotations()[0].content == "Updated review comment"
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.Yes,
    )
    window.comments_list.setCurrentRow(0)
    window.delete_selected_annotation()
    assert len(window.engine.annotations()) == 1
    window.undo()
    assert len(window.engine.annotations()) == 2

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_acroform_sidebar_edits_fields_with_undo_redo(
    tmp_path: Path, monkeypatch
) -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(_form_pdf_bytes())
    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, None, already_saved=True)
    window.show()
    app.processEvents()

    assert window.forms_list.count() == 3
    assert window.sidebar_tabs.count() == 2
    assert window.right_sidebar.isTabEnabled(window.forms_tool_index)
    assert not window.right_sidebar.isExpanded()
    window.right_sidebar.setCurrentIndex(window.forms_tool_index)
    assert window.right_sidebar.isExpanded()
    app.processEvents()
    assert window.right_sidebar.width() >= 250
    window.right_sidebar.collapse()
    assert not window.right_sidebar.isExpanded()
    app.processEvents()
    assert window.right_sidebar.width() == 48

    def select_field(name: str) -> None:
        field = next(item for item in window.engine.form_fields() if item.name == name)
        row = next(
            index
            for index in range(window.forms_list.count())
            if int(window.forms_list.item(index).data(Qt.UserRole)) == field.xref
        )
        window.forms_list.setCurrentRow(row)

    select_field("customer")
    monkeypatch.setattr(
        main_window_module.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("New customer", True),
    )
    window.edit_selected_form_field()
    assert {item.name: item.value for item in window.engine.form_fields()}["customer"] == "New customer"
    assert window.history_index == 1
    window.undo()
    assert {item.name: item.value for item in window.engine.form_fields()}["customer"] == "Old"
    window.redo()
    assert {item.name: item.value for item in window.engine.form_fields()}["customer"] == "New customer"

    select_field("approved")
    window.edit_selected_form_field()
    assert next(item for item in window.engine.form_fields() if item.name == "approved").checked

    select_field("country")
    monkeypatch.setattr(
        main_window_module.QInputDialog,
        "getItem",
        lambda *args, **kwargs: ("Poland", True),
    )
    window.edit_selected_form_field()
    assert {item.name: item.value for item in window.engine.form_fields()}["country"] == "Poland"
    assert window.has_unsaved_changes

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_form_field_creation_and_deletion_use_right_sidebar_and_history(
    tmp_path: Path, monkeypatch
) -> None:
    app = _application()
    engine = PdfEngine()
    engine.load_bytes(PdfEngine.blank_document_bytes(420, 300))
    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, None, already_saved=True)
    window.show()
    app.processEvents()

    spec = FormFieldSpec(
        fitz.PDF_WIDGET_TYPE_TEXT,
        "customer_email",
        "Customer email",
        "mail@example.com",
    )

    class AcceptedFormDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return True

        def field_spec(self):
            return spec

    monkeypatch.setattr(main_window_module, "FormFieldDialog", AcceptedFormDialog)
    window.start_create_form_field()
    assert window.page_view.form_field_mode
    window._create_form_field(
        (50, 70, 260, 102),
        window.page_view._page_generation,
    )

    fields = window.engine.form_fields()
    assert len(fields) == 1
    assert fields[0].name == "customer_email"
    assert fields[0].value == "mail@example.com"
    assert window.forms_list.count() == 1
    assert window.right_sidebar.currentIndex() == window.forms_tool_index
    assert window.right_sidebar.isExpanded()
    assert window.history_index == 1

    window.undo()
    assert window.engine.form_fields() == []
    window.redo()
    assert len(window.engine.form_fields()) == 1

    window.forms_list.setCurrentRow(0)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.Yes,
    )
    window.delete_selected_form_field()
    assert window.engine.form_fields() == []
    window.undo()
    assert len(window.engine.form_fields()) == 1

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_area_redaction_is_confirmed_and_supports_undo_redo(
    tmp_path: Path, monkeypatch
) -> None:
    app = _application()
    document = fitz.open()
    page = document.new_page(width=420, height=300)
    page.insert_text((60, 100), "VISIBLE SECRET-97531", fontsize=18)
    source = document.tobytes()
    document.close()

    engine = PdfEngine()
    engine.load_bytes(source)
    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, None, already_saved=True)
    window.show()
    app.processEvents()

    secret_rect = window.engine._source[0].search_for("SECRET-97531")[0]
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.Yes,
    )
    window.start_redact_area()
    assert window.page_view.redaction_mode
    window._confirm_redaction(tuple(secret_rect), window.page_view._page_generation)

    assert "SECRET-97531" not in window.engine._source[0].get_text()
    assert window.history_index == 1
    assert window.has_unsaved_changes
    window.undo()
    assert "SECRET-97531" in window.engine._source[0].get_text()
    window.redo()
    assert "SECRET-97531" not in window.engine._source[0].get_text()

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_source_image_click_is_non_mutating_and_first_drag_preserves_jpeg(tmp_path: Path) -> None:
    app = _application()
    image = QImage(240, 100, QImage.Format_RGB888)
    image.fill(QColor("#285fbd"))
    buffer = QByteArray()
    from PySide6.QtCore import QBuffer, QIODevice

    device = QBuffer(buffer)
    device.open(QIODevice.WriteOnly)
    assert image.save(device, "JPEG", 92)
    jpeg = bytes(buffer)

    document = fitz.open()
    page = document.new_page(width=500, height=400)
    page.insert_image(fitz.Rect(70, 65, 310, 165), stream=jpeg, rotate=90)
    engine = PdfEngine()
    engine.load_bytes(document.tobytes())
    document.close()

    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, None, already_saved=True)
    window.show()
    app.processEvents()
    source_item = next(
        item
        for item in window.page_view.scene().items()
        if isinstance(item, VisualImageItem)
    )
    source_run = source_item.run
    click_position = window.page_view.mapFromScene(source_item.sceneBoundingRect().center())
    QTest.mouseClick(window.page_view.viewport(), Qt.LeftButton, pos=click_position)
    app.processEvents()

    assert window.page_view.selected_visual_ref == ("source", source_run.key)
    assert window.history_index == 0
    assert not window.inserted_images
    assert not window.deleted_images

    source_item._transform_at_press = (
        QPointF(source_item.pos()),
        source_item.scale(),
        source_item.rotation(),
    )
    source_item.setPos(source_item.pos() + QPointF(24, 0))
    source_item._commit_if_changed()
    app.processEvents(QEventLoop.AllEvents, 200)

    assert window.history_index == 1
    assert len(window.inserted_images) == 1
    assert len(window.deleted_images) == 1
    replacement = window.inserted_images[0]
    assert replacement.image_bytes == jpeg
    assert replacement.rotation_degrees == pytest.approx(source_run.rotation_degrees)
    assert any(
        isinstance(item, SignatureGraphicsItem)
        for item in window.page_view.scene().items()
    )

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_page_object_context_menu_deletes_image_and_offers_original_edit(
    tmp_path: Path, monkeypatch
) -> None:
    app = _application()
    image = QImage(180, 90, QImage.Format_RGB888)
    image.fill(QColor("#285fbd"))
    buffer = QByteArray()
    from PySide6.QtCore import QBuffer, QIODevice

    device = QBuffer(buffer)
    device.open(QIODevice.WriteOnly)
    assert image.save(device, "PNG")
    payload = bytes(buffer)

    document = fitz.open()
    page = document.new_page(width=500, height=400)
    page.insert_image(fitz.Rect(70, 65, 250, 155), stream=payload)
    engine = PdfEngine()
    engine.load_bytes(document.tobytes())
    document.close()

    window = MainWindow(recovery_path=tmp_path / "recovery")
    window._start_document_inspection = lambda: None
    window._activate_document(engine, None, already_saved=True)
    window.show()
    app.processEvents()
    source_item = next(
        item
        for item in window.page_view.scene().items()
        if isinstance(item, VisualImageItem)
    )
    click_position = window.page_view.mapFromScene(source_item.sceneBoundingRect().center())
    seen_actions: list[str] = []

    def choose_delete(menu: QMenu, _position: QPoint):
        seen_actions.extend(
            action.text() for action in menu.actions() if not action.isSeparator()
        )
        action = next(
            action for action in menu.actions() if action.text() == window.trx("delete_image")
        )
        action.trigger()
        return action

    monkeypatch.setattr(window, "_exec_context_menu", choose_delete)
    context_event = QContextMenuEvent(
        QContextMenuEvent.Mouse,
        click_position,
        window.page_view.viewport().mapToGlobal(click_position),
    )
    QApplication.sendEvent(window.page_view.viewport(), context_event)
    app.processEvents(QEventLoop.AllEvents, 200)

    assert window.trx("edit_original_image") in seen_actions
    assert window.trx("delete_image") in seen_actions
    assert len(window.deleted_images) == 1
    assert window.history_index == 1
    window.undo()
    assert not window.deleted_images

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_toolbar_formatting_preserves_source_font_and_selection(tmp_path: Path) -> None:
    source = SAMPLES / "KS_Teil_2_2_01_KS26_ROB-KUKA_Projektspezifische_Vorgaben.pdf"
    if not source.exists():
        return
    app = _application()
    window = MainWindow()
    window._maybe_save_changes = lambda: True
    engine = PdfEngine()
    engine.open(source)
    window._activate_document(engine, source, already_saved=True)
    window.show()
    window._select_and_render_page(1)
    app.processEvents(QEventLoop.AllEvents, 50)

    run = next(run for run in engine.text_runs(1) if run.text == "Inhaltsverzeichnis:")
    item = next(
        item
        for item in window.page_view.scene().items()
        if isinstance(item, TextObjectGraphicsItem) and item.key == run.key
    )
    item.setSelected(True)
    app.processEvents(QEventLoop.AllEvents, 50)

    assert window.page_view.selected_text_ref == ("source", run.key)
    assert window.text_bold_button.isChecked()

    # Simulate a focus change to the size control. Even if Qt clears the scene
    # selection while the combo has focus, formatting must retain its target.
    window.page_view.setFocus()
    window.page_view.scene().clearSelection()
    app.processEvents(QEventLoop.AllEvents, 50)
    assert window.page_view.selected_text_ref == ("source", run.key)
    assert window._text_toolbar_reference == ("source", run.key)
    window.text_size_box.setCurrentText("13.5 pt")
    window._font_size_changed()
    app.processEvents(QEventLoop.AllEvents, 50)

    edit = window.edits[run.key]
    assert edit.font_family == run.font_name
    assert edit.bold is True
    assert edit.font_size == 13.5
    assert edit.fit_to_width is False
    assert window.page_view.selected_text_ref == ("source", run.key)

    output = tmp_path / "toolbar_formatting.pdf"
    engine.save(output, window.edits.values())
    with fitz.open(output) as document:
        spans = [
            span
            for block in document[1].get_text("dict")["blocks"]
            if block.get("type") == 0
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if span.get("text") == run.text
        ]
    assert spans
    assert any(span["flags"] & 16 for span in spans)
    assert any(abs(span["size"] - 13.5) < 0.05 for span in spans)

    QTest.mouseClick(
        window.page_view.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        window.page_view.viewport().rect().bottomRight(),
    )
    app.processEvents(QEventLoop.AllEvents, 50)
    assert window.page_view.selected_text_ref is None
    assert window._text_toolbar_reference is None

    window.close()
    # A queued editingFinished signal after close must be harmless.
    window._font_size_changed()
    window.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 50)


def test_inline_editor_does_not_remove_itself_inside_focus_event() -> None:
    app = _application()
    editor = InlineTextEditor(
        "Changed text",
        "Arial",
        12,
        True,
        False,
        False,
        QColor("#000000"),
        False,
    )
    accepted: list[str] = []
    editor.accepted.connect(accepted.append)

    editor.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    assert accepted == []
    app.processEvents(QEventLoop.AllEvents, 50)
    assert accepted == ["Changed text"]

    editor.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 50)


def test_opening_text_without_a_change_keeps_original_page(tmp_path: Path) -> None:
    source = SAMPLES / "KS_Teil_2_2_01_KS26_ROB-KUKA_Projektspezifische_Vorgaben.pdf"
    if not source.exists():
        return
    app = _application()
    window = MainWindow()
    window._maybe_save_changes = lambda: True
    engine = PdfEngine()
    engine.open(source)
    window._activate_document(engine, source, already_saved=True)
    window._select_and_render_page(1)

    run = next(run for run in engine.text_runs(1) if run.text == "Inhaltsverzeichnis:")
    window._start_inline_text_edit("source", run.key)
    assert window.page_view.inline_editing
    window.page_view.finish_inline_editor(True)
    app.processEvents(QEventLoop.AllEvents, 50)

    assert run.key not in window.edits
    assert window.history_index == 0
    output = tmp_path / "opened_but_unchanged.pdf"
    engine.save(output, window.edits.values())
    with fitz.open(source) as original, fitz.open(output) as saved:
        original_pixels = original[1].get_pixmap(alpha=False).samples
        saved_pixels = saved[1].get_pixmap(alpha=False).samples
    assert saved_pixels == original_pixels

    window._start_inline_text_edit("source", run.key)
    assert window.page_view._inline_editor is not None
    window.page_view._inline_editor.setPlainText("Changed heading")
    arrow = QPoint(
        window.text_size_box.width() - 10,
        window.text_size_box.height() // 2,
    )
    QTest.mousePress(window.text_size_box, Qt.LeftButton, Qt.NoModifier, arrow)
    assert not window.page_view.inline_editing
    assert window.edits[run.key].new_text == "Changed heading"
    QTest.mouseRelease(window.text_size_box, Qt.LeftButton, Qt.NoModifier, arrow)
    window.text_size_box.hidePopup()
    app.processEvents(QEventLoop.AllEvents, 50)

    # A queued graphics-item event arriving after the document was closed must
    # be ignored instead of touching a destroyed page / scene.
    moved = (run.bbox[0] + 1, run.bbox[1], run.bbox[2] + 1, run.bbox[3])
    window.page_view.text_transform_requested.emit("source", run.key, moved)
    assert window.close_document()
    app.processEvents(QEventLoop.AllEvents, 50)
    assert not window.engine.is_open

    window.close()
    window.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 50)


def test_inline_edit_keeps_vertical_source_text_vertical() -> None:
    app = _application()
    source = fitz.open()
    page = source.new_page(width=420, height=420)
    page.insert_text((210, 300), "VERTICAL BEFORE", fontsize=16, rotate=90)
    payload = source.tobytes()
    source.close()

    window = MainWindow()
    window._maybe_save_changes = lambda: True
    engine = PdfEngine()
    engine.load_bytes(payload)
    window._activate_document(engine, None, already_saved=False)
    window.show()
    window._select_and_render_page(0)
    app.processEvents(QEventLoop.AllEvents, 50)

    run = next(item for item in engine.text_runs(0) if item.text == "VERTICAL BEFORE")
    assert run.direction == pytest.approx((0.0, -1.0), abs=1e-5)
    window._start_inline_text_edit("source", run.key)
    assert window.page_view._inline_editor is not None
    window.page_view._inline_editor.setPlainText("VERTICAL AFTER")
    window.page_view.finish_inline_editor(True)
    app.processEvents(QEventLoop.AllEvents, 100)

    assert window.edits[run.key].run.direction == pytest.approx((0.0, -1.0), abs=1e-5)
    edited_document = engine.build_document(window.edits.values())
    try:
        edited_line = next(
            line
            for block in edited_document[0].get_text("dict", sort=False)["blocks"]
            if block.get("type") == 0
            for line in block.get("lines", [])
            if any(
                span.get("text") == "VERTICAL AFTER"
                for span in line.get("spans", [])
            )
        )
        assert edited_line["dir"] == pytest.approx((0.0, -1.0), abs=1e-5)
    finally:
        edited_document.close()

    page_items = [
        item
        for item in window.page_view.scene().items()
        if isinstance(item, QGraphicsPixmapItem) and item.zValue() == 0
    ]
    assert len(page_items) == 1
    assert page_items[0].isVisible()
    assert not page_items[0].pixmap().isNull()

    window.close()
    window.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 50)


def test_page_render_is_deferred_while_inline_editor_is_alive() -> None:
    source = SAMPLES / "KS_Teil_2_2_01_KS26_ROB-KUKA_Projektspezifische_Vorgaben.pdf"
    if not source.exists():
        return
    app = _application()
    window = MainWindow()
    window._maybe_save_changes = lambda: True
    engine = PdfEngine()
    engine.open(source)
    window._activate_document(engine, source, already_saved=True)
    window.show()
    window._select_and_render_page(1)
    app.processEvents(QEventLoop.AllEvents, 50)

    run = next(run for run in engine.text_runs(1) if run.text == "Inhaltsverzeichnis:")
    window._start_inline_text_edit("source", run.key)
    editor_scene = window.page_view.scene()
    assert window.page_view.inline_editing

    # This is the former race: a queued frame mutation could request a render
    # between the two clicks of a double click. Clearing this scene while its
    # proxy widget owns focus can blank the view or crash Qt on Windows.
    moved = (run.bbox[0] + 4, run.bbox[1], run.bbox[2] + 4, run.bbox[3])
    window.page_view.text_transform_requested.emit("source", run.key, moved)
    app.processEvents(QEventLoop.AllEvents, 50)
    assert window._render_pending
    assert window.page_view.inline_editing
    assert window.page_view.scene() is editor_scene

    window.page_view.finish_inline_editor(True)
    app.processEvents(QEventLoop.AllEvents, 100)

    page_items = [
        item
        for item in window.page_view.scene().items()
        if isinstance(item, QGraphicsPixmapItem)
    ]
    assert not window._render_pending
    assert not window.page_view.inline_editing
    assert window.page_view.scene() is not editor_scene
    assert len(page_items) == 1
    assert not page_items[0].pixmap().isNull()
    visible = window.page_view.mapToScene(window.page_view.viewport().rect()).boundingRect()
    assert not visible.intersected(window.page_view.sceneRect()).isEmpty()

    window.close()
    window.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 50)


def test_failed_page_scene_build_keeps_last_valid_page(monkeypatch) -> None:
    app = _application()
    view = PageView()
    view.resize(520, 420)
    view.show()
    pixmap = QPixmap(360, 540)
    pixmap.fill(Qt.white)
    view.set_page(pixmap, [], [], [], 1.0)
    app.processEvents(QEventLoop.AllEvents, 50)
    valid_scene = view.scene()

    class BrokenTextItem:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("synthetic overlay failure")

    monkeypatch.setattr(main_window_module, "TextObjectGraphicsItem", BrokenTextItem)
    with pytest.raises(RuntimeError, match="synthetic overlay failure"):
        view.set_page(pixmap, [("source", "key", (10, 10, 80, 30))], [], [], 1.0)

    assert view.scene() is valid_scene
    page_items = [item for item in valid_scene.items() if isinstance(item, QGraphicsPixmapItem)]
    assert len(page_items) == 1
    assert not page_items[0].pixmap().isNull()

    view.close()
    view.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 50)


def test_double_click_pointer_jitter_does_not_move_text_frame() -> None:
    app = _application()
    view = PageView()
    pixmap = QPixmap(360, 540)
    pixmap.fill(Qt.white)
    view.set_page(pixmap, [("source", "key", (20, 30, 120, 50))], [], [], 1.0)
    item = next(
        candidate
        for candidate in view.scene().items()
        if isinstance(candidate, TextObjectGraphicsItem)
    )
    changes: list[tuple[str, str, object]] = []
    view.text_transform_requested.connect(
        lambda kind, key, bbox: changes.append((kind, key, bbox))
    )

    original = item._scene_rect()
    item._geometry_at_press = original
    item.moveBy(2.0, 1.0)
    item._commit_if_changed()

    restored = item._scene_rect()
    assert abs(restored.left() - original.left()) < 0.01
    assert abs(restored.top() - original.top()) < 0.01
    assert changes == []

    item._geometry_at_press = restored
    item.moveBy(4.0, 0.0)
    item._commit_if_changed()
    assert len(changes) == 1

    view.close()
    view.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 50)


def test_clicking_between_text_frames_finishes_gesture_before_page_swap() -> None:
    source = SAMPLES / "KS_Teil_2_2_01_KS26_ROB-KUKA_Projektspezifische_Vorgaben.pdf"
    if not source.exists():
        return
    app = _application()
    window = MainWindow()
    window._maybe_save_changes = lambda: True
    engine = PdfEngine()
    engine.open(source)
    window._activate_document(engine, source, already_saved=True)
    window.resize(1137, 849)
    window.show()
    window._select_and_render_page(1)
    app.processEvents(QEventLoop.AllEvents, 50)
    run = next(run for run in engine.text_runs(1) if run.text == "Inhaltsverzeichnis:")

    def blank_position() -> QPoint:
        scene = window.page_view.scene()
        bounds = scene.sceneRect().adjusted(10, 10, -10, -10)
        for y in range(round(bounds.top()), round(bounds.bottom()), 5):
            for x in range(round(bounds.left()), round(bounds.right()), 10):
                hits = scene.items(QPointF(x, y))
                if not any(isinstance(item, TextObjectGraphicsItem) for item in hits):
                    return window.page_view.mapFromScene(QPointF(x, y))
        raise AssertionError("No blank point found between text frames")

    for cycle in range(8):
        window._start_inline_text_edit("source", run.key)
        window.page_view._inline_editor.setPlainText(
            "Inhaltsverzeichnis:" + ("x" if cycle % 2 == 0 else "")
        )
        editor_scene = window.page_view.scene()
        position = blank_position()

        QTest.mousePress(
            window.page_view.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            position,
        )
        app.processEvents(QEventLoop.AllEvents, 50)

        assert window.page_view.pointer_interaction_active
        assert not window.page_view.inline_editing
        assert window._render_pending
        assert window.page_view.scene() is editor_scene
        pressed_page_items = [
            item
            for item in window.page_view.scene().items()
            if isinstance(item, QGraphicsPixmapItem) and item.zValue() == 0
        ]
        assert len(pressed_page_items) == 1
        assert pressed_page_items[0].isVisible()
        assert not pressed_page_items[0].pixmap().isNull()

        QTest.mouseRelease(
            window.page_view.viewport(),
            Qt.LeftButton,
            Qt.NoModifier,
            position,
        )
        app.processEvents(QEventLoop.AllEvents, 50)

        page_items = [
            item
            for item in window.page_view.scene().items()
            if isinstance(item, QGraphicsPixmapItem) and item.zValue() == 0
        ]
        visible = window.page_view.mapToScene(
            window.page_view.viewport().rect()
        ).boundingRect()
        assert not window.page_view.pointer_interaction_active
        assert not window._render_pending
        assert len(page_items) == 1
        assert page_items[0].isVisible()
        assert not page_items[0].pixmap().isNull()
        assert not visible.intersected(window.page_view.sceneRect()).isEmpty()

    # A plain deselection click must keep the same scene. If a platform paint
    # glitch ever hides the base pixmap, the post-gesture integrity check makes
    # it visible again without requiring a page change.
    current_scene = window.page_view.scene()
    page_item = next(
        item
        for item in current_scene.items()
        if isinstance(item, QGraphicsPixmapItem) and item.zValue() == 0
    )
    page_item.setVisible(False)
    QTest.mouseClick(
        window.page_view.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        blank_position(),
    )
    app.processEvents(QEventLoop.AllEvents, 50)
    assert window.page_view.scene() is current_scene
    assert page_item.isVisible()

    window.close()
    window.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 50)


def test_blank_page_click_repaints_only_when_base_layer_needs_repair(
    monkeypatch,
) -> None:
    app = _application()
    view = PageView()
    view.resize(500, 650)
    pixmap = QPixmap(360, 540)
    pixmap.fill(Qt.white)
    view.set_page(pixmap, [], [], [], 1.0)
    view.show()
    app.processEvents(QEventLoop.AllEvents, 50)

    page_item = next(
        item
        for item in view.scene().items()
        if isinstance(item, QGraphicsPixmapItem) and item.zValue() == 0
    )
    scene_updates = []
    viewport_updates = []
    monkeypatch.setattr(
        view.scene(),
        "update",
        lambda *args: scene_updates.append(args),
    )
    monkeypatch.setattr(
        view.viewport(),
        "update",
        lambda *args: viewport_updates.append(args),
    )

    click_position = view.mapFromScene(view.sceneRect().center())
    QTest.mouseClick(
        view.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        click_position,
    )
    app.processEvents(QEventLoop.AllEvents, 50)

    assert page_item.isVisible()
    assert scene_updates == []
    assert viewport_updates == []

    page_item.setVisible(False)
    QTest.mouseClick(
        view.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        click_position,
    )
    app.processEvents(QEventLoop.AllEvents, 50)

    assert page_item.isVisible()
    assert len(scene_updates) == 1
    assert len(viewport_updates) == 1

    view.close()
    view.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 50)


def test_page_background_remains_visible_while_blank_click_is_held() -> None:
    app = _application()
    view = PageView()
    view.resize(500, 650)
    pixmap = QPixmap(360, 540)
    pixmap.fill(Qt.white)
    view.set_page(pixmap, [], [], [], 1.0)
    view.show()
    app.processEvents(QEventLoop.AllEvents, 50)

    # Do not fetch the page item from scene().items() before the press.  Such a
    # local wrapper reference used to mask the PySide lifetime fault that made
    # the page disappear until mouse release.
    before_press = view.viewport().grab().toImage()
    click_position = view.mapFromScene(view.sceneRect().center())
    QTest.mousePress(
        view.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        click_position,
    )
    QTest.qWait(50)
    while_pressed = view.viewport().grab().toImage()

    assert view.pointer_interaction_active
    assert before_press == while_pressed
    assert view._page_item is not None
    assert view._page_item.scene() is view.scene()
    assert view._page_item.isVisible()
    assert not view._page_item.pixmap().isNull()

    QTest.mouseRelease(
        view.viewport(),
        Qt.LeftButton,
        Qt.NoModifier,
        click_position,
    )
    app.processEvents(QEventLoop.AllEvents, 50)
    assert not view.pointer_interaction_active

    view.close()
    view.deleteLater()
    app.processEvents(QEventLoop.AllEvents, 50)
