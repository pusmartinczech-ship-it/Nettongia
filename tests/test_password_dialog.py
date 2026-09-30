import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit, QMessageBox

from openpdf_editor.dialogs import PasswordProtectionDialog
from openpdf_editor.engine import PdfEngine, TextPlacement
from openpdf_editor.main_window import MainWindow


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_password_dialog_requires_length_and_matching_confirmation() -> None:
    _application()
    dialog = PasswordProtectionDialog()

    assert not dialog.save_button.isEnabled()
    dialog.password_edit.setText("long-enough")
    dialog.confirm_edit.setText("different")
    assert not dialog.save_button.isEnabled()
    assert dialog.validation_label.text()

    dialog.confirm_edit.setText("long-enough")
    assert dialog.save_button.isEnabled()
    assert dialog.password == "long-enough"
    assert not dialog.validation_label.text()

    dialog.show_password_box.setChecked(True)
    assert dialog.password_edit.echoMode() == QLineEdit.Normal
    assert dialog.confirm_edit.echoMode() == QLineEdit.Normal


def test_remove_password_protection_writes_unencrypted_copy(
    tmp_path,
    monkeypatch,
) -> None:
    app = _application()
    source = tmp_path / "protected-source.pdf"
    output = tmp_path / "unprotected-copy.pdf"
    creator = PdfEngine()
    creator.load_bytes(PdfEngine.blank_document_bytes(420, 300))
    creator.save(
        source,
        (),
        inserted_texts=(
            TextPlacement(
                key="secret",
                page_index=0,
                bbox=(40, 50, 350, 110),
                text="Password removed safely",
                font_size=18,
            ),
        ),
        encryption_password="source-password",
    )
    creator.close()

    engine = PdfEngine()
    engine.open(source, password="source-password")
    window = MainWindow()
    window._activate_document(engine, source, already_saved=True)
    window._cancel_document_inspection()
    assert window.remove_password_protection_action.isEnabled()
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(output), "PDF"),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(window, "_confirm_document_write_compatibility", lambda: True)

    assert window.save_unprotected_copy(background=False)
    with pymupdf.open(output) as unprotected:
        assert not unprotected.needs_pass
        assert "Password removed safely" in unprotected[0].get_text()
    assert window.document_path == source

    window._maybe_save_changes = lambda: True
    window.close()
    window.deleteLater()
    app.processEvents()
