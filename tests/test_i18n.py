from string import Formatter

from openpdf_editor.european_translations import EUROPEAN_LANGUAGE_CODES, EUROPEAN_ROWS
from openpdf_editor.i18n import BASE, LANGUAGES, language_from_locale, translate


def test_requested_language_set_is_complete() -> None:
    codes = {language.code for language in LANGUAGES}
    assert codes == {
        "en",
        "zh",
        "hi",
        "es",
        "fr",
        "ar",
        "bn",
        "pt",
        "id",
        "ur",
        "de",
        "ru",
        "tr",
        "it",
        "nl",
        "ro",
        "hu",
        "uk",
        "cs",
        "sk",
        "pl",
    }
    assert len(LANGUAGES) == 21


def test_core_controls_are_translated_for_every_language() -> None:
    for language in LANGUAGES:
        for key in (
            "menu_file",
            "menu_language",
            "new_pdf",
            "recent_files",
            "clear_recent_files",
            "close_document",
            "save_copy",
            "move_page_up",
            "move_page_down",
            "page_moved",
            "edit_original_image",
            "edit_original_image_hint",
            "original_image_ready",
            "print",
            "print_preview",
            "find",
            "find_next",
            "find_previous",
            "find_no_results",
            "add_text",
            "delete_text",
            "font_size",
            "signature_title",
            "compress_title",
            "sidebar_pages",
            "sidebar_tree",
            "no_document_tree",
            "document_compatibility",
            "compatibility_checking",
            "compatibility_signature_risk",
            "compatibility_level_safe",
            "compatibility_level_possible_changes",
            "compatibility_level_high_risk",
            "ocr_page",
            "ocr_document",
            "ocr_working",
            "ocr_complete",
            "image_updated",
            "recovery_title",
            "recovery_question",
            "restore",
        ):
            assert translate(language.code, key)

    assert translate("cs", "add_text") == "Přidat textové pole"
    assert translate("cs", "print") == "Tisk..."
    assert translate("cs", "print_preview") == "Náhled tisku"
    assert translate("cs", "recent_files") == "Nedávné soubory"
    assert translate("cs", "restore") == "Obnovit"
    assert translate("cs", "document_compatibility") == "Kompatibilita dokumentu..."
    assert translate("cs", "save_copy") == "Uložit kopii..."
    assert translate("cs", "ocr_page") == "OCR aktuální stránky..."
    assert translate("sk", "menu_file") == "Súbor"
    assert translate("pl", "save_as") == "Zapisz jako..."
    assert translate("id", "menu_file") == "Berkas"
    assert translate("de", "menu_file") == "Datei"
    assert translate("ru", "find") == "Найти..."
    assert translate("tr", "print") == "Yazdır..."
    assert translate("it", "sidebar_tree") == "Albero"
    assert translate("nl", "save") == "Opslaan"
    assert translate("ro", "menu_language") == "Limbă"
    assert translate("hu", "font_size") == "Betűméret"
    assert translate("uk", "close_document") == "Закрити документ"


def test_system_locale_mapping() -> None:
    assert language_from_locale("cs_CZ") == "cs"
    assert language_from_locale("pt-BR") == "pt"
    assert language_from_locale("id_ID") == "id"
    assert language_from_locale("de_DE") == "de"
    assert language_from_locale("ru_RU") == "ru"
    assert language_from_locale("tr-TR") == "tr"
    assert language_from_locale("uk_UA") == "uk"


def test_new_european_languages_cover_every_message_and_keep_placeholders() -> None:
    assert set(EUROPEAN_ROWS) == set(BASE)
    formatter = Formatter()
    for key, base_text in BASE.items():
        expected_fields = {
            field_name
            for _, field_name, _, _ in formatter.parse(base_text)
            if field_name is not None
        }
        for language_index, code in enumerate(EUROPEAN_LANGUAGE_CODES):
            translated = EUROPEAN_ROWS[key][language_index]
            actual_fields = {
                field_name
                for _, field_name, _, _ in formatter.parse(translated)
                if field_name is not None
            }
            assert translated
            assert actual_fields == expected_fields, (code, key)
