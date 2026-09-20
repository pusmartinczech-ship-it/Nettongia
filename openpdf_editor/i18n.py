from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

from .european_translations import EUROPEAN_LANGUAGE_CODES, EUROPEAN_ROWS


@dataclass(frozen=True)
class Language:
    code: str
    native_name: str
    english_name: str


LANGUAGES = (
    Language("en", "English", "English"),
    Language("zh", "中文", "Chinese"),
    Language("hi", "हिन्दी", "Hindi"),
    Language("es", "Español", "Spanish"),
    Language("ar", "العربية", "Arabic"),
    Language("fr", "Français", "French"),
    Language("bn", "বাংলা", "Bengali"),
    Language("pt", "Português", "Portuguese"),
    Language("id", "Bahasa Indonesia", "Indonesian"),
    Language("ur", "اردو", "Urdu"),
    Language("de", "Deutsch", "German"),
    Language("ru", "Русский", "Russian"),
    Language("tr", "Türkçe", "Turkish"),
    Language("it", "Italiano", "Italian"),
    Language("nl", "Nederlands", "Dutch"),
    Language("ro", "Română", "Romanian"),
    Language("hu", "Magyar", "Hungarian"),
    Language("uk", "Українська", "Ukrainian"),
    Language("cs", "Čeština", "Czech"),
    Language("sk", "Slovenčina", "Slovak"),
    Language("pl", "Polski", "Polish"),
)
LANGUAGE_CODES = {language.code for language in LANGUAGES}
RIGHT_TO_LEFT = {"ar", "ur"}
_ROW_LANGUAGE_CODES = ("en", "zh", "hi", "es", "fr", "ar", "bn", "pt", "id", "ur", "cs", "sk", "pl")


BASE = {
    "menu_file": "File",
    "menu_edit": "Edit",
    "menu_insert": "Insert",
    "menu_page": "Page",
    "menu_image": "Image",
    "menu_view": "View",
    "menu_appearance": "Appearance",
    "menu_language": "Language",
    "menu_help": "Help",
    "new_pdf": "New PDF...",
    "open": "Open...",
    "recent_files": "Recent files",
    "no_recent_files": "No recent files",
    "clear_recent_files": "Clear recent files",
    "recent_file_missing": "The file is no longer available:\n{path}",
    "close_document": "Close document",
    "save_as": "Save As...",
    "save_copy": "Save a Copy...",
    "print": "Print...",
    "print_preview": "Print preview",
    "compress": "Compress PDF...",
    "exit": "Exit",
    "undo": "Undo",
    "redo": "Redo",
    "find": "Find...",
    "find_label": "Find:",
    "find_placeholder": "Find in document...",
    "find_previous": "Previous match",
    "find_next": "Next match",
    "close_search": "Close search",
    "find_no_results": "No matches found",
    "document_closed": "Document closed",
    "add_text": "Add text box",
    "delete_text": "Delete selected text",
    "edit_text": "Edit text",
    "zoom_in": "Zoom in",
    "zoom_out": "Zoom out",
    "fit_width": "Fit width",
    "theme_auto": "Automatic (system)",
    "theme_dark": "Dark",
    "theme_light": "Light",
    "add_blank_page": "Add blank page",
    "insert_pages": "Insert pages from PDF...",
    "delete_page": "Delete current page",
    "move_page_up": "Move page earlier",
    "move_page_down": "Move page later",
    "page_moved": "Page moved to position {page}.",
    "rotate_page_left": "Rotate page left",
    "rotate_page_right": "Rotate page right",
    "page_rotated": "Page {page} rotated.",
    "insert_image": "Insert image...",
    "edit_original_image": "Edit original image...",
    "edit_original_image_hint": "Click an original image to make it movable, resizable, and rotatable. Press Esc to cancel.",
    "original_image": "Original image",
    "original_image_ready": "The original image is now editable. Drag it or use the resize and rotation handles.",
    "delete_image": "Delete image",
    "add_signature": "Add visual signature...",
    "export_diagnostics": "Export anonymized diagnostics...",
    "diagnostics_title": "Anonymized diagnostics",
    "diagnostics_review": "Before export, review the complete contents.\n\nIncluded:\n• bundle generation time and application/diagnostics versions\n• frozen-build flag, operating-system family, release and architecture\n• Python, Qt, PySide6 and PyMuPDF versions\n• interface language and appearance mode\n• page count, current page and coarse PDF size bucket\n• unsaved-state flag and counts of pending objects\n• tile-cache counters\n• bounded operation timestamps, random per-start session IDs, names and outcomes\n• presence of current/previous crash logs and their coarse size\n\nExcluded:\n• PDF files and rendered pages\n• document text, images, annotations and metadata\n• file names, folder paths and recent-file history\n• user name, computer name, IP and hardware identifiers\n• raw exception messages and raw crash-log contents\n\nCreate the ZIP?",
    "diagnostics_filter": "ZIP archives (*.zip)",
    "diagnostics_saved": "Anonymized diagnostics saved ({records} operation records):\n{path}",
    "diagnostics_failed": "Unable to create diagnostics: {error}",
    "about": "About",
    "check_for_updates": "Check for updates...",
    "automatic_updates": "Automatically check for updates (GitHub)",
    "update_check_title": "Nettongia PDF Editor updates",
    "update_available": "A newer version is available: {version}\n\nCurrent version: {current}\n\nOpen the release page to download it?",
    "no_update_available": "You are using the latest available version ({version}).",
    "update_check_failed": "The update check is currently unavailable. Nettongia can continue working offline.",
    "open_release_page": "Open release page",
    "document_compatibility": "Document compatibility...",
    "ocr_page": "OCR current page...",
    "ocr_document": "OCR document...",
    "ocr_title": "Text recognition (OCR)",
    "ocr_language_prompt": "Recognition language:",
    "ocr_unavailable": "The bundled offline OCR language data is unavailable. Reinstall the complete Nettongia PDF Editor package.",
    "ocr_working": "Recognizing text in a separate process...",
    "ocr_complete": "OCR completed: {pages} page(s), {words} recognized word(s).",
    "ocr_nothing": "OCR found no image-only page with recognizable text. Pages that already contain text were left unchanged.",
    "ocr_discarded": "The OCR result was discarded because the document changed.",
    "compatibility_checking": "Checking document compatibility in an isolated process...",
    "compatibility_ok": "No risky PDF features were detected.",
    "compatibility_warnings": "Compatibility check found {count} item(s) to review.",
    "compatibility_failed": "The isolated compatibility check failed: {error}",
    "compatibility_signature_risk": "Editing and saving will invalidate existing digital signatures.",
    "compatibility_features": "Features to review: {features}",
    "compatibility_level_safe": "Safe",
    "compatibility_level_possible_changes": "Possible changes",
    "compatibility_level_high_risk": "High risk",
    "representative_render_ok": "Representative pages rendered safely: {count}",
    "font": "Font",
    "font_size": "Font size",
    "bold": "Bold",
    "italic": "Italic",
    "underline": "Underline",
    "text_color": "Text color",
    "current_zoom": "Current zoom",
    "create": "Create",
    "cancel": "Cancel",
    "save": "Save",
    "discard": "Discard",
    "yes": "Yes",
    "no": "No",
    "new_title": "Create new PDF",
    "custom_size": "Custom size",
    "portrait": "Portrait",
    "landscape": "Landscape",
    "page_size": "Page size",
    "orientation": "Orientation",
    "width": "Width",
    "height": "Height",
    "page_count": "Number of pages",
    "result": "Result",
    "blank_pdf_intro": "Create a blank PDF document:",
    "pages_count": "{count} page(s)",
    "signature_title": "Insert visual signature",
    "signature_warning": "This inserts a visible signature into the page. It is not a certificate-based digital signature.",
    "draw_signature": "Draw signature",
    "type_signature": "Type signature",
    "clear_drawing": "Clear drawing",
    "draw_hint": "Draw inside the box using the mouse or a pen:",
    "your_name": "Your name",
    "signature_text": "Signature text",
    "size": "Size",
    "style": "Style",
    "width_on_page": "Width on page",
    "rotation": "Rotation",
    "empty_signature": "Empty signature",
    "empty_draw": "Draw a signature or switch to Type signature.",
    "empty_type": "Enter the signature text.",
    "drawn_signature_desc": "Drawn visual signature",
    "typed_signature_desc": "Typed visual signature: {text}",
    "compress_title": "Compress PDF",
    "lossless": "Lossless optimization",
    "balanced": "Balanced - recommended",
    "strong": "Strong - smallest file",
    "compression_profile": "Compression profile",
    "lossless_desc": "Optimizes PDF objects and streams without lowering image quality.",
    "balanced_desc": "Downsamples oversized images to about 150 dpi and uses medium JPEG compression.",
    "strong_desc": "Downsamples oversized images to about 105 dpi and uses stronger JPEG compression.",
    "compression_note": "Lossy profiles are most effective for scans and photographs. Vector text and graphics remain sharp.",
    "open_to_begin": "Open a PDF or create a new one to begin",
    "sidebar_pages": "Pages",
    "sidebar_tree": "Tree",
    "comments": "Comments",
    "add_comment": "Add comment...",
    "edit_comment": "Edit selected comment...",
    "delete_annotation": "Delete selected annotation",
    "highlight_text": "Highlight text",
    "comment_place_hint": "Click the page where the comment icon should be placed. Press Esc to cancel.",
    "comment_text_prompt": "Comment text:",
    "comment_empty": "Enter comment text before placing the annotation.",
    "comment_added": "Comment added. Use Undo to remove it.",
    "highlight_added": "Text highlighted. Use Undo to remove the highlight.",
    "comment_updated": "Comment updated. Use Undo to restore the previous text.",
    "delete_annotation_question": "Delete the selected annotation?",
    "annotation_deleted": "Annotation deleted. Use Undo to restore it.",
    "annotation_without_comment": "No comment text",
    "forms": "Forms",
    "edit_form_field": "Edit selected form field...",
    "no_form_fields": "This PDF has no supported AcroForm fields.",
    "unnamed_form_field": "Unnamed field",
    "form_checked": "Checked",
    "form_unchecked": "Unchecked",
    "form_empty": "Empty",
    "form_read_only": "Read-only",
    "form_read_only_message": "This form field is read-only and cannot be changed.",
    "form_value": "Value:",
    "form_no_choices": "This choice field has no available values.",
    "form_unsupported": "This form field type is not supported for editing.",
    "form_updated": "Form field updated. Use Undo to restore the previous value.",
    "no_document_tree": "This PDF has no document tree.",
    "untitled": "Untitled.pdf",
    "page_word": "Page",
    "editable_text": "editable text",
    "ocr_required": "image-only page - OCR required",
    "images": "images",
    "signatures": "signatures",
    "text_boxes": "text objects",
    "unsaved_title": "Unsaved changes",
    "unsaved_question": "Save changes to {name} before continuing?",
    "recovery_title": "Recover unsaved work",
    "recovery_question": "Nettongia PDF Editor found automatically saved unsaved work for {name}. Restore it?",
    "restore": "Restore",
    "recovery_unavailable": "Automatic recovery is currently unavailable: {error}",
    "recovery_failed_title": "Recovery failed",
    "recovery_failed_message": "The recovery data could not be opened. It was preserved for diagnostics at:\n{path}\n\n{error}",
    "recovery_restored": "Unsaved work was restored. Save the document to keep it.",
    "choose_text_color": "Choose text color",
    "add_text_hint": "Drag a text box on the page, or click once for a standard box. Press Esc to cancel.",
    "type_text_hint": "Type the new text. Press Ctrl+Enter to finish or Esc to cancel.",
    "direct_edit_hint": "Edit directly on the page. Ctrl+Enter confirms; Esc cancels.",
    "text_inserted": "Text inserted. It remains selectable, movable, and editable.",
    "text_updated": "Text updated. Use Undo to restore the previous version.",
    "text_cancelled": "Text editing cancelled.",
    "text_removed": "Text removed. Use Undo to restore it.",
    "text_frame_updated": "Text frame updated. Use Undo to restore its previous geometry.",
    "select_text_hint": "Double-click to type directly. Drag the frame to move it or its lower-right handle to resize it.",
    "about_title": "About Nettongia PDF Editor",
    "pdf_filter": "PDF documents (*.pdf)",
    "image_filter": "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)",
    "new_created": "New PDF created: {count} page(s), {width:.0f} x {height:.0f} pt. Save it to choose a filename.",
    "unable_create_title": "Unable to create PDF",
    "open_pdf_title": "Open PDF",
    "unable_open_title": "Unable to open PDF",
    "pdf_password_title": "Protected PDF",
    "pdf_password_prompt": "Enter the password to open this PDF:",
    "pdf_password_incorrect": "Incorrect password. Try again:",
    "pdf_password_removed_notice": "The PDF was unlocked. Edited copies will be saved without password protection.",
    "render_error_title": "Rendering error",
    "cannot_delete_page": "A PDF must contain at least one page.",
    "delete_page_question": "Delete page {page}?",
    "invalid_image_format": "The selected image format could not be read.",
    "image_width_prompt": "Width on page (points):",
    "unable_open_image": "Unable to open image",
    "unable_create_signature": "Unable to create signature",
    "visual_place_hint": "Click on the page where the {kind} should be placed. Press Esc to cancel.",
    "unable_place_image": "Unable to place image",
    "invalid_image_data": "The image data is invalid.",
    "signature_inserted": "Signature inserted. Click it to move, resize, or rotate it.",
    "image_inserted": "Image inserted. Use Undo to remove it.",
    "image_updated": "Image updated. Use Undo to restore its previous position.",
    "signature_updated": "Signature updated. Use Undo to restore its previous position.",
    "signature_select_hint": "Drag the signature to move it; use the lower handle to resize and the upper handle to rotate.",
    "no_image": "No image",
    "no_image_message": "There is no image or visual signature on this page.",
    "delete_visual_hint": "Click the image or visual signature to remove. Press Esc to cancel.",
    "image_removed": "Image removed. Use Undo to restore it.",
    "save_pdf_title": "Save edited PDF",
    "pdf_saved": "PDF saved",
    "pdf_saved_message": "The edited document was saved to:\n{path}",
    "saved_status": "Saved: {path}",
    "unable_save": "Unable to save PDF",
    "print_failed": "Printing failed",
    "print_complete": "Print job sent: {count} page(s).",
    "save_compressed_title": "Save compressed PDF",
    "compression_failed": "Compression failed",
    "compression_complete": "Compression complete",
    "reduction": "Reduction: {value:.1f}%",
    "increase": "Increase: {value:.1f}% (the source was already efficiently compressed)",
    "original_working": "Original working document",
    "compressed_copy": "Compressed copy",
    "recompressed_images": "Recompressed images",
    "about_body": "Nettongia PDF Editor 0.17.0\n\nEdit existing text directly on the page and add movable, resizable text boxes. Create blank PDFs; insert or remove images; manage pages; add rotatable visual signatures; switch appearance and interface language; preview and print documents; and save compressed copies.\n\nOriginal selected text and deleted images are removed from page content before saving.\n\nUnsaved work is marked with an asterisk, protected by a Save / Discard / Cancel prompt, and captured by automatic crash recovery. Recently opened PDFs are available from the File menu.\n\nVisual signatures are not certificate-based digital signatures. Image-only text still requires OCR.",
}


# Each row follows _ROW_LANGUAGE_CODES. The first value is English and is
# intentionally repeated so the table can be validated and inspected easily.
_ROWS = {
    "automatic_updates": ("Automatically check for updates (GitHub)", "自动检查更新 (GitHub)", "स्वचालित अपडेट जाँच (GitHub)", "Buscar actualizaciones automáticamente (GitHub)", "Vérifier automatiquement les mises à jour (GitHub)", "التحقق تلقائيًا من التحديثات (GitHub)", "স্বয়ংক্রিয়ভাবে আপডেট পরীক্ষা করুন (GitHub)", "Verificar atualizações automaticamente (GitHub)", "Periksa pembaruan otomatis (GitHub)", "اپ ڈیٹس خودکار طور پر چیک کریں (GitHub)", "Automaticky kontrolovat aktualizace (GitHub)", "Automaticky kontrolovať aktualizácie (GitHub)", "Automatycznie sprawdzaj aktualizacje (GitHub)"),
    "menu_file": ("File", "文件", "फ़ाइल", "Archivo", "Fichier", "ملف", "ফাইল", "Ficheiro", "Файл", "فائل", "Soubor", "Súbor", "Plik"),
    "menu_edit": ("Edit", "编辑", "संपादन", "Editar", "Édition", "تحرير", "সম্পাদনা", "Editar", "Правка", "ترمیم", "Úpravy", "Upraviť", "Edycja"),
    "menu_insert": ("Insert", "插入", "सम्मिलित करें", "Insertar", "Insertion", "إدراج", "সন্নিবেশ", "Inserir", "Вставка", "داخل کریں", "Vložit", "Vložiť", "Wstaw"),
    "menu_page": ("Page", "页面", "पृष्ठ", "Página", "Page", "صفحة", "পৃষ্ঠা", "Página", "Страница", "صفحہ", "Stránka", "Strana", "Strona"),
    "menu_image": ("Image", "图像", "छवि", "Imagen", "Image", "صورة", "ছবি", "Imagem", "Изображение", "تصویر", "Obrázek", "Obrázok", "Obraz"),
    "menu_view": ("View", "视图", "दृश्य", "Ver", "Affichage", "عرض", "দৃশ্য", "Ver", "Вид", "منظر", "Zobrazení", "Zobrazenie", "Widok"),
    "menu_appearance": ("Appearance", "外观", "रूप", "Apariencia", "Apparence", "المظهر", "চেহারা", "Aspeto", "Оформление", "ظاہری شکل", "Vzhled", "Vzhľad", "Wygląd"),
    "menu_language": ("Language", "语言", "भाषा", "Idioma", "Langue", "اللغة", "ভাষা", "Idioma", "Язык", "زبان", "Jazyk", "Jazyk", "Język"),
    "menu_help": ("Help", "帮助", "सहायता", "Ayuda", "Aide", "مساعدة", "সহায়তা", "Ajuda", "Справка", "مدد", "Nápověda", "Pomocník", "Pomoc"),
    "new_pdf": ("New PDF...", "新建 PDF...", "नया PDF...", "Nuevo PDF...", "Nouveau PDF...", "PDF جديد...", "নতুন PDF...", "Novo PDF...", "Новый PDF...", "نئی PDF...", "Nové PDF...", "Nové PDF...", "Nowy PDF..."),
    "open": ("Open...", "打开...", "खोलें...", "Abrir...", "Ouvrir...", "فتح...", "খুলুন...", "Abrir...", "Открыть...", "کھولیں...", "Otevřít...", "Otvoriť...", "Otwórz..."),
    "close_document": ("Close document", "关闭文档", "दस्तावेज़ बंद करें", "Cerrar documento", "Fermer le document", "إغلاق المستند", "নথি বন্ধ করুন", "Fechar documento", "Tutup dokumen", "دستاویز بند کریں", "Zavřít dokument", "Zavrieť dokument", "Zamknij dokument"),
    "save_as": ("Save As...", "另存为...", "इस रूप में सहेजें...", "Guardar como...", "Enregistrer sous...", "حفظ باسم...", "নামে সংরক্ষণ...", "Guardar como...", "Сохранить как...", "محفوظ کریں بطور...", "Uložit jako...", "Uložiť ako...", "Zapisz jako..."),
    "print": ("Print...", "打印...", "प्रिंट करें...", "Imprimir...", "Imprimer...", "طباعة...", "প্রিন্ট...", "Imprimir...", "Cetak...", "پرنٹ...", "Tisk...", "Tlačiť...", "Drukuj..."),
    "print_preview": ("Print preview", "打印预览", "प्रिंट पूर्वावलोकन", "Vista previa de impresión", "Aperçu avant impression", "معاينة الطباعة", "প্রিন্ট প্রিভিউ", "Pré-visualização da impressão", "Pratinjau cetak", "پرنٹ پیش منظر", "Náhled tisku", "Ukážka pred tlačou", "Podgląd wydruku"),
    "compress": ("Compress PDF...", "压缩 PDF...", "PDF संपीड़ित करें...", "Comprimir PDF...", "Compresser le PDF...", "ضغط PDF...", "PDF সংকুচিত করুন...", "Comprimir PDF...", "Сжать PDF...", "PDF سکیڑیں...", "Komprimovat PDF...", "Komprimovať PDF...", "Kompresuj PDF..."),
    "exit": ("Exit", "退出", "बाहर निकलें", "Salir", "Quitter", "خروج", "প্রস্থান", "Sair", "Выход", "باہر نکلیں", "Ukončit", "Ukončiť", "Zakończ"),
    "undo": ("Undo", "撤销", "पूर्ववत करें", "Deshacer", "Annuler", "تراجع", "পূর্বাবস্থায়", "Desfazer", "Отменить", "واپس", "Zpět", "Späť", "Cofnij"),
    "redo": ("Redo", "重做", "फिर से करें", "Rehacer", "Rétablir", "إعادة", "পুনরায়", "Refazer", "Повторить", "دوبارہ", "Znovu", "Znova", "Ponów"),
    "find": ("Find...", "查找...", "खोजें...", "Buscar...", "Rechercher...", "بحث...", "খুঁজুন...", "Localizar...", "Cari...", "تلاش کریں...", "Najít...", "Nájsť...", "Znajdź..."),
    "find_label": ("Find:", "查找：", "खोजें:", "Buscar:", "Rechercher :", "بحث:", "খুঁজুন:", "Localizar:", "Cari:", "تلاش:", "Najít:", "Nájsť:", "Znajdź:"),
    "find_placeholder": ("Find in document...", "在文档中查找...", "दस्तावेज़ में खोजें...", "Buscar en el documento...", "Rechercher dans le document...", "البحث في المستند...", "নথিতে খুঁজুন...", "Localizar no documento...", "Cari dalam dokumen...", "دستاویز میں تلاش کریں...", "Hledat v dokumentu...", "Hľadať v dokumente...", "Szukaj w dokumencie..."),
    "find_previous": ("Previous match", "上一个匹配项", "पिछला मिलान", "Coincidencia anterior", "Résultat précédent", "النتيجة السابقة", "আগের মিল", "Correspondência anterior", "Hasil sebelumnya", "پچھلا نتیجہ", "Předchozí výsledek", "Predchádzajúci výsledok", "Poprzedni wynik"),
    "find_next": ("Next match", "下一个匹配项", "अगला मिलान", "Coincidencia siguiente", "Résultat suivant", "النتيجة التالية", "পরের মিল", "Correspondência seguinte", "Hasil berikutnya", "اگلا نتیجہ", "Další výsledek", "Nasledujúci výsledok", "Następny wynik"),
    "close_search": ("Close search", "关闭查找", "खोज बंद करें", "Cerrar búsqueda", "Fermer la recherche", "إغلاق البحث", "খোঁজ বন্ধ করুন", "Fechar pesquisa", "Tutup pencarian", "تلاش بند کریں", "Zavřít vyhledávání", "Zavrieť vyhľadávanie", "Zamknij wyszukiwanie"),
    "find_no_results": ("No matches found", "未找到匹配项", "कोई मिलान नहीं मिला", "No se encontraron coincidencias", "Aucun résultat trouvé", "لم يتم العثور على نتائج", "কোনো মিল পাওয়া যায়নি", "Nenhuma correspondência encontrada", "Tidak ada hasil", "کوئی نتیجہ نہیں ملا", "Nenalezen žádný výsledek", "Nenašiel sa žiadny výsledok", "Nie znaleziono wyników"),
    "document_closed": ("Document closed", "文档已关闭", "दस्तावेज़ बंद किया गया", "Documento cerrado", "Document fermé", "تم إغلاق المستند", "নথি বন্ধ হয়েছে", "Documento fechado", "Dokumen ditutup", "دستاویز بند ہو گئی", "Dokument byl zavřen", "Dokument bol zatvorený", "Dokument został zamknięty"),
    "add_text": ("Add text box", "添加文本框", "टेक्स्ट बॉक्स जोड़ें", "Añadir cuadro de texto", "Ajouter une zone de texte", "إضافة مربع نص", "টেক্সট বক্স যোগ করুন", "Adicionar caixa de texto", "Добавить текстовое поле", "متن خانہ شامل کریں", "Přidat textové pole", "Pridať textové pole", "Dodaj pole tekstowe"),
    "delete_text": ("Delete selected text", "删除所选文本", "चयनित पाठ हटाएँ", "Eliminar texto seleccionado", "Supprimer le texte sélectionné", "حذف النص المحدد", "নির্বাচিত লেখা মুছুন", "Eliminar texto selecionado", "Удалить выбранный текст", "منتخب متن حذف کریں", "Odstranit vybraný text", "Odstrániť vybraný text", "Usuń zaznaczony tekst"),
    "edit_text": ("Edit text", "编辑文本", "पाठ संपादित करें", "Editar texto", "Modifier le texte", "تحرير النص", "পাঠ সম্পাদনা করুন", "Editar texto", "Редактировать текст", "متن میں ترمیم کریں", "Upravit text", "Upraviť text", "Edytuj tekst"),
    "zoom_in": ("Zoom in", "放大", "ज़ूम इन", "Acercar", "Zoom avant", "تكبير", "বড় করুন", "Ampliar", "Увеличить", "بڑا کریں", "Přiblížit", "Priblížiť", "Powiększ"),
    "zoom_out": ("Zoom out", "缩小", "ज़ूम आउट", "Alejar", "Zoom arrière", "تصغير", "ছোট করুন", "Reduzir", "Уменьшить", "چھوٹا کریں", "Oddálit", "Oddialiť", "Pomniejsz"),
    "fit_width": ("Fit width", "适合宽度", "चौड़ाई में फिट", "Ajustar al ancho", "Ajuster à la largeur", "ملاءمة العرض", "প্রস্থে মানান", "Ajustar à largura", "По ширине", "چوڑائی کے مطابق", "Přizpůsobit šířce", "Prispôsobiť šírke", "Dopasuj do szerokości"),
    "theme_auto": ("Automatic (system)", "自动（系统）", "स्वचालित (सिस्टम)", "Automático (sistema)", "Automatique (système)", "تلقائي (النظام)", "স্বয়ংক্রিয় (সিস্টেম)", "Automático (sistema)", "Автоматически (система)", "خودکار (نظام)", "Automaticky (systém)", "Automaticky (systém)", "Automatyczny (system)"),
    "theme_dark": ("Dark", "深色", "गहरा", "Oscuro", "Sombre", "داكن", "গাঢ়", "Escuro", "Тёмная", "گہرا", "Tmavý", "Tmavý", "Ciemny"),
    "theme_light": ("Light", "浅色", "हल्का", "Claro", "Clair", "فاتح", "হালকা", "Claro", "Светлая", "ہلکا", "Světlý", "Svetlý", "Jasny"),
    "add_blank_page": ("Add blank page", "添加空白页", "खाली पृष्ठ जोड़ें", "Añadir página en blanco", "Ajouter une page vierge", "إضافة صفحة فارغة", "ফাঁকা পৃষ্ঠা যোগ করুন", "Adicionar página em branco", "Добавить пустую страницу", "خالی صفحہ شامل کریں", "Přidat prázdnou stránku", "Pridať prázdnu stranu", "Dodaj pustą stronę"),
    "insert_pages": ("Insert pages from PDF...", "从 PDF 插入页面...", "PDF से पृष्ठ डालें...", "Insertar páginas desde PDF...", "Insérer des pages depuis un PDF...", "إدراج صفحات من PDF...", "PDF থেকে পৃষ্ঠা যোগ করুন...", "Inserir páginas de PDF...", "Вставить страницы из PDF...", "PDF سے صفحات شامل کریں...", "Vložit stránky z PDF...", "Vložiť strany z PDF...", "Wstaw strony z PDF..."),
    "delete_page": ("Delete current page", "删除当前页", "वर्तमान पृष्ठ हटाएँ", "Eliminar página actual", "Supprimer la page actuelle", "حذف الصفحة الحالية", "বর্তমান পৃষ্ঠা মুছুন", "Eliminar página atual", "Удалить текущую страницу", "موجودہ صفحہ حذف کریں", "Odstranit aktuální stránku", "Odstrániť aktuálnu stranu", "Usuń bieżącą stronę"),
    "insert_image": ("Insert image...", "插入图像...", "छवि डालें...", "Insertar imagen...", "Insérer une image...", "إدراج صورة...", "ছবি যোগ করুন...", "Inserir imagem...", "Вставить изображение...", "تصویر شامل کریں...", "Vložit obrázek...", "Vložiť obrázok...", "Wstaw obraz..."),
    "delete_image": ("Delete image", "删除图像", "छवि हटाएँ", "Eliminar imagen", "Supprimer l’image", "حذف الصورة", "ছবি মুছুন", "Eliminar imagem", "Удалить изображение", "تصویر حذف کریں", "Odstranit obrázek", "Odstrániť obrázok", "Usuń obraz"),
    "add_signature": ("Add visual signature...", "添加可视签名...", "दृश्य हस्ताक्षर जोड़ें...", "Añadir firma visual...", "Ajouter une signature visuelle...", "إضافة توقيع مرئي...", "দৃশ্যমান স্বাক্ষর যোগ করুন...", "Adicionar assinatura visual...", "Добавить визуальную подпись...", "ظاہری دستخط شامل کریں...", "Přidat vizuální podpis...", "Pridať vizuálny podpis...", "Dodaj podpis wizualny..."),
    "about": ("About", "关于", "परिचय", "Acerca de", "À propos", "حول", "সম্পর্কে", "Acerca de", "О программе", "متعلق", "O programu", "O programe", "O programie"),
    "check_for_updates": ("Check for updates...", "检查更新...", "अपडेट की जाँच करें...", "Buscar actualizaciones...", "Rechercher des mises à jour...", "التحقق من وجود تحديثات...", "আপডেটের জন্য পরীক্ষা করুন...", "Verificar atualizações...", "Periksa pembaruan...", "اپ ڈیٹس کی جانچ کریں...", "Kontrola aktualizací...", "Skontrolovať aktualizácie...", "Sprawdź aktualizacje..."),
    "update_check_title": ("Nettongia PDF Editor updates", "Nettongia PDF Editor 更新", "Nettongia PDF Editor अपडेट", "Actualizaciones de Nettongia PDF Editor", "Mises à jour de Nettongia PDF Editor", "تحديثات Nettongia PDF Editor", "Nettongia PDF Editor আপডেট", "Atualizações do Nettongia PDF Editor", "Pembaruan Nettongia PDF Editor", "تازہ کاری‌های Nettongia PDF Editor", "Aktualizace Nettongia PDF Editor", "Aktualizácie Nettongia PDF Editor", "Aktualizacje Nettongia PDF Editor"),
    "update_available": ("A newer version is available: {version}\n\nCurrent version: {current}\n\nOpen the release page to download it?", "有可用的新版本：{version}\n\n当前版本：{current}\n\n打开发布页面下载吗？", "एक नया संस्करण उपलब्ध है: {version}\n\nवर्तमान संस्करण: {current}\n\nडाउनलोड करने के लिए रिलीज़ पृष्ठ खोलें?", "Hay una versión más reciente disponible: {version}\n\nVersión actual: {current}\n\n¿Abrir la página de publicación para descargarla?", "Une nouvelle version est disponible : {version}\n\nVersion actuelle : {current}\n\nOuvrir la page de publication pour la télécharger ?", "يتوفر إصدار أحدث: {version}\n\nالإصدار الحالي: {current}\n\nهل تريد فتح صفحة الإصدار لتنزيله؟", "একটি নতুন সংস্করণ উপলব্ধ: {version}\n\nবর্তমান সংস্করণ: {current}\n\nডাউনলোড করতে রিলিজ পৃষ্ঠা খুলবেন?", "Está disponível uma versão mais recente: {version}\n\nVersão atual: {current}\n\nAbrir a página da versão para descarregar?", "Versi terbaru tersedia: {version}\n\nVersi saat ini: {current}\n\nBuka halaman rilis untuk mengunduhnya?", "ایک نیا ورژن دستیاب ہے: {version}\n\nموجودہ ورژن: {current}\n\nڈاؤن لوڈ کرنے کے لیے ریلیز صفحہ کھولیں؟", "Je k dispozici novější verze: {version}\n\nAktuální verze: {current}\n\nOtevřít stránku vydání a stáhnout ji?", "Je k dispozícii novšia verzia: {version}\n\nAktuálna verzia: {current}\n\nOtvoriť stránku vydania a stiahnuť ju?", "Dostępna jest nowsza wersja: {version}\n\nBieżąca wersja: {current}\n\nOtworzyć stronę wydania, aby ją pobrać?"),
    "no_update_available": ("You are using the latest available version ({version}).", "您使用的是最新可用版本（{version}）。", "आप नवीनतम उपलब्ध संस्करण ({version}) का उपयोग कर रहे हैं।", "Está utilizando la versión disponible más reciente ({version}).", "Vous utilisez la dernière version disponible ({version}).", "أنت تستخدم أحدث إصدار متاح ({version}).", "আপনি সর্বশেষ উপলব্ধ সংস্করণ ({version}) ব্যবহার করছেন।", "Está a utilizar a versão mais recente disponível ({version}).", "Anda menggunakan versi terbaru yang tersedia ({version}).", "آپ دستیاب تازہ ترین ورژن ({version}) استعمال کر رہے ہیں۔", "Používáte nejnovější dostupnou verzi ({version}).", "Používate najnovšiu dostupnú verziu ({version}).", "Używasz najnowszej dostępnej wersji ({version})."),
    "update_check_failed": ("The update check is currently unavailable. Nettongia can continue working offline.", "更新检查目前不可用。Nettongia 可以继续离线工作。", "अपडेट जाँच अभी उपलब्ध नहीं है। Nettongia ऑफ़लाइन काम जारी रख सकता है।", "La comprobación de actualizaciones no está disponible. Nettongia puede seguir funcionando sin conexión.", "La recherche de mises à jour est indisponible. Nettongia peut continuer à fonctionner hors ligne.", "التحقق من التحديثات غير متاح حاليًا. يمكن لـ Nettongia متابعة العمل دون اتصال.", "আপডেট পরীক্ষা বর্তমানে উপলব্ধ নয়। Nettongia অফলাইনে কাজ চালিয়ে যেতে পারে।", "A verificação de atualizações não está disponível. O Nettongia pode continuar a funcionar offline.", "Pemeriksaan pembaruan saat ini tidak tersedia. Nettongia tetap dapat bekerja secara offline.", "اپ ڈیٹ کی جانچ فی الحال دستیاب نہیں۔ Nettongia آف لائن کام جاری رکھ سکتا ہے۔", "Kontrola aktualizací není nyní dostupná. Nettongia může dál pracovat offline.", "Kontrola aktualizácií momentálne nie je dostupná. Nettongia môže ďalej pracovať offline.", "Sprawdzanie aktualizacji jest obecnie niedostępne. Nettongia może nadal działać offline."),
    "open_release_page": ("Open release page", "打开发布页面", "रिलीज़ पृष्ठ खोलें", "Abrir página de publicación", "Ouvrir la page de publication", "فتح صفحة الإصدار", "রিলিজ পৃষ্ঠা খুলুন", "Abrir página da versão", "Buka halaman rilis", "ریلیز صفحہ کھولیں", "Otevřít stránku vydání", "Otvoriť stránku vydania", "Otwórz stronę wydania"),
    "font": ("Font", "字体", "फ़ॉन्ट", "Fuente", "Police", "الخط", "ফন্ট", "Tipo de letra", "Шрифт", "فونٹ", "Písmo", "Písmo", "Czcionka"),
    "font_size": ("Font size", "字号", "फ़ॉन्ट आकार", "Tamaño de fuente", "Taille de police", "حجم الخط", "ফন্টের আকার", "Tamanho da letra", "Размер шрифта", "فونٹ سائز", "Velikost písma", "Veľkosť písma", "Rozmiar czcionki"),
    "bold": ("Bold", "粗体", "बोल्ड", "Negrita", "Gras", "عريض", "গাঢ়", "Negrito", "Полужирный", "موٹا", "Tučné", "Tučné", "Pogrubienie"),
    "italic": ("Italic", "斜体", "इटैलिक", "Cursiva", "Italique", "مائل", "তির্যক", "Itálico", "Курсив", "ترچھا", "Kurzíva", "Kurzíva", "Kursywa"),
    "underline": ("Underline", "下划线", "रेखांकित", "Subrayado", "Souligné", "تسطير", "নিম্নরেখা", "Sublinhado", "Подчёркивание", "خط کشیدہ", "Podtržení", "Podčiarknutie", "Podkreślenie"),
    "text_color": ("Text color", "文本颜色", "पाठ रंग", "Color del texto", "Couleur du texte", "لون النص", "লেখার রং", "Cor do texto", "Цвет текста", "متن کا رنگ", "Barva textu", "Farba textu", "Kolor tekstu"),
    "current_zoom": ("Current zoom", "当前缩放", "वर्तमान ज़ूम", "Zoom actual", "Zoom actuel", "التكبير الحالي", "বর্তমান জুম", "Zoom atual", "Текущий масштаб", "موجودہ زوم", "Aktuální přiblížení", "Aktuálne priblíženie", "Bieżące powiększenie"),
    "create": ("Create", "创建", "बनाएँ", "Crear", "Créer", "إنشاء", "তৈরি করুন", "Criar", "Создать", "بنائیں", "Vytvořit", "Vytvoriť", "Utwórz"),
    "cancel": ("Cancel", "取消", "रद्द करें", "Cancelar", "Annuler", "إلغاء", "বাতিল", "Cancelar", "Отмена", "منسوخ", "Zrušit", "Zrušiť", "Anuluj"),
    "save": ("Save", "保存", "सहेजें", "Guardar", "Enregistrer", "حفظ", "সংরক্ষণ", "Guardar", "Сохранить", "محفوظ کریں", "Uložit", "Uložiť", "Zapisz"),
    "discard": ("Discard", "放弃", "छोड़ें", "Descartar", "Ignorer", "تجاهل", "বাতিল করুন", "Descartar", "Не сохранять", "رد کریں", "Zahodit", "Zahodiť", "Odrzuć"),
    "yes": ("Yes", "是", "हाँ", "Sí", "Oui", "نعم", "হ্যাঁ", "Sim", "Да", "ہاں", "Ano", "Áno", "Tak"),
    "no": ("No", "否", "नहीं", "No", "Non", "لا", "না", "Não", "Нет", "نہیں", "Ne", "Nie", "Nie"),
    "new_title": ("Create new PDF", "创建新 PDF", "नया PDF बनाएँ", "Crear nuevo PDF", "Créer un nouveau PDF", "إنشاء PDF جديد", "নতুন PDF তৈরি করুন", "Criar novo PDF", "Создать новый PDF", "نئی PDF بنائیں", "Vytvořit nové PDF", "Vytvoriť nové PDF", "Utwórz nowy PDF"),
    "custom_size": ("Custom size", "自定义尺寸", "कस्टम आकार", "Tamaño personalizado", "Format personnalisé", "حجم مخصص", "নিজস্ব আকার", "Tamanho personalizado", "Другой размер", "مخصوص سائز", "Vlastní velikost", "Vlastná veľkosť", "Rozmiar niestandardowy"),
    "portrait": ("Portrait", "纵向", "पोर्ट्रेट", "Vertical", "Portrait", "عمودي", "লম্বালম্বি", "Vertical", "Книжная", "عمودی", "Na výšku", "Na výšku", "Pionowa"),
    "landscape": ("Landscape", "横向", "लैंडस्केप", "Horizontal", "Paysage", "أفقي", "আড়াআড়ি", "Horizontal", "Альбомная", "افقی", "Na šířku", "Na šírku", "Pozioma"),
    "page_size": ("Page size", "页面大小", "पृष्ठ आकार", "Tamaño de página", "Format de page", "حجم الصفحة", "পৃষ্ঠার আকার", "Tamanho da página", "Размер страницы", "صفحے کا سائز", "Velikost stránky", "Veľkosť strany", "Rozmiar strony"),
    "orientation": ("Orientation", "方向", "अभिविन्यास", "Orientación", "Orientation", "الاتجاه", "অভিমুখ", "Orientação", "Ориентация", "سمت", "Orientace", "Orientácia", "Orientacja"),
    "width": ("Width", "宽度", "चौड़ाई", "Ancho", "Largeur", "العرض", "প্রস্থ", "Largura", "Ширина", "چوڑائی", "Šířka", "Šírka", "Szerokość"),
    "height": ("Height", "高度", "ऊँचाई", "Alto", "Hauteur", "الارتفاع", "উচ্চতা", "Altura", "Высота", "اونچائی", "Výška", "Výška", "Wysokość"),
    "page_count": ("Number of pages", "页数", "पृष्ठों की संख्या", "Número de páginas", "Nombre de pages", "عدد الصفحات", "পৃষ্ঠা সংখ্যা", "Número de páginas", "Количество страниц", "صفحات کی تعداد", "Počet stránek", "Počet strán", "Liczba stron"),
    "result": ("Result", "结果", "परिणाम", "Resultado", "Résultat", "النتيجة", "ফলাফল", "Resultado", "Результат", "نتیجہ", "Výsledek", "Výsledok", "Wynik"),
    "blank_pdf_intro": ("Create a blank PDF document:", "创建空白 PDF 文档：", "एक खाली PDF दस्तावेज़ बनाएँ:", "Crear un documento PDF en blanco:", "Créer un document PDF vierge :", "إنشاء مستند PDF فارغ:", "একটি ফাঁকা PDF তৈরি করুন:", "Criar um documento PDF em branco:", "Создать пустой PDF-документ:", "خالی PDF دستاویز بنائیں:", "Vytvořit prázdný dokument PDF:", "Vytvoriť prázdny dokument PDF:", "Utwórz pusty dokument PDF:"),
    "signature_title": ("Insert visual signature", "插入可视签名", "दृश्य हस्ताक्षर डालें", "Insertar firma visual", "Insérer une signature visuelle", "إدراج توقيع مرئي", "দৃশ্যমান স্বাক্ষর যোগ করুন", "Inserir assinatura visual", "Вставить визуальную подпись", "ظاہری دستخط شامل کریں", "Vložit vizuální podpis", "Vložiť vizuálny podpis", "Wstaw podpis wizualny"),
    "signature_warning": ("This inserts a visible signature into the page. It is not a certificate-based digital signature.", "这会在页面中插入可见签名，并非基于证书的数字签名。", "यह पृष्ठ पर दिखाई देने वाला हस्ताक्षर जोड़ता है। यह प्रमाणपत्र-आधारित डिजिटल हस्ताक्षर नहीं है।", "Esto inserta una firma visible en la página. No es una firma digital basada en certificado.", "Ceci insère une signature visible dans la page. Ce n’est pas une signature numérique certifiée.", "يُدرج هذا توقيعًا مرئيًا في الصفحة، وليس توقيعًا رقميًا قائمًا على شهادة.", "এটি পৃষ্ঠায় দৃশ্যমান স্বাক্ষর যোগ করে; এটি সার্টিফিকেটভিত্তিক ডিজিটাল স্বাক্ষর নয়।", "Isto insere uma assinatura visível na página. Não é uma assinatura digital baseada em certificado.", "Это добавляет видимую подпись на страницу, а не цифровую подпись на основе сертификата.", "یہ صفحے پر نظر آنے والا دستخط شامل کرتا ہے؛ یہ سرٹیفکیٹ پر مبنی ڈیجیٹل دستخط نہیں ہے۔", "Tímto vložíte na stránku viditelný podpis. Nejde o digitální podpis založený na certifikátu.", "Týmto vložíte na stranu viditeľný podpis. Nejde o digitálny podpis založený na certifikáte.", "Spowoduje to wstawienie widocznego podpisu na stronie. Nie jest to podpis cyfrowy oparty na certyfikacie."),
    "draw_signature": ("Draw signature", "绘制签名", "हस्ताक्षर बनाएँ", "Dibujar firma", "Dessiner la signature", "رسم التوقيع", "স্বাক্ষর আঁকুন", "Desenhar assinatura", "Нарисовать подпись", "دستخط بنائیں", "Nakreslit podpis", "Nakresliť podpis", "Narysuj podpis"),
    "type_signature": ("Type signature", "输入签名", "हस्ताक्षर लिखें", "Escribir firma", "Saisir la signature", "كتابة التوقيع", "স্বাক্ষর লিখুন", "Escrever assinatura", "Напечатать подпись", "دستخط لکھیں", "Napsat podpis", "Napísať podpis", "Wpisz podpis"),
    "clear_drawing": ("Clear drawing", "清除绘图", "चित्र साफ़ करें", "Borrar dibujo", "Effacer le dessin", "مسح الرسم", "অঙ্কন মুছুন", "Limpar desenho", "Очистить рисунок", "ڈرائنگ صاف کریں", "Vymazat kresbu", "Vymazať kresbu", "Wyczyść rysunek"),
    "draw_hint": ("Draw inside the box using the mouse or a pen:", "使用鼠标或手写笔在框内绘制：", "माउस या पेन से बॉक्स में हस्ताक्षर बनाएँ:", "Dibuje dentro del cuadro con el ratón o un lápiz:", "Dessinez dans le cadre avec la souris ou un stylet :", "ارسم داخل المربع باستخدام الفأرة أو القلم:", "মাউস বা কলম দিয়ে বাক্সের মধ্যে আঁকুন:", "Desenhe dentro da caixa com o rato ou uma caneta:", "Рисуйте в рамке мышью или пером:", "ماؤس یا قلم سے خانے کے اندر بنائیں:", "Kreslete do rámečku myší nebo perem:", "Kreslite do rámčeka myšou alebo perom:", "Rysuj w polu za pomocą myszy lub pióra:"),
    "your_name": ("Your name", "您的姓名", "आपका नाम", "Su nombre", "Votre nom", "اسمك", "আপনার নাম", "O seu nome", "Ваше имя", "آپ کا نام", "Vaše jméno", "Vaše meno", "Twoje imię i nazwisko"),
    "signature_text": ("Signature text", "签名文本", "हस्ताक्षर पाठ", "Texto de firma", "Texte de la signature", "نص التوقيع", "স্বাক্ষরের লেখা", "Texto da assinatura", "Текст подписи", "دستخط کا متن", "Text podpisu", "Text podpisu", "Tekst podpisu"),
    "size": ("Size", "大小", "आकार", "Tamaño", "Taille", "الحجم", "আকার", "Tamanho", "Размер", "سائز", "Velikost", "Veľkosť", "Rozmiar"),
    "style": ("Style", "样式", "शैली", "Estilo", "Style", "النمط", "শৈলী", "Estilo", "Стиль", "انداز", "Styl", "Štýl", "Styl"),
    "width_on_page": ("Width on page", "页面宽度", "पृष्ठ पर चौड़ाई", "Ancho en la página", "Largeur sur la page", "العرض على الصفحة", "পৃষ্ঠায় প্রস্থ", "Largura na página", "Ширина на странице", "صفحے پر چوڑائی", "Šířka na stránce", "Šírka na strane", "Szerokość na stronie"),
    "rotation": ("Rotation", "旋转", "घुमाव", "Rotación", "Rotation", "التدوير", "ঘূর্ণন", "Rotação", "Поворот", "گردش", "Natočení", "Otočenie", "Obrót"),
    "compress_title": ("Compress PDF", "压缩 PDF", "PDF संपीड़ित करें", "Comprimir PDF", "Compresser le PDF", "ضغط PDF", "PDF সংকুচিত করুন", "Comprimir PDF", "Сжать PDF", "PDF سکیڑیں", "Komprimovat PDF", "Komprimovať PDF", "Kompresuj PDF"),
    "lossless": ("Lossless optimization", "无损优化", "दोषरहित अनुकूलन", "Optimización sin pérdida", "Optimisation sans perte", "تحسين دون فقد", "ক্ষতিহীন অপ্টিমাইজেশন", "Otimização sem perdas", "Оптимизация без потерь", "بے ضرر اصلاح", "Bezeztrátová optimalizace", "Bezstratová optimalizácia", "Optymalizacja bezstratna"),
    "balanced": ("Balanced - recommended", "平衡 - 推荐", "संतुलित - अनुशंसित", "Equilibrado - recomendado", "Équilibré - recommandé", "متوازن - موصى به", "ভারসাম্যপূর্ণ - প্রস্তাবিত", "Equilibrado - recomendado", "Сбалансированное - рекомендуется", "متوازن - تجویز کردہ", "Vyvážená - doporučeno", "Vyvážená - odporúčané", "Zrównoważona - zalecana"),
    "strong": ("Strong - smallest file", "强力 - 最小文件", "मज़बूत - सबसे छोटी फ़ाइल", "Fuerte - archivo mínimo", "Forte - fichier minimal", "قوي - أصغر ملف", "শক্তিশালী - ক্ষুদ্রতম ফাইল", "Forte - ficheiro mínimo", "Сильное - минимальный файл", "زیادہ - سب سے چھوٹی فائل", "Silná - nejmenší soubor", "Silná - najmenší súbor", "Silna - najmniejszy plik"),
    "compression_profile": ("Compression profile", "压缩配置", "संपीड़न प्रोफ़ाइल", "Perfil de compresión", "Profil de compression", "ملف الضغط", "সংকোচন প্রোফাইল", "Perfil de compressão", "Профиль сжатия", "کمپریشن پروفائل", "Profil komprese", "Profil kompresie", "Profil kompresji"),
    "open_to_begin": ("Open a PDF or create a new one to begin", "打开或新建 PDF 以开始", "शुरू करने के लिए PDF खोलें या बनाएँ", "Abra o cree un PDF para comenzar", "Ouvrez ou créez un PDF pour commencer", "افتح ملف PDF أو أنشئ واحدًا للبدء", "শুরু করতে PDF খুলুন বা তৈরি করুন", "Abra ou crie um PDF para começar", "Откройте или создайте PDF", "شروع کرنے کے لیے PDF کھولیں یا بنائیں", "Začněte otevřením nebo vytvořením PDF", "Začnite otvorením alebo vytvorením PDF", "Otwórz lub utwórz PDF, aby rozpocząć"),
    "print_failed": ("Printing failed", "打印失败", "मुद्रण विफल", "Error de impresión", "Échec de l’impression", "فشلت الطباعة", "প্রিন্ট ব্যর্থ হয়েছে", "Falha na impressão", "Pencetakan gagal", "پرنٹنگ ناکام", "Tisk se nezdařil", "Tlač zlyhala", "Drukowanie nie powiodło się"),
    "print_complete": ("Print job sent: {count} page(s).", "打印任务已发送：{count} 页。", "प्रिंट कार्य भेजा गया: {count} पृष्ठ।", "Trabajo de impresión enviado: {count} página(s).", "Tâche d’impression envoyée : {count} page(s).", "تم إرسال مهمة الطباعة: {count} صفحة.", "প্রিন্ট কাজ পাঠানো হয়েছে: {count} পৃষ্ঠা।", "Trabalho de impressão enviado: {count} página(s).", "Pekerjaan cetak dikirim: {count} halaman.", "پرنٹ کام بھیج دیا گیا: {count} صفحہ۔", "Tisková úloha byla odeslána: {count} stránek.", "Tlačová úloha bola odoslaná: {count} strán.", "Zadanie drukowania wysłano: {count} stron."),
    "sidebar_pages": ("Pages", "页面", "पृष्ठ", "Páginas", "Pages", "الصفحات", "পৃষ্ঠাসমূহ", "Páginas", "Halaman", "صفحات", "Stránky", "Strany", "Strony"),
    "sidebar_tree": ("Tree", "文档树", "दस्तावेज़ वृक्ष", "Árbol", "Arborescence", "شجرة المستند", "নথির গাছ", "Árvore", "Struktur", "دستاویز کا درخت", "Strom", "Strom", "Drzewo"),
    "no_document_tree": ("This PDF has no document tree.", "此 PDF 没有文档树。", "इस PDF में दस्तावेज़ वृक्ष नहीं है।", "Este PDF no contiene un árbol de documento.", "Ce PDF ne contient aucune arborescence de document.", "لا يحتوي ملف PDF هذا على شجرة مستند.", "এই PDF-এ কোনো নথির গাছ নেই।", "Este PDF não contém uma árvore do documento.", "PDF ini tidak memiliki struktur dokumen.", "اس PDF میں دستاویز کا درخت نہیں ہے۔", "Toto PDF neobsahuje strom dokumentu.", "Toto PDF neobsahuje strom dokumentu.", "Ten plik PDF nie zawiera drzewa dokumentu."),
}

_ROWS.update({
    "forms": ("Forms", "表单", "फ़ॉर्म", "Formularios", "Formulaires", "النماذج", "ফর্ম", "Formulários", "Formulir", "فارمز", "Formuláře", "Formuláre", "Formularze"),
    "edit_form_field": ("Edit selected form field...", "编辑所选表单字段...", "चुना हुआ फ़ॉर्म फ़ील्ड संपादित करें...", "Editar campo de formulario seleccionado...", "Modifier le champ de formulaire sélectionné...", "تحرير حقل النموذج المحدد...", "নির্বাচিত ফর্ম ক্ষেত্র সম্পাদনা করুন...", "Editar campo de formulário selecionado...", "Edit bidang formulir terpilih...", "منتخب فارم فیلڈ میں ترمیم کریں...", "Upravit vybrané pole formuláře...", "Upraviť vybrané pole formulára...", "Edytuj wybrane pole formularza..."),
    "no_form_fields": ("This PDF has no supported AcroForm fields.", "此 PDF 没有受支持的 AcroForm 字段。", "इस PDF में समर्थित AcroForm फ़ील्ड नहीं हैं।", "Este PDF no tiene campos AcroForm compatibles.", "Ce PDF ne contient aucun champ AcroForm pris en charge.", "لا يحتوي ملف PDF هذا على حقول AcroForm مدعومة.", "এই PDF-এ সমর্থিত AcroForm ক্ষেত্র নেই।", "Este PDF não contém campos AcroForm compatíveis.", "PDF ini tidak memiliki bidang AcroForm yang didukung.", "اس PDF میں معاون AcroForm فیلڈز نہیں ہیں۔", "Toto PDF neobsahuje podporovaná pole AcroForm.", "Toto PDF neobsahuje podporované polia AcroForm.", "Ten PDF nie zawiera obsługiwanych pól AcroForm."),
    "unnamed_form_field": ("Unnamed field", "未命名字段", "अनाम फ़ील्ड", "Campo sin nombre", "Champ sans nom", "حقل بلا اسم", "নামহীন ক্ষেত্র", "Campo sem nome", "Bidang tanpa nama", "بے نام فیلڈ", "Pole bez názvu", "Pole bez názvu", "Pole bez nazwy"),
    "form_checked": ("Checked", "已选中", "चयनित", "Marcado", "Coché", "محدد", "নির্বাচিত", "Marcado", "Dicentang", "منتخب", "Zaškrtnuto", "Začiarknuté", "Zaznaczone"),
    "form_unchecked": ("Unchecked", "未选中", "अचयनित", "No marcado", "Non coché", "غير محدد", "অনির্বাচিত", "Desmarcado", "Tidak dicentang", "غیر منتخب", "Nezaškrtnuto", "Nezačiarknuté", "Niezaznaczone"),
    "form_empty": ("Empty", "空", "खाली", "Vacío", "Vide", "فارغ", "খালি", "Vazio", "Kosong", "خالی", "Prázdné", "Prázdne", "Puste"),
    "form_read_only": ("Read-only", "只读", "केवल पढ़ने योग्य", "Solo lectura", "Lecture seule", "للقراءة فقط", "শুধু পাঠযোগ্য", "Somente leitura", "Hanya baca", "صرف پڑھنے کے لیے", "Jen pro čtení", "Iba na čítanie", "Tylko do odczytu"),
    "form_read_only_message": ("This form field is read-only and cannot be changed.", "此表单字段为只读，无法更改。", "यह फ़ॉर्म फ़ील्ड केवल पढ़ने योग्य है और बदला नहीं जा सकता।", "Este campo es de solo lectura y no se puede cambiar.", "Ce champ est en lecture seule et ne peut pas être modifié.", "حقل النموذج هذا للقراءة فقط ولا يمكن تغييره.", "এই ফর্ম ক্ষেত্রটি শুধু পাঠযোগ্য এবং পরিবর্তন করা যায় না।", "Este campo é somente leitura e não pode ser alterado.", "Bidang ini hanya baca dan tidak dapat diubah.", "یہ فارم فیلڈ صرف پڑھنے کے لیے ہے اور تبدیل نہیں ہو سکتی۔", "Toto pole formuláře je jen pro čtení a nelze je změnit.", "Toto pole formulára je iba na čítanie a nemožno ho zmeniť.", "To pole formularza jest tylko do odczytu i nie można go zmienić."),
    "form_value": ("Value:", "值：", "मान:", "Valor:", "Valeur :", "القيمة:", "মান:", "Valor:", "Nilai:", "قدر:", "Hodnota:", "Hodnota:", "Wartość:"),
    "form_no_choices": ("This choice field has no available values.", "此选择字段没有可用值。", "इस चयन फ़ील्ड में उपलब्ध मान नहीं हैं।", "Este campo de selección no tiene valores disponibles.", "Ce champ de choix ne contient aucune valeur disponible.", "لا يحتوي حقل الاختيار هذا على قيم متاحة.", "এই নির্বাচন ক্ষেত্রে কোনো মান নেই।", "Este campo de escolha não possui valores disponíveis.", "Bidang pilihan ini tidak memiliki nilai yang tersedia.", "اس انتخابی فیلڈ میں کوئی دستیاب قدر نہیں ہے۔", "Toto výběrové pole nemá žádné dostupné hodnoty.", "Toto výberové pole nemá žiadne dostupné hodnoty.", "To pole wyboru nie ma dostępnych wartości."),
    "form_unsupported": ("This form field type is not supported for editing.", "不支持编辑此类型的表单字段。", "इस प्रकार के फ़ॉर्म फ़ील्ड का संपादन समर्थित नहीं है।", "Este tipo de campo no se puede editar.", "Ce type de champ ne peut pas être modifié.", "تحرير هذا النوع من حقول النموذج غير مدعوم.", "এই ধরনের ফর্ম ক্ষেত্র সম্পাদনা সমর্থিত নয়।", "Este tipo de campo não pode ser editado.", "Jenis bidang formulir ini tidak didukung untuk diedit.", "اس قسم کی فارم فیلڈ کی تدوین معاون نہیں ہے۔", "Úprava tohoto typu pole formuláře není podporována.", "Úprava tohto typu poľa formulára nie je podporovaná.", "Edycja tego typu pola formularza nie jest obsługiwana."),
    "form_updated": ("Form field updated. Use Undo to restore the previous value.", "表单字段已更新。使用撤销可恢复以前的值。", "फ़ॉर्म फ़ील्ड अपडेट हुआ। पिछला मान लौटाने के लिए पूर्ववत करें।", "Campo actualizado. Use Deshacer para restaurar el valor anterior.", "Champ mis à jour. Utilisez Annuler pour restaurer la valeur précédente.", "تم تحديث حقل النموذج. استخدم تراجع لاستعادة القيمة السابقة.", "ফর্ম ক্ষেত্র আপডেট হয়েছে। আগের মান ফেরাতে পূর্বাবস্থায় ফেরান।", "Campo atualizado. Use Anular para restaurar o valor anterior.", "Bidang formulir diperbarui. Gunakan Urungkan untuk memulihkan nilai sebelumnya.", "فارم فیلڈ اپ ڈیٹ ہو گئی۔ سابقہ قدر بحال کرنے کے لیے کالعدم کریں۔", "Pole formuláře bylo upraveno. Pomocí Zpět obnovíte předchozí hodnotu.", "Pole formulára bolo upravené. Pomocou Späť obnovíte predchádzajúcu hodnotu.", "Pole formularza zostało zaktualizowane. Użyj Cofnij, aby przywrócić poprzednią wartość."),
    "move_page_up": ("Move page earlier", "向前移动页面", "पृष्ठ को पहले ले जाएँ", "Mover página antes", "Déplacer la page plus tôt", "نقل الصفحة إلى موضع سابق", "পৃষ্ঠা আগে সরান", "Mover página para antes", "Pindahkan halaman ke depan", "صفحہ پہلے منتقل کریں", "Přesunout stránku výše", "Presunúť stranu vyššie", "Przenieś stronę wyżej"),
    "move_page_down": ("Move page later", "向后移动页面", "पृष्ठ को बाद में ले जाएँ", "Mover página después", "Déplacer la page plus tard", "نقل الصفحة إلى موضع لاحق", "পৃষ্ঠা পরে সরান", "Mover página para depois", "Pindahkan halaman ke belakang", "صفحہ بعد میں منتقل کریں", "Přesunout stránku níže", "Presunúť stranu nižšie", "Przenieś stronę niżej"),
    "page_moved": ("Page moved to position {page}.", "页面已移动到位置 {page}。", "पृष्ठ को स्थान {page} पर ले जाया गया।", "Página movida a la posición {page}.", "Page déplacée à la position {page}.", "تم نقل الصفحة إلى الموضع {page}.", "পৃষ্ঠা {page} অবস্থানে সরানো হয়েছে।", "Página movida para a posição {page}.", "Halaman dipindahkan ke posisi {page}.", "صفحہ مقام {page} پر منتقل کر دیا گیا۔", "Stránka byla přesunuta na pozici {page}.", "Strana bola presunutá na pozíciu {page}.", "Strona została przeniesiona na pozycję {page}."),
    "rotate_page_left": ("Rotate page left", "向左旋转页面", "पृष्ठ को बाएँ घुमाएँ", "Girar página a la izquierda", "Faire pivoter la page à gauche", "تدوير الصفحة إلى اليسار", "পৃষ্ঠা বামে ঘোরান", "Rodar página para a esquerda", "Putar halaman ke kiri", "صفحہ بائیں گھمائیں", "Otočit stránku doleva", "Otočiť stranu doľava", "Obróć stronę w lewo"),
    "rotate_page_right": ("Rotate page right", "向右旋转页面", "पृष्ठ को दाएँ घुमाएँ", "Girar página a la derecha", "Faire pivoter la page à droite", "تدوير الصفحة إلى اليمين", "পৃষ্ঠা ডানে ঘোরান", "Rodar página para a direita", "Putar halaman ke kanan", "صفحہ دائیں گھمائیں", "Otočit stránku doprava", "Otočiť stranu doprava", "Obróć stronę w prawo"),
    "page_rotated": ("Page {page} rotated.", "页面 {page} 已旋转。", "पृष्ठ {page} घुमाया गया।", "Página {page} girada.", "Page {page} pivotée.", "تم تدوير الصفحة {page}.", "পৃষ্ঠা {page} ঘোরানো হয়েছে।", "Página {page} rodada.", "Halaman {page} diputar.", "صفحہ {page} گھما دیا گیا۔", "Stránka {page} byla otočena.", "Strana {page} bola otočená.", "Strona {page} została obrócona."),
    "edit_original_image": ("Edit original image...", "编辑原始图像...", "मूल छवि संपादित करें...", "Editar imagen original...", "Modifier l’image d’origine...", "تحرير الصورة الأصلية...", "মূল ছবি সম্পাদনা করুন...", "Editar imagem original...", "Edit gambar asli...", "اصل تصویر میں ترمیم کریں...", "Upravit původní obrázek...", "Upraviť pôvodný obrázok...", "Edytuj oryginalny obraz..."),
    "edit_original_image_hint": ("Click an original image to make it movable, resizable, and rotatable. Press Esc to cancel.", "单击原始图像，使其可移动、调整大小和旋转。按 Esc 取消。", "मूल छवि पर क्लिक करके उसे चलने, आकार बदलने और घुमाने योग्य बनाएँ। रद्द करने के लिए Esc दबाएँ।", "Haga clic en una imagen original para poder moverla, redimensionarla y girarla. Pulse Esc para cancelar.", "Cliquez sur une image d’origine pour pouvoir la déplacer, la redimensionner et la faire pivoter. Appuyez sur Échap pour annuler.", "انقر على صورة أصلية لجعلها قابلة للنقل وتغيير الحجم والتدوير. اضغط Esc للإلغاء.", "মূল ছবিতে ক্লিক করে সেটিকে সরানো, আকার বদলানো ও ঘোরানোর উপযোগী করুন। বাতিল করতে Esc চাপুন।", "Clique numa imagem original para a tornar movível, redimensionável e rotativa. Prima Esc para cancelar.", "Klik gambar asli agar dapat dipindahkan, diubah ukurannya, dan diputar. Tekan Esc untuk batal.", "اصل تصویر کو قابلِ حرکت، قابلِ سائز تبدیلی اور قابلِ گردش بنانے کے لیے کلک کریں۔ منسوخ کرنے کے لیے Esc دبائیں۔", "Klikněte na původní obrázek, který chcete přesouvat, měnit jeho velikost a otáčet. Esc akci zruší.", "Kliknite na pôvodný obrázok, ktorý chcete presúvať, meniť jeho veľkosť a otáčať. Esc akciu zruší.", "Kliknij oryginalny obraz, aby go przesuwać, skalować i obracać. Esc anuluje operację."),
    "original_image": ("Original image", "原始图像", "मूल छवि", "Imagen original", "Image d’origine", "الصورة الأصلية", "মূল ছবি", "Imagem original", "Gambar asli", "اصل تصویر", "Původní obrázek", "Pôvodný obrázok", "Oryginalny obraz"),
    "original_image_ready": ("The original image is now editable. Drag it or use the resize and rotation handles.", "原始图像现在可编辑。拖动它或使用大小和旋转手柄。", "मूल छवि अब संपादन योग्य है। उसे खींचें या आकार और घुमाव हैंडल का उपयोग करें।", "La imagen original ya se puede editar. Arrástrela o use los controles de tamaño y rotación.", "L’image d’origine est maintenant modifiable. Faites-la glisser ou utilisez les poignées de taille et de rotation.", "أصبحت الصورة الأصلية قابلة للتحرير. اسحبها أو استخدم مقابض الحجم والتدوير.", "মূল ছবি এখন সম্পাদনাযোগ্য। টেনে নিন বা আকার ও ঘূর্ণন হ্যান্ডেল ব্যবহার করুন।", "A imagem original está agora editável. Arraste-a ou use as alças de tamanho e rotação.", "Gambar asli sekarang dapat diedit. Seret atau gunakan gagang ukuran dan rotasi.", "اصل تصویر اب قابلِ ترمیم ہے۔ اسے کھینچیں یا سائز اور گردش کے ہینڈل استعمال کریں۔", "Původní obrázek je nyní upravitelný. Přetáhněte jej nebo použijte úchyty velikosti a otočení.", "Pôvodný obrázok je teraz upraviteľný. Presuňte ho alebo použite úchyty veľkosti a otočenia.", "Oryginalny obraz można teraz edytować. Przeciągnij go lub użyj uchwytów rozmiaru i obrotu."),
    "save_copy": ("Save a Copy...", "保存副本...", "एक प्रति सहेजें...", "Guardar una copia...", "Enregistrer une copie...", "حفظ نسخة...", "একটি অনুলিপি সংরক্ষণ করুন...", "Guardar uma cópia...", "Simpan salinan...", "ایک نقل محفوظ کریں...", "Uložit kopii...", "Uložiť kópiu...", "Zapisz kopię..."),
    "pdf_password_title": ("Protected PDF", "受保护的 PDF", "सुरक्षित PDF", "PDF protegido", "PDF protégé", "ملف PDF محمي", "সুরক্ষিত PDF", "PDF protegido", "PDF terlindungi", "محفوظ PDF", "Chráněné PDF", "Chránené PDF", "Chroniony PDF"),
    "pdf_password_prompt": ("Enter the password to open this PDF:", "请输入密码以打开此 PDF：", "इस PDF को खोलने के लिए पासवर्ड दर्ज करें:", "Introduzca la contraseña para abrir este PDF:", "Saisissez le mot de passe pour ouvrir ce PDF :", "أدخل كلمة المرور لفتح ملف PDF هذا:", "এই PDF খুলতে পাসওয়ার্ড লিখুন:", "Introduza a palavra-passe para abrir este PDF:", "Masukkan kata sandi untuk membuka PDF ini:", "اس PDF کو کھولنے کے لیے پاس ورڈ درج کریں:", "Zadejte heslo pro otevření tohoto PDF:", "Zadajte heslo na otvorenie tohto PDF:", "Wprowadź hasło, aby otworzyć ten plik PDF:"),
    "pdf_password_incorrect": ("Incorrect password. Try again:", "密码不正确。请重试：", "पासवर्ड गलत है। पुनः प्रयास करें:", "Contraseña incorrecta. Inténtelo de nuevo:", "Mot de passe incorrect. Réessayez :", "كلمة المرور غير صحيحة. حاول مرة أخرى:", "ভুল পাসওয়ার্ড। আবার চেষ্টা করুন:", "Palavra-passe incorreta. Tente novamente:", "Kata sandi salah. Coba lagi:", "پاس ورڈ غلط ہے۔ دوبارہ کوشش کریں:", "Nesprávné heslo. Zkuste to znovu:", "Nesprávne heslo. Skúste to znova:", "Nieprawidłowe hasło. Spróbuj ponownie:"),
    "pdf_password_removed_notice": ("The PDF was unlocked. Edited copies will be saved without password protection.", "PDF 已解锁。编辑后的副本将不带密码保护保存。", "PDF अनलॉक हो गया है। संपादित प्रतियाँ पासवर्ड सुरक्षा के बिना सहेजी जाएँगी।", "El PDF se ha desbloqueado. Las copias editadas se guardarán sin protección por contraseña.", "Le PDF a été déverrouillé. Les copies modifiées seront enregistrées sans protection par mot de passe.", "تم فتح ملف PDF. سيتم حفظ النسخ المعدلة من دون حماية بكلمة مرور.", "PDF আনলক করা হয়েছে। সম্পাদিত কপি পাসওয়ার্ড সুরক্ষা ছাড়াই সংরক্ষিত হবে।", "O PDF foi desbloqueado. As cópias editadas serão guardadas sem proteção por palavra-passe.", "PDF telah dibuka. Salinan yang diedit akan disimpan tanpa perlindungan kata sandi.", "PDF کھول دیا گیا ہے۔ ترمیم شدہ نقول پاس ورڈ کے تحفظ کے بغیر محفوظ ہوں گی۔", "PDF bylo odemčeno. Upravené kopie budou uloženy bez ochrany heslem.", "PDF bolo odomknuté. Upravené kópie sa uložia bez ochrany heslom.", "Plik PDF został odblokowany. Edytowane kopie zostaną zapisane bez ochrony hasłem."),
    "recent_files": ("Recent files", "最近使用的文件", "हाल की फ़ाइलें", "Archivos recientes", "Fichiers récents", "الملفات الأخيرة", "সাম্প্রতিক ফাইল", "Ficheiros recentes", "Berkas terbaru", "حالیہ فائلیں", "Nedávné soubory", "Nedávne súbory", "Ostatnie pliki"),
    "no_recent_files": ("No recent files", "没有最近使用的文件", "कोई हाल की फ़ाइल नहीं", "No hay archivos recientes", "Aucun fichier récent", "لا توجد ملفات أخيرة", "কোনো সাম্প্রতিক ফাইল নেই", "Sem ficheiros recentes", "Tidak ada berkas terbaru", "کوئی حالیہ فائل نہیں", "Žádné nedávné soubory", "Žiadne nedávne súbory", "Brak ostatnich plików"),
    "clear_recent_files": ("Clear recent files", "清除最近使用的文件", "हाल की फ़ाइलें साफ़ करें", "Borrar archivos recientes", "Effacer les fichiers récents", "مسح الملفات الأخيرة", "সাম্প্রতিক ফাইল মুছুন", "Limpar ficheiros recentes", "Hapus daftar berkas terbaru", "حالیہ فائلوں کی فہرست صاف کریں", "Vymazat seznam nedávných souborů", "Vymazať zoznam nedávnych súborov", "Wyczyść listę ostatnich plików"),
    "recent_file_missing": ("The file is no longer available:\n{path}", "该文件已不可用：\n{path}", "फ़ाइल अब उपलब्ध नहीं है:\n{path}", "El archivo ya no está disponible:\n{path}", "Le fichier n’est plus disponible :\n{path}", "لم يعد الملف متاحًا:\n{path}", "ফাইলটি আর পাওয়া যাচ্ছে না:\n{path}", "O ficheiro já não está disponível:\n{path}", "Berkas tidak lagi tersedia:\n{path}", "فائل اب دستیاب نہیں ہے:\n{path}", "Soubor již není dostupný:\n{path}", "Súbor už nie je dostupný:\n{path}", "Plik nie jest już dostępny:\n{path}"),
    "recovery_title": ("Recover unsaved work", "恢复未保存的工作", "सहेजे न गए काम को पुनर्प्राप्त करें", "Recuperar trabajo no guardado", "Récupérer le travail non enregistré", "استعادة العمل غير المحفوظ", "অসংরক্ষিত কাজ পুনরুদ্ধার করুন", "Recuperar trabalho não guardado", "Pulihkan pekerjaan yang belum disimpan", "غیر محفوظ کام بحال کریں", "Obnovit neuloženou práci", "Obnoviť neuloženú prácu", "Odzyskaj niezapisaną pracę"),
    "recovery_question": ("Nettongia PDF Editor found automatically saved unsaved work for {name}. Restore it?", "Nettongia PDF Editor 找到了为 {name} 自动保存的未保存工作。是否恢复？", "Nettongia PDF Editor को {name} के लिए स्वतः सहेजा गया काम मिला। क्या इसे पुनर्प्राप्त करें?", "Nettongia PDF Editor encontró trabajo no guardado automáticamente para {name}. ¿Desea recuperarlo?", "Nettongia PDF Editor a trouvé un travail non enregistré sauvegardé automatiquement pour {name}. Le restaurer ?", "عثر Nettongia PDF Editor على عمل غير محفوظ تم حفظه تلقائيًا للملف {name}. هل تريد استعادته؟", "Nettongia PDF Editor {name}-এর জন্য স্বয়ংক্রিয়ভাবে সংরক্ষিত কাজ খুঁজে পেয়েছে। এটি পুনরুদ্ধার করবেন?", "O Nettongia PDF Editor encontrou trabalho não guardado automaticamente para {name}. Pretende recuperá-lo?", "Nettongia PDF Editor menemukan pekerjaan yang disimpan otomatis untuk {name}. Pulihkan?", "Nettongia PDF Editor کو {name} کے لیے خودکار طور پر محفوظ کیا گیا کام ملا ہے۔ کیا اسے بحال کریں؟", "Nettongia PDF Editor našel automaticky uloženou neuloženou práci pro dokument {name}. Chcete ji obnovit?", "Nettongia PDF Editor našiel automaticky uloženú neuloženú prácu pre dokument {name}. Chcete ju obnoviť?", "Nettongia PDF Editor znalazł automatycznie zapisaną pracę dla dokumentu {name}. Czy ją odzyskać?"),
    "restore": ("Restore", "恢复", "पुनर्प्राप्त करें", "Restaurar", "Restaurer", "استعادة", "পুনরুদ্ধার", "Restaurar", "Pulihkan", "بحال کریں", "Obnovit", "Obnoviť", "Odzyskaj"),
    "recovery_unavailable": ("Automatic recovery is currently unavailable: {error}", "自动恢复当前不可用：{error}", "स्वचालित पुनर्प्राप्ति अभी उपलब्ध नहीं है: {error}", "La recuperación automática no está disponible: {error}", "La récupération automatique est actuellement indisponible : {error}", "الاستعادة التلقائية غير متاحة حاليًا: {error}", "স্বয়ংক্রিয় পুনরুদ্ধার বর্তমানে অনুপলব্ধ: {error}", "A recuperação automática não está disponível: {error}", "Pemulihan otomatis saat ini tidak tersedia: {error}", "خودکار بحالی فی الحال دستیاب نہیں ہے: {error}", "Automatické obnovení nyní není dostupné: {error}", "Automatické obnovenie teraz nie je dostupné: {error}", "Automatyczne odzyskiwanie jest obecnie niedostępne: {error}"),
    "recovery_failed_title": ("Recovery failed", "恢复失败", "पुनर्प्राप्ति विफल", "Error de recuperación", "Échec de la récupération", "فشلت الاستعادة", "পুনরুদ্ধার ব্যর্থ হয়েছে", "Falha na recuperação", "Pemulihan gagal", "بحالی ناکام ہو گئی", "Obnovení se nezdařilo", "Obnovenie zlyhalo", "Odzyskiwanie nie powiodło się"),
    "recovery_failed_message": ("The recovery data could not be opened. It was preserved for diagnostics at:\n{path}\n\n{error}", "无法打开恢复数据。数据已保留以供诊断：\n{path}\n\n{error}", "पुनर्प्राप्ति डेटा खोला नहीं जा सका। निदान के लिए इसे यहाँ सुरक्षित रखा गया है:\n{path}\n\n{error}", "No se pudieron abrir los datos de recuperación. Se conservaron para diagnóstico en:\n{path}\n\n{error}", "Les données de récupération n’ont pas pu être ouvertes. Elles ont été conservées à des fins de diagnostic ici :\n{path}\n\n{error}", "تعذر فتح بيانات الاستعادة. تم الاحتفاظ بها للتشخيص في:\n{path}\n\n{error}", "পুনরুদ্ধার ডেটা খোলা যায়নি। ত্রুটি নির্ণয়ের জন্য এটি এখানে রাখা হয়েছে:\n{path}\n\n{error}", "Não foi possível abrir os dados de recuperação. Foram preservados para diagnóstico em:\n{path}\n\n{error}", "Data pemulihan tidak dapat dibuka. Data disimpan untuk diagnosis di:\n{path}\n\n{error}", "بحالی کا ڈیٹا کھولا نہیں جا سکا۔ تشخیص کے لیے اسے یہاں محفوظ رکھا گیا ہے:\n{path}\n\n{error}", "Data pro obnovení nelze otevřít. Pro diagnostiku byla zachována zde:\n{path}\n\n{error}", "Dáta na obnovenie sa nepodarilo otvoriť. Na diagnostiku zostali uložené tu:\n{path}\n\n{error}", "Nie można otworzyć danych odzyskiwania. Zachowano je do diagnostyki w:\n{path}\n\n{error}"),
    "recovery_restored": ("Unsaved work was restored. Save the document to keep it.", "未保存的工作已恢复。请保存文档以保留这些更改。", "सहेजा न गया काम पुनर्प्राप्त हो गया। इसे रखने के लिए दस्तावेज़ सहेजें।", "Se recuperó el trabajo no guardado. Guarde el documento para conservarlo.", "Le travail non enregistré a été restauré. Enregistrez le document pour le conserver.", "تمت استعادة العمل غير المحفوظ. احفظ المستند للاحتفاظ به.", "অসংরক্ষিত কাজ পুনরুদ্ধার করা হয়েছে। এটি রাখতে নথিটি সংরক্ষণ করুন।", "O trabalho não guardado foi recuperado. Guarde o documento para o conservar.", "Pekerjaan yang belum disimpan telah dipulihkan. Simpan dokumen untuk mempertahankannya.", "غیر محفوظ کام بحال ہو گیا ہے۔ اسے برقرار رکھنے کے لیے دستاویز محفوظ کریں۔", "Neuložená práce byla obnovena. Zachováte ji uložením dokumentu.", "Neuložená práca bola obnovená. Zachováte ju uložením dokumentu.", "Niezapisana praca została odzyskana. Zapisz dokument, aby ją zachować."),
})

_ROWS.update({
    "ocr_page": ("OCR current page...", "OCR 当前页面...", "वर्तमान पृष्ठ OCR...", "OCR de la página actual...", "OCR de la page actuelle...", "OCR للصفحة الحالية...", "বর্তমান পৃষ্ঠার OCR...", "OCR da página atual...", "OCR halaman saat ini...", "موجودہ صفحے کا OCR...", "OCR aktuální stránky...", "OCR aktuálnej strany...", "OCR bieżącej strony..."),
    "ocr_document": ("OCR document...", "OCR 文档...", "दस्तावेज़ OCR...", "OCR del documento...", "OCR du document...", "OCR للمستند...", "নথির OCR...", "OCR do documento...", "OCR dokumen...", "دستاویز کا OCR...", "OCR dokumentu...", "OCR dokumentu...", "OCR dokumentu..."),
    "ocr_title": ("Text recognition (OCR)", "文本识别 (OCR)", "पाठ पहचान (OCR)", "Reconocimiento de texto (OCR)", "Reconnaissance de texte (OCR)", "التعرف على النص (OCR)", "পাঠ শনাক্তকরণ (OCR)", "Reconhecimento de texto (OCR)", "Pengenalan teks (OCR)", "متن کی شناخت (OCR)", "Rozpoznání textu (OCR)", "Rozpoznanie textu (OCR)", "Rozpoznawanie tekstu (OCR)"),
    "ocr_language_prompt": ("Recognition language:", "识别语言：", "पहचान भाषा:", "Idioma de reconocimiento:", "Langue de reconnaissance :", "لغة التعرف:", "শনাক্তকরণের ভাষা:", "Idioma de reconhecimento:", "Bahasa pengenalan:", "شناخت کی زبان:", "Jazyk rozpoznávání:", "Jazyk rozpoznávania:", "Język rozpoznawania:"),
    "ocr_unavailable": ("The bundled offline OCR language data is unavailable. Reinstall the complete Nettongia PDF Editor package.", "捆绑的离线 OCR 语言数据不可用。请重新安装完整的 Nettongia PDF Editor 软件包。", "बंडल किया गया ऑफ़लाइन OCR भाषा डेटा उपलब्ध नहीं है। पूरा Nettongia PDF Editor पैकेज फिर से इंस्टॉल करें।", "Los datos de idioma OCR sin conexión incluidos no están disponibles. Vuelva a instalar el paquete completo de Nettongia PDF Editor.", "Les données linguistiques OCR hors ligne incluses ne sont pas disponibles. Réinstallez le paquet complet Nettongia PDF Editor.", "بيانات لغة OCR غير المتصلة المضمّنة غير متاحة. أعد تثبيت حزمة Nettongia PDF Editor الكاملة.", "বান্ডেল করা অফলাইন OCR ভাষার ডেটা পাওয়া যাচ্ছে না। সম্পূর্ণ Nettongia PDF Editor প্যাকেজ পুনরায় ইনস্টল করুন।", "Os dados de idioma OCR offline incluídos não estão disponíveis. Reinstale o pacote completo do Nettongia PDF Editor.", "Data bahasa OCR offline yang disertakan tidak tersedia. Instal ulang paket Nettongia PDF Editor lengkap.", "شامل کردہ آف لائن OCR زبان کا ڈیٹا دستیاب نہیں۔ مکمل Nettongia PDF Editor پیکیج دوبارہ نصب کریں۔", "Přibalená offline jazyková data OCR nejsou dostupná. Znovu nainstalujte kompletní balíček Nettongia PDF Editor.", "Pribalené offline jazykové dáta OCR nie sú dostupné. Znova nainštalujte kompletný balík Nettongia PDF Editor.", "Dołączone dane językowe OCR offline są niedostępne. Zainstaluj ponownie cały pakiet Nettongia PDF Editor."),
    "ocr_working": ("Recognizing text in a separate process...", "正在独立进程中识别文本...", "अलग प्रक्रिया में पाठ पहचाना जा रहा है...", "Reconociendo texto en un proceso separado...", "Reconnaissance du texte dans un processus séparé...", "جارٍ التعرف على النص في عملية منفصلة...", "পৃথক প্রক্রিয়ায় পাঠ শনাক্ত করা হচ্ছে...", "Reconhecendo texto em um processo separado...", "Mengenali teks dalam proses terpisah...", "علیحدہ عمل میں متن شناخت کیا جا رہا ہے...", "Probíhá rozpoznávání textu v samostatném procesu...", "Prebieha rozpoznávanie textu v samostatnom procese...", "Rozpoznawanie tekstu w osobnym procesie..."),
    "ocr_complete": ("OCR completed: {pages} page(s), {words} recognized word(s).", "OCR 完成：{pages} 页，识别 {words} 个词。", "OCR पूर्ण: {pages} पृष्ठ, {words} शब्द पहचाने गए।", "OCR completado: {pages} página(s), {words} palabra(s).", "OCR terminé : {pages} page(s), {words} mot(s).", "اكتمل OCR: {pages} صفحة، {words} كلمة.", "OCR সম্পন্ন: {pages} পৃষ্ঠা, {words} শব্দ।", "OCR concluído: {pages} página(s), {words} palavra(s).", "OCR selesai: {pages} halaman, {words} kata.", "OCR مکمل: {pages} صفحات، {words} الفاظ۔", "OCR dokončeno: {pages} stran, rozpoznáno {words} slov.", "OCR dokončené: {pages} strán, rozpoznaných {words} slov.", "OCR zakończony: {pages} stron, rozpoznano {words} słów."),
    "ocr_nothing": ("OCR found no image-only page with recognizable text. Pages that already contain text were left unchanged.", "OCR 未找到包含可识别文本的纯图像页面。已有文本的页面未更改。", "OCR को पहचान योग्य पाठ वाला केवल-छवि पृष्ठ नहीं मिला। मौजूदा पाठ वाले पृष्ठ नहीं बदले गए।", "OCR no encontró páginas de solo imagen con texto reconocible. Las páginas con texto no se modificaron.", "OCR n'a trouvé aucune page image avec du texte reconnaissable. Les pages contenant déjà du texte sont inchangées.", "لم يعثر OCR على صفحة صور فقط بنص قابل للتعرف. لم تتغير الصفحات التي تحتوي على نص.", "OCR শনাক্তযোগ্য পাঠসহ শুধু-ছবির পৃষ্ঠা পায়নি। বিদ্যমান পাঠের পৃষ্ঠা অপরিবর্তিত রাখা হয়েছে।", "O OCR não encontrou páginas apenas com imagem e texto reconhecível. Páginas com texto não foram alteradas.", "OCR tidak menemukan halaman khusus gambar dengan teks yang dapat dikenali. Halaman yang sudah memiliki teks tidak diubah.", "OCR کو قابل شناخت متن والا صرف تصویری صفحہ نہیں ملا۔ پہلے سے متن والے صفحات تبدیل نہیں ہوئے۔", "OCR nenašlo obrazovou stránku s rozpoznatelným textem. Stránky, které již obsahují text, zůstaly beze změny.", "OCR nenašlo obrazovú stranu s rozpoznateľným textom. Strany, ktoré už obsahujú text, zostali nezmenené.", "OCR nie znalazł strony obrazowej z rozpoznawalnym tekstem. Strony zawierające tekst pozostały bez zmian."),
    "ocr_discarded": ("The OCR result was discarded because the document changed.", "由于文档已更改，OCR 结果被丢弃。", "दस्तावेज़ बदलने के कारण OCR परिणाम छोड़ दिया गया।", "El resultado de OCR se descartó porque el documento cambió.", "Le résultat OCR a été ignoré car le document a changé.", "تم تجاهل نتيجة OCR لأن المستند تغير.", "নথি পরিবর্তিত হওয়ায় OCR ফল বাতিল করা হয়েছে।", "O resultado do OCR foi descartado porque o documento mudou.", "Hasil OCR dibuang karena dokumen berubah.", "دستاویز تبدیل ہونے کی وجہ سے OCR نتیجہ مسترد کر دیا گیا۔", "Výsledek OCR byl zahozen, protože se dokument změnil.", "Výsledok OCR bol zahodený, pretože sa dokument zmenil.", "Wynik OCR odrzucono, ponieważ dokument został zmieniony."),
    "image_updated": ("Image updated. Use Undo to restore its previous position.", "图像已更新。使用撤消恢复原位置。", "छवि अपडेट की गई। पिछली स्थिति लौटाने के लिए पूर्ववत करें।", "Imagen actualizada. Use Deshacer para restaurar su posición anterior.", "Image mise à jour. Utilisez Annuler pour restaurer sa position précédente.", "تم تحديث الصورة. استخدم تراجع لاستعادة موضعها السابق.", "ছবি আপডেট হয়েছে। আগের অবস্থান ফেরাতে পূর্বাবস্থা ব্যবহার করুন।", "Imagem atualizada. Use Desfazer para restaurar a posição anterior.", "Gambar diperbarui. Gunakan Urungkan untuk mengembalikan posisi sebelumnya.", "تصویر اپ ڈیٹ ہو گئی۔ پچھلی جگہ بحال کرنے کے لیے کالعدم کریں۔", "Obrázek byl upraven. Pomocí Zpět obnovíte jeho předchozí polohu.", "Obrázok bol upravený. Pomocou Späť obnovíte jeho predchádzajúcu polohu.", "Obraz został zmieniony. Użyj Cofnij, aby przywrócić poprzednie położenie."),
})


_REGIONAL = {
    "id": {
        "menu_file": "Berkas",
        "menu_edit": "Edit",
        "menu_insert": "Sisipkan",
        "menu_page": "Halaman",
        "menu_image": "Gambar",
        "menu_view": "Tampilan",
        "menu_appearance": "Tema",
        "menu_language": "Bahasa",
        "menu_help": "Bantuan",
        "new_pdf": "PDF Baru...",
        "open": "Buka...",
        "save_as": "Simpan Sebagai...",
        "compress": "Kompres PDF...",
        "exit": "Keluar",
        "undo": "Urungkan",
        "redo": "Ulangi",
        "add_text": "Tambah kotak teks",
        "delete_text": "Hapus teks terpilih",
        "zoom_in": "Perbesar",
        "zoom_out": "Perkecil",
        "fit_width": "Sesuaikan lebar",
        "theme_auto": "Otomatis (sistem)",
        "theme_dark": "Gelap",
        "theme_light": "Terang",
        "add_blank_page": "Tambah halaman kosong",
        "insert_pages": "Sisipkan halaman dari PDF...",
        "delete_page": "Hapus halaman saat ini",
        "insert_image": "Sisipkan gambar...",
        "delete_image": "Hapus gambar",
        "add_signature": "Tambah tanda tangan visual...",
        "about": "Tentang",
        "font": "Font",
        "font_size": "Ukuran font",
        "bold": "Tebal",
        "italic": "Miring",
        "underline": "Garis bawah",
        "text_color": "Warna teks",
        "current_zoom": "Zoom saat ini",
        "create": "Buat",
        "cancel": "Batal",
        "save": "Simpan",
        "discard": "Buang",
        "yes": "Ya",
        "no": "Tidak",
        "new_title": "Buat PDF baru",
        "custom_size": "Ukuran khusus",
        "portrait": "Potret",
        "landscape": "Lanskap",
        "page_size": "Ukuran halaman",
        "orientation": "Orientasi",
        "width": "Lebar",
        "height": "Tinggi",
        "page_count": "Jumlah halaman",
        "result": "Hasil",
        "blank_pdf_intro": "Buat dokumen PDF kosong:",
        "signature_title": "Sisipkan tanda tangan visual",
        "signature_warning": "Ini menyisipkan tanda tangan yang terlihat pada halaman, bukan tanda tangan digital berbasis sertifikat.",
        "draw_signature": "Gambar tanda tangan",
        "type_signature": "Ketik tanda tangan",
        "clear_drawing": "Hapus gambar",
        "draw_hint": "Gambar di dalam kotak menggunakan tetikus atau pena:",
        "your_name": "Nama Anda",
        "signature_text": "Teks tanda tangan",
        "size": "Ukuran",
        "style": "Gaya",
        "width_on_page": "Lebar pada halaman",
        "rotation": "Rotasi",
        "compress_title": "Kompres PDF",
        "lossless": "Optimasi tanpa kehilangan",
        "balanced": "Seimbang - disarankan",
        "strong": "Kuat - berkas terkecil",
        "compression_profile": "Profil kompresi",
        "open_to_begin": "Buka PDF atau buat yang baru untuk memulai",
    },
    "cs": {
        "unsaved_title": "Neuložené změny",
        "unsaved_question": "Uložit změny v souboru {name}, než budete pokračovat?",
        "choose_text_color": "Vybrat barvu textu",
        "add_text_hint": "Tažením vytvořte textové pole, nebo jednou klikněte pro standardní velikost. Esc akci zruší.",
        "type_text_hint": "Napište nový text. Ctrl+Enter dokončí úpravu, Esc ji zruší.",
        "direct_edit_hint": "Upravujte text přímo na stránce. Ctrl+Enter potvrdí, Esc zruší.",
        "text_inserted": "Text byl vložen a zůstává označitelný, přesouvatelný a upravitelný.",
        "text_updated": "Text byl upraven. Předchozí verzi vrátíte pomocí Zpět.",
        "text_cancelled": "Úprava textu byla zrušena.",
        "text_removed": "Text byl odstraněn. Obnovit jej můžete pomocí Zpět.",
        "text_frame_updated": "Textový rámeček byl změněn. Předchozí polohu obnovíte pomocí Zpět.",
        "select_text_hint": "Dvojklikem začnete psát. Tažením rámečku text přesunete, pravým dolním úchytem změníte jeho velikost.",
        "editable_text": "upravitelný text",
        "ocr_required": "stránka je pouze obraz - je vyžadováno OCR",
        "images": "obrázky",
        "signatures": "podpisy",
        "text_boxes": "textové objekty",
        "page_word": "Stránka",
        "untitled": "Bez názvu.pdf",
        "new_created": "Bylo vytvořeno nové PDF: {count} stran, {width:.0f} x {height:.0f} bodů. Uložením zvolíte název souboru.",
        "unable_create_title": "PDF nelze vytvořit",
        "open_pdf_title": "Otevřít PDF",
        "unable_open_title": "PDF nelze otevřít",
        "render_error_title": "Chyba vykreslení",
        "cannot_delete_page": "PDF musí obsahovat alespoň jednu stránku.",
        "delete_page_question": "Odstranit stránku {page}?",
        "invalid_image_format": "Vybraný formát obrázku nelze načíst.",
        "image_width_prompt": "Šířka na stránce (v bodech):",
        "unable_open_image": "Obrázek nelze otevřít",
        "unable_create_signature": "Podpis nelze vytvořit",
        "visual_place_hint": "Klikněte na místo na stránce, kam se má objekt vložit. Esc akci zruší.",
        "unable_place_image": "Obrázek nelze vložit",
        "invalid_image_data": "Data obrázku nejsou platná.",
        "signature_inserted": "Podpis byl vložen. Kliknutím jej můžete přesunout, změnit jeho velikost nebo jej otočit.",
        "image_inserted": "Obrázek byl vložen. Odstranit jej můžete pomocí Zpět.",
        "signature_updated": "Podpis byl upraven. Předchozí polohu obnovíte pomocí Zpět.",
        "signature_select_hint": "Tažením podpis přesunete, dolním úchytem změníte velikost a horním úchytem jej otočíte.",
        "no_image": "Žádný obrázek",
        "no_image_message": "Na této stránce není žádný obrázek ani vizuální podpis.",
        "delete_visual_hint": "Klikněte na obrázek nebo vizuální podpis, který chcete odstranit. Esc akci zruší.",
        "image_removed": "Obrázek byl odstraněn. Obnovit jej můžete pomocí Zpět.",
        "save_pdf_title": "Uložit upravené PDF",
        "pdf_saved": "PDF bylo uloženo",
        "pdf_saved_message": "Upravený dokument byl uložen do:\n{path}",
        "saved_status": "Uloženo: {path}",
        "unable_save": "PDF nelze uložit",
        "save_compressed_title": "Uložit komprimované PDF",
        "compression_failed": "Komprese se nezdařila",
        "compression_complete": "Komprese dokončena",
        "reduction": "Zmenšení: {value:.1f}%",
        "increase": "Zvětšení: {value:.1f}% (zdroj byl již účinně komprimován)",
        "original_working": "Původní pracovní dokument",
        "compressed_copy": "Komprimovaná kopie",
        "recompressed_images": "Znovu komprimované obrázky",
        "about_body": "Nettongia PDF Editor 0.17.0\n\nUpravujte existující text přímo na stránce a přidávejte přesouvatelná textová pole s měnitelnou velikostí. Vytvářejte prázdná PDF, vkládejte nebo odstraňujte obrázky, spravujte stránky, přidávejte otočné vizuální podpisy, měňte vzhled a jazyk rozhraní, zobrazujte náhled, tiskněte dokumenty a ukládejte komprimované kopie.\n\nVybraný původní text a odstraněné obrázky jsou před uložením skutečně odebrány z obsahu stránky.\n\nNeuložená práce je označena hvězdičkou, chráněna dialogem Uložit / Zahodit / Zrušit a průběžně zachycována automatickým obnovením po pádu. Nedávno otevřená PDF jsou dostupná v nabídce Soubor.\n\nVizuální podpisy nejsou digitální podpisy založené na certifikátu. Text v naskenovaných obrázcích stále vyžaduje OCR.",
        "empty_signature": "Prázdný podpis",
        "empty_draw": "Nakreslete podpis nebo přepněte na možnost Napsat podpis.",
        "empty_type": "Zadejte text podpisu.",
        "drawn_signature_desc": "Nakreslený vizuální podpis",
        "typed_signature_desc": "Napsaný vizuální podpis: {text}",
        "lossless_desc": "Optimalizuje objekty a datové proudy PDF bez snížení kvality obrázků.",
        "balanced_desc": "Zmenší příliš velké obrázky přibližně na 150 dpi a použije střední kompresi JPEG.",
        "strong_desc": "Zmenší příliš velké obrázky přibližně na 105 dpi a použije silnější kompresi JPEG.",
        "compression_note": "Ztrátové profily jsou nejúčinnější pro skeny a fotografie. Vektorový text a grafika zůstanou ostré.",
        "about_title": "O aplikaci Nettongia PDF Editor",
        "pdf_filter": "Dokumenty PDF (*.pdf)",
        "image_filter": "Obrázky (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)",
        "pages_count": "Počet stran: {count}",
    },
    "sk": {
        "unsaved_title": "Neuložené zmeny",
        "unsaved_question": "Uložiť zmeny v súbore {name} pred pokračovaním?",
        "choose_text_color": "Vybrať farbu textu",
        "add_text_hint": "Ťahaním vytvorte textové pole alebo raz kliknite pre štandardnú veľkosť. Esc akciu zruší.",
        "type_text_hint": "Napíšte nový text. Ctrl+Enter dokončí úpravu, Esc ju zruší.",
        "direct_edit_hint": "Upravujte text priamo na strane. Ctrl+Enter potvrdí, Esc zruší.",
        "text_inserted": "Text bol vložený a zostáva označiteľný, presúvateľný a upraviteľný.",
        "text_updated": "Text bol upravený. Predchádzajúcu verziu obnovíte pomocou Späť.",
        "text_cancelled": "Úprava textu bola zrušená.",
        "text_removed": "Text bol odstránený. Obnovíte ho pomocou Späť.",
        "text_frame_updated": "Textový rámček bol zmenený. Predchádzajúcu polohu obnovíte pomocou Späť.",
        "select_text_hint": "Dvojklikom začnete písať. Ťahaním rámčeka text presuniete, pravým dolným úchytom zmeníte veľkosť.",
        "editable_text": "upraviteľný text",
        "ocr_required": "strana je iba obraz - vyžaduje sa OCR",
        "images": "obrázky",
        "signatures": "podpisy",
        "text_boxes": "textové objekty",
        "page_word": "Strana",
        "untitled": "Bez názvu.pdf",
        "new_created": "Bolo vytvorené nové PDF: {count} strán, {width:.0f} x {height:.0f} bodov. Uložením vyberiete názov súboru.",
        "unable_create_title": "PDF sa nedá vytvoriť",
        "open_pdf_title": "Otvoriť PDF",
        "unable_open_title": "PDF sa nedá otvoriť",
        "render_error_title": "Chyba vykresľovania",
        "cannot_delete_page": "PDF musí obsahovať aspoň jednu stranu.",
        "delete_page_question": "Odstrániť stranu {page}?",
        "invalid_image_format": "Vybraný formát obrázka sa nedá načítať.",
        "image_width_prompt": "Šírka na strane (v bodoch):",
        "unable_open_image": "Obrázok sa nedá otvoriť",
        "unable_create_signature": "Podpis sa nedá vytvoriť",
        "visual_place_hint": "Kliknite na miesto na strane, kam sa má objekt vložiť. Esc akciu zruší.",
        "unable_place_image": "Obrázok sa nedá vložiť",
        "invalid_image_data": "Údaje obrázka nie sú platné.",
        "signature_inserted": "Podpis bol vložený. Kliknutím ho môžete presunúť, zmeniť jeho veľkosť alebo ho otočiť.",
        "image_inserted": "Obrázok bol vložený. Odstránite ho pomocou Späť.",
        "signature_updated": "Podpis bol upravený. Predchádzajúcu polohu obnovíte pomocou Späť.",
        "signature_select_hint": "Ťahaním podpis presuniete, dolným úchytom zmeníte veľkosť a horným úchytom ho otočíte.",
        "no_image": "Žiadny obrázok",
        "no_image_message": "Na tejto strane nie je žiadny obrázok ani vizuálny podpis.",
        "delete_visual_hint": "Kliknite na obrázok alebo vizuálny podpis, ktorý chcete odstrániť. Esc akciu zruší.",
        "image_removed": "Obrázok bol odstránený. Obnovíte ho pomocou Späť.",
        "save_pdf_title": "Uložiť upravené PDF",
        "pdf_saved": "PDF bolo uložené",
        "pdf_saved_message": "Upravený dokument bol uložený do:\n{path}",
        "saved_status": "Uložené: {path}",
        "unable_save": "PDF sa nedá uložiť",
        "save_compressed_title": "Uložiť komprimované PDF",
        "compression_failed": "Kompresia zlyhala",
        "compression_complete": "Kompresia dokončená",
        "reduction": "Zmenšenie: {value:.1f}%",
        "increase": "Zväčšenie: {value:.1f}% (zdroj už bol účinne komprimovaný)",
        "original_working": "Pôvodný pracovný dokument",
        "compressed_copy": "Komprimovaná kópia",
        "recompressed_images": "Znova komprimované obrázky",
        "empty_signature": "Prázdny podpis",
        "empty_draw": "Nakreslite podpis alebo prepnite na možnosť Napísať podpis.",
        "empty_type": "Zadajte text podpisu.",
        "drawn_signature_desc": "Nakreslený vizuálny podpis",
        "typed_signature_desc": "Napísaný vizuálny podpis: {text}",
        "lossless_desc": "Optimalizuje objekty a dátové prúdy PDF bez zníženia kvality obrázkov.",
        "balanced_desc": "Zmenší príliš veľké obrázky približne na 150 dpi a použije strednú kompresiu JPEG.",
        "strong_desc": "Zmenší príliš veľké obrázky približne na 105 dpi a použije silnejšiu kompresiu JPEG.",
        "compression_note": "Stratové profily sú najúčinnejšie pre skeny a fotografie. Vektorový text a grafika zostanú ostré.",
        "about_title": "O aplikácii Nettongia PDF Editor",
        "about_body": "Nettongia PDF Editor 0.17.0\n\nUpravujte existujúci text priamo na strane a pridávajte presúvateľné textové polia s meniteľnou veľkosťou. Vytvárajte prázdne PDF, vkladajte alebo odstraňujte obrázky, spravujte strany, pridávajte otočné vizuálne podpisy, meňte vzhľad a jazyk rozhrania, zobrazujte náhľad, tlačte dokumenty a ukladajte komprimované kópie.\n\nVybraný pôvodný text a odstránené obrázky sa pred uložením skutočne odstránia z obsahu strany.\n\nNeuložená práca je označená hviezdičkou, chránená dialógom Uložiť / Zahodiť / Zrušiť a priebežne zachytávaná automatickým obnovením po páde. Nedávno otvorené PDF sú dostupné v ponuke Súbor.\n\nVizuálne podpisy nie sú digitálne podpisy založené na certifikáte. Text v naskenovaných obrázkoch stále vyžaduje OCR.",
        "pdf_filter": "Dokumenty PDF (*.pdf)",
        "image_filter": "Obrázky (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)",
        "pages_count": "Počet strán: {count}",
    },
    "pl": {
        "unsaved_title": "Niezapisane zmiany",
        "unsaved_question": "Zapisać zmiany w pliku {name} przed kontynuowaniem?",
        "choose_text_color": "Wybierz kolor tekstu",
        "add_text_hint": "Przeciągnij, aby utworzyć pole tekstowe, lub kliknij raz, aby użyć standardowego rozmiaru. Esc anuluje.",
        "type_text_hint": "Wpisz nowy tekst. Ctrl+Enter kończy edycję, Esc anuluje.",
        "direct_edit_hint": "Edytuj bezpośrednio na stronie. Ctrl+Enter zatwierdza, Esc anuluje.",
        "text_inserted": "Tekst wstawiono; nadal można go zaznaczać, przenosić i edytować.",
        "text_updated": "Tekst zaktualizowano. Użyj Cofnij, aby przywrócić poprzednią wersję.",
        "text_cancelled": "Edycję tekstu anulowano.",
        "text_removed": "Tekst usunięto. Użyj Cofnij, aby go przywrócić.",
        "text_frame_updated": "Ramkę tekstową zmieniono. Użyj Cofnij, aby przywrócić poprzednią geometrię.",
        "select_text_hint": "Kliknij dwukrotnie, aby pisać. Przeciągnij ramkę, aby przenieść tekst, a prawy dolny uchwyt, aby zmienić rozmiar.",
        "editable_text": "edytowalny tekst",
        "ocr_required": "strona jest tylko obrazem - wymagane OCR",
        "images": "obrazy",
        "signatures": "podpisy",
        "text_boxes": "obiekty tekstowe",
        "page_word": "Strona",
        "untitled": "Bez nazwy.pdf",
        "new_created": "Utworzono nowy PDF: {count} stron, {width:.0f} x {height:.0f} punktów. Zapisz go, aby wybrać nazwę pliku.",
        "unable_create_title": "Nie można utworzyć PDF",
        "open_pdf_title": "Otwórz PDF",
        "unable_open_title": "Nie można otworzyć PDF",
        "render_error_title": "Błąd renderowania",
        "cannot_delete_page": "PDF musi zawierać co najmniej jedną stronę.",
        "delete_page_question": "Usunąć stronę {page}?",
        "invalid_image_format": "Nie można odczytać wybranego formatu obrazu.",
        "image_width_prompt": "Szerokość na stronie (w punktach):",
        "unable_open_image": "Nie można otworzyć obrazu",
        "unable_create_signature": "Nie można utworzyć podpisu",
        "visual_place_hint": "Kliknij miejsce na stronie, w którym ma zostać umieszczony obiekt. Esc anuluje.",
        "unable_place_image": "Nie można wstawić obrazu",
        "invalid_image_data": "Dane obrazu są nieprawidłowe.",
        "signature_inserted": "Podpis wstawiono. Kliknij go, aby przesunąć, zmienić rozmiar lub obrócić.",
        "image_inserted": "Obraz wstawiono. Użyj Cofnij, aby go usunąć.",
        "signature_updated": "Podpis zaktualizowano. Użyj Cofnij, aby przywrócić poprzednie położenie.",
        "signature_select_hint": "Przeciągnij podpis, aby go przenieść; użyj dolnego uchwytu do zmiany rozmiaru i górnego do obrotu.",
        "no_image": "Brak obrazu",
        "no_image_message": "Na tej stronie nie ma obrazu ani podpisu wizualnego.",
        "delete_visual_hint": "Kliknij obraz lub podpis wizualny, który chcesz usunąć. Esc anuluje.",
        "image_removed": "Obraz usunięto. Użyj Cofnij, aby go przywrócić.",
        "save_pdf_title": "Zapisz zmodyfikowany PDF",
        "pdf_saved": "PDF zapisano",
        "pdf_saved_message": "Zmodyfikowany dokument zapisano w:\n{path}",
        "saved_status": "Zapisano: {path}",
        "unable_save": "Nie można zapisać PDF",
        "save_compressed_title": "Zapisz skompresowany PDF",
        "compression_failed": "Kompresja nie powiodła się",
        "compression_complete": "Kompresja zakończona",
        "reduction": "Zmniejszenie: {value:.1f}%",
        "increase": "Zwiększenie: {value:.1f}% (źródło było już skutecznie skompresowane)",
        "original_working": "Oryginalny dokument roboczy",
        "compressed_copy": "Skompresowana kopia",
        "recompressed_images": "Ponownie skompresowane obrazy",
        "empty_signature": "Pusty podpis",
        "empty_draw": "Narysuj podpis lub przełącz na opcję Wpisz podpis.",
        "empty_type": "Wprowadź tekst podpisu.",
        "drawn_signature_desc": "Narysowany podpis wizualny",
        "typed_signature_desc": "Wpisany podpis wizualny: {text}",
        "lossless_desc": "Optymalizuje obiekty i strumienie PDF bez obniżania jakości obrazów.",
        "balanced_desc": "Zmniejsza zbyt duże obrazy do około 150 dpi i stosuje średnią kompresję JPEG.",
        "strong_desc": "Zmniejsza zbyt duże obrazy do około 105 dpi i stosuje silniejszą kompresję JPEG.",
        "compression_note": "Profile stratne są najskuteczniejsze dla skanów i fotografii. Tekst wektorowy i grafika pozostają ostre.",
        "about_title": "O aplikacji Nettongia PDF Editor",
        "about_body": "Nettongia PDF Editor 0.17.0\n\nEdytuj istniejący tekst bezpośrednio na stronie i dodawaj przenośne pola tekstowe o zmiennym rozmiarze. Twórz puste pliki PDF, wstawiaj lub usuwaj obrazy, zarządzaj stronami, dodawaj obracane podpisy wizualne, zmieniaj wygląd i język interfejsu, wyświetlaj podgląd, drukuj dokumenty oraz zapisuj skompresowane kopie.\n\nWybrany tekst źródłowy i usunięte obrazy są rzeczywiście usuwane z zawartości strony przed zapisem.\n\nNiezapisana praca jest oznaczona gwiazdką, chroniona oknem Zapisz / Odrzuć / Anuluj i zapisywana przez automatyczne odzyskiwanie po awarii. Ostatnio otwarte pliki PDF są dostępne w menu Plik.\n\nPodpisy wizualne nie są podpisami cyfrowymi opartymi na certifikacie. Tekst w zeskanowanych obrazach nadal wymaga OCR.",
        "pdf_filter": "Dokumenty PDF (*.pdf)",
        "image_filter": "Obrazy (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)",
        "pages_count": "Liczba stron: {count}",
    },
}


_ROWS.update({
    "document_compatibility": ("Document compatibility...", "文档兼容性...", "दस्तावेज़ संगतता...", "Compatibilidad del documento...", "Compatibilité du document...", "توافق المستند...", "নথির সামঞ্জস্য...", "Compatibilidade do documento...", "Kompatibilitas dokumen...", "دستاویز کی مطابقت...", "Kompatibilita dokumentu...", "Kompatibilita dokumentu...", "Zgodność dokumentu..."),
    "compatibility_checking": ("Checking document compatibility in an isolated process...", "正在独立进程中检查文档兼容性...", "अलग प्रक्रिया में दस्तावेज़ संगतता जाँची जा रही है...", "Comprobando la compatibilidad en un proceso aislado...", "Vérification de la compatibilité dans un processus isolé...", "جارٍ فحص التوافق في عملية معزولة...", "আলাদা প্রক্রিয়ায় সামঞ্জস্য পরীক্ষা করা হচ্ছে...", "A verificar a compatibilidade num processo isolado...", "Memeriksa kompatibilitas dalam proses terisolasi...", "الگ عمل میں مطابقت کی جانچ جاری ہے...", "Kontroluji kompatibilitu dokumentu v izolovaném procesu...", "Kontroluje sa kompatibilita dokumentu v izolovanom procese...", "Sprawdzanie zgodności dokumentu w odizolowanym procesie..."),
    "compatibility_ok": ("No risky PDF features were detected.", "未检测到有风险的 PDF 功能。", "कोई जोखिमपूर्ण PDF सुविधा नहीं मिली।", "No se detectaron funciones PDF de riesgo.", "Aucune fonction PDF à risque n’a été détectée.", "لم يتم اكتشاف ميزات PDF خطرة.", "ঝুঁকিপূর্ণ PDF বৈশিষ্ট্য পাওয়া যায়নি।", "Não foram detetadas funcionalidades PDF de risco.", "Tidak ada fitur PDF berisiko yang terdeteksi.", "کوئی خطرناک PDF خصوصیت نہیں ملی۔", "Nebyly zjištěny žádné rizikové vlastnosti PDF.", "Nezistili sa žiadne rizikové vlastnosti PDF.", "Nie wykryto ryzykownych funkcji PDF."),
    "compatibility_warnings": ("Compatibility check found {count} item(s) to review.", "兼容性检查发现 {count} 个需要检查的项目。", "संगतता जाँच में समीक्षा हेतु {count} मद मिलीं।", "La comprobación encontró {count} elemento(s) para revisar.", "Le contrôle a trouvé {count} élément(s) à examiner.", "وجد الفحص {count} عنصرًا للمراجعة.", "পর্যালোচনার জন্য {count}টি বিষয় পাওয়া গেছে।", "A verificação encontrou {count} item(ns) para rever.", "Pemeriksaan menemukan {count} item untuk ditinjau.", "جانچ میں جائزے کے لیے {count} آئٹم ملے۔", "Kontrola našla {count} položek k prověření.", "Kontrola našla {count} položiek na preverenie.", "Kontrola wykryła {count} elementów do sprawdzenia."),
    "compatibility_failed": ("The isolated compatibility check failed: {error}", "独立兼容性检查失败：{error}", "अलग संगतता जाँच विफल रही: {error}", "Falló la comprobación aislada: {error}", "Le contrôle isolé a échoué : {error}", "فشل فحص التوافق المعزول: {error}", "আলাদা সামঞ্জস্য পরীক্ষা ব্যর্থ হয়েছে: {error}", "A verificação isolada falhou: {error}", "Pemeriksaan terisolasi gagal: {error}", "الگ مطابقتی جانچ ناکام ہوئی: {error}", "Izolovaná kontrola kompatibility selhala: {error}", "Izolovaná kontrola kompatibility zlyhala: {error}", "Odizolowana kontrola zgodności nie powiodła się: {error}"),
    "compatibility_signature_risk": ("Editing and saving will invalidate existing digital signatures.", "编辑并保存将使现有数字签名失效。", "संपादन और सहेजने से मौजूदा डिजिटल हस्ताक्षर अमान्य हो जाएंगे।", "Editar y guardar invalidará las firmas digitales existentes.", "La modification et l’enregistrement invalideront les signatures numériques existantes.", "سيؤدي التحرير والحفظ إلى إبطال التوقيعات الرقمية الحالية.", "সম্পাদনা ও সংরক্ষণে বিদ্যমান ডিজিটাল স্বাক্ষর অকার্যকর হবে।", "Editar e guardar invalidará as assinaturas digitais existentes.", "Mengedit dan menyimpan akan membatalkan tanda tangan digital yang ada.", "ترمیم اور محفوظ کرنے سے موجودہ ڈیجیٹل دستخط منسوخ ہو جائیں گے۔", "Úprava a uložení zneplatní existující digitální podpisy.", "Úprava a uloženie zneplatnia existujúce digitálne podpisy.", "Edycja i zapis unieważnią istniejące podpisy cyfrowe."),
    "compatibility_features": ("Features to review: {features}", "需要检查的功能：{features}", "समीक्षा योग्य सुविधाएँ: {features}", "Funciones para revisar: {features}", "Fonctions à examiner : {features}", "الميزات المطلوب مراجعتها: {features}", "পর্যালোচনার বৈশিষ্ট্য: {features}", "Funcionalidades a rever: {features}", "Fitur untuk ditinjau: {features}", "جائزے کی خصوصیات: {features}", "Vlastnosti k prověření: {features}", "Vlastnosti na preverenie: {features}", "Funkcje do sprawdzenia: {features}"),
    "compatibility_level_safe": ("Safe", "安全", "सुरक्षित", "Seguro", "Sûr", "آمن", "নিরাপদ", "Seguro", "Aman", "محفوظ", "Bezpečné", "Bezpečné", "Bezpieczny"),
    "compatibility_level_possible_changes": ("Possible changes", "可能发生变化", "संभावित बदलाव", "Posibles cambios", "Modifications possibles", "تغييرات محتملة", "সম্ভাব্য পরিবর্তন", "Possíveis alterações", "Kemungkinan perubahan", "ممکنہ تبدیلیاں", "Možné změny", "Možné zmeny", "Możliwe zmiany"),
    "compatibility_level_high_risk": ("High risk", "高风险", "उच्च जोखिम", "Riesgo alto", "Risque élevé", "مخاطر عالية", "উচ্চ ঝুঁকি", "Risco elevado", "Risiko tinggi", "زیادہ خطرہ", "Vysoké riziko", "Vysoké riziko", "Wysokie ryzyko"),
    "representative_render_ok": ("Representative pages rendered safely: {count}", "安全渲染的代表性页面：{count}", "सुरक्षित रूप से रेंडर किए गए प्रतिनिधि पृष्ठ: {count}", "Páginas representativas renderizadas con seguridad: {count}", "Pages représentatives rendues en sécurité : {count}", "الصفحات النموذجية التي تم عرضها بأمان: {count}", "নিরাপদে রেন্ডার করা নমুনা পৃষ্ঠা: {count}", "Páginas representativas renderizadas em segurança: {count}", "Halaman perwakilan dirender dengan aman: {count}", "محفوظ طریقے سے رینڈر کیے گئے نمائندہ صفحات: {count}", "Bezpečně vykreslené reprezentativní stránky: {count}", "Bezpečne vykreslené reprezentatívne strany: {count}", "Bezpiecznie wyrenderowane strony reprezentatywne: {count}"),
})

_ROWS.update({
    "export_diagnostics": ("Export anonymized diagnostics...", "导出匿名诊断信息...", "अनाम निदान निर्यात करें...", "Exportar diagnóstico anónimo...", "Exporter les diagnostics anonymisés...", "تصدير بيانات التشخيص المجهّلة...", "বেনামী ডায়াগনস্টিক রপ্তানি করুন...", "Exportar diagnóstico anonimizado...", "Ekspor diagnostik anonim...", "گمنام تشخیصی معلومات برآمد کریں...", "Exportovat anonymizovanou diagnostiku...", "Exportovať anonymizovanú diagnostiku...", "Eksportuj anonimową diagnostykę..."),
    "diagnostics_title": ("Anonymized diagnostics", "匿名诊断信息", "अनाम निदान", "Diagnóstico anónimo", "Diagnostics anonymisés", "بيانات تشخيص مجهّلة", "বেনামী ডায়াগনস্টিক", "Diagnóstico anonimizado", "Diagnostik anonim", "گمنام تشخیصی معلومات", "Anonymizovaná diagnostika", "Anonymizovaná diagnostika", "Anonimowa diagnostyka"),
    "diagnostics_filter": ("ZIP archives (*.zip)", "ZIP 压缩包 (*.zip)", "ZIP संग्रह (*.zip)", "Archivos ZIP (*.zip)", "Archives ZIP (*.zip)", "أرشيفات ZIP (*.zip)", "ZIP আর্কাইভ (*.zip)", "Arquivos ZIP (*.zip)", "Arsip ZIP (*.zip)", "ZIP آرکائیوز (*.zip)", "Archivy ZIP (*.zip)", "Archívy ZIP (*.zip)", "Archiwa ZIP (*.zip)"),
    "diagnostics_saved": ("Anonymized diagnostics saved ({records} operation records):\n{path}", "匿名诊断信息已保存（{records} 条操作记录）：\n{path}", "अनाम निदान सहेजा गया ({records} संचालन रिकॉर्ड):\n{path}", "Diagnóstico anónimo guardado ({records} registros de operaciones):\n{path}", "Diagnostics anonymisés enregistrés ({records} opérations) :\n{path}", "تم حفظ بيانات التشخيص المجهّلة ({records} سجل عمليات):\n{path}", "বেনামী ডায়াগনস্টিক সংরক্ষিত হয়েছে ({records}টি অপারেশন রেকর্ড):\n{path}", "Diagnóstico anonimizado guardado ({records} registos de operações):\n{path}", "Diagnostik anonim disimpan ({records} catatan operasi):\n{path}", "گمنام تشخیصی معلومات محفوظ ہو گئیں ({records} عملی ریکارڈ):\n{path}", "Anonymizovaná diagnostika byla uložena ({records} záznamů operací):\n{path}", "Anonymizovaná diagnostika bola uložená ({records} záznamov operácií):\n{path}", "Zapisano anonimową diagnostykę ({records} rekordów operacji):\n{path}"),
    "diagnostics_failed": ("Unable to create diagnostics: {error}", "无法创建诊断信息：{error}", "निदान नहीं बनाया जा सका: {error}", "No se pudo crear el diagnóstico: {error}", "Impossible de créer les diagnostics : {error}", "تعذر إنشاء بيانات التشخيص: {error}", "ডায়াগনস্টিক তৈরি করা যায়নি: {error}", "Não foi possível criar o diagnóstico: {error}", "Tidak dapat membuat diagnostik: {error}", "تشخیصی معلومات نہیں بن سکیں: {error}", "Diagnostiku nelze vytvořit: {error}", "Diagnostiku sa nepodarilo vytvoriť: {error}", "Nie można utworzyć diagnostyki: {error}"),
    "diagnostics_review": (
        "Before export, review the complete contents.\n\nIncluded:\n• bundle generation time and application/diagnostics versions\n• frozen-build flag, operating-system family, release and architecture\n• Python, Qt, PySide6 and PyMuPDF versions\n• interface language and appearance mode\n• page count, current page and coarse PDF size bucket\n• unsaved-state flag and counts of pending objects\n• tile-cache counters\n• bounded operation timestamps, random per-start session IDs, names and outcomes\n• presence of current/previous crash logs and their coarse size\n\nExcluded:\n• PDF files and rendered pages\n• document text, images, annotations and metadata\n• file names, folder paths and recent-file history\n• user name, computer name, IP and hardware identifiers\n• raw exception messages and raw crash-log contents\n\nCreate the ZIP?",
        "导出前请检查完整内容。\n\n包含：\n• 应用程序和诊断格式版本\n• 操作系统系列、版本和体系结构\n• Python、Qt、PySide6 和 PyMuPDF 版本\n• 界面语言和外观模式\n• 页数、当前页和粗略 PDF 大小范围\n• 未保存状态和待处理对象数量\n• 图块缓存计数器\n• 有界的操作名称、时间戳和结果类别\n• 本地崩溃日志是否存在及其粗略大小\n\n不包含：\n• PDF 文件和渲染页面\n• 文档文本、图像、注释和元数据\n• 文件名、文件夹路径和最近文件历史\n• 用户名、计算机名、IP 和硬件标识符\n• 原始异常消息和崩溃日志内容\n\n创建 ZIP？",
        "निर्यात से पहले पूरी सामग्री देखें।\n\nशामिल:\n• ऐप और निदान संस्करण\n• ऑपरेटिंग सिस्टम परिवार, रिलीज़ और आर्किटेक्चर\n• Python, Qt, PySide6 और PyMuPDF संस्करण\n• इंटरफ़ेस भाषा और रूप\n• पृष्ठ संख्या, वर्तमान पृष्ठ और मोटा PDF आकार वर्ग\n• बिना सहेजे स्थिति और लंबित वस्तुओं की गिनती\n• टाइल-कैश काउंटर\n• सीमित ऑपरेशन नाम, समय और परिणाम श्रेणियाँ\n• स्थानीय क्रैश लॉग की मौजूदगी और मोटा आकार\n\nशामिल नहीं:\n• PDF और रेंडर किए पृष्ठ\n• दस्तावेज़ पाठ, चित्र, टिप्पणियाँ और मेटाडेटा\n• फ़ाइल नाम, पथ और हाल की फ़ाइलें\n• उपयोगकर्ता/कंप्यूटर नाम, IP और हार्डवेयर पहचान\n• मूल त्रुटि संदेश और क्रैश लॉग सामग्री\n\nZIP बनाएँ?",
        "Revise el contenido completo antes de exportar.\n\nIncluye:\n• versiones de la aplicación y del diagnóstico\n• familia, versión y arquitectura del sistema operativo\n• versiones de Python, Qt, PySide6 y PyMuPDF\n• idioma y modo de apariencia\n• número de páginas, página actual y rango aproximado del tamaño del PDF\n• estado sin guardar y cantidades de objetos pendientes\n• contadores de caché de mosaicos\n• nombres de operaciones, marcas de tiempo y resultados limitados\n• presencia y tamaño aproximado del registro de fallos\n\nExcluye:\n• PDF y páginas renderizadas\n• texto, imágenes, anotaciones y metadatos del documento\n• nombres, rutas e historial de archivos recientes\n• nombre de usuario/equipo, IP e identificadores de hardware\n• mensajes de error y contenido bruto del registro de fallos\n\n¿Crear el ZIP?",
        "Vérifiez le contenu complet avant l’export.\n\nInclus :\n• versions de l’application et du diagnostic\n• famille, version et architecture du système\n• versions de Python, Qt, PySide6 et PyMuPDF\n• langue et mode d’apparence\n• nombre de pages, page actuelle et classe de taille approximative du PDF\n• état non enregistré et nombres d’objets en attente\n• compteurs du cache de tuiles\n• noms d’opérations, horodatages et catégories de résultat limités\n• présence et taille approximative du journal de plantage\n\nExclus :\n• PDF et pages rendues\n• texte, images, annotations et métadonnées du document\n• noms, chemins et historique des fichiers récents\n• nom d’utilisateur/ordinateur, IP et identifiants matériels\n• messages d’erreur et contenu brut du journal de plantage\n\nCréer le ZIP ?",
        "راجع المحتوى الكامل قبل التصدير.\n\nيتضمن: إصدارات التطبيق والتشخيص، ونظام التشغيل وبنيته، وإصدارات Python وQt وPySide6 وPyMuPDF، ولغة الواجهة ومظهرها، وعدد الصفحات والصفحة الحالية وفئة حجم PDF التقريبية، وحالة الحفظ وأعداد العناصر، وعدادات التخزين المؤقت، وأسماء العمليات وأوقاتها ونتائجها المحدودة، ووجود سجل تعطل وحجمه التقريبي.\n\nلا يتضمن: ملفات PDF أو الصفحات المعروضة، أو نص المستند وصوره وتعليقاته وبياناته الوصفية، أو أسماء الملفات ومساراتها وسجل الملفات الحديثة، أو اسم المستخدم والحاسوب وIP ومعرّفات العتاد، أو رسائل الأخطاء ومحتوى سجل التعطل الخام.\n\nهل تريد إنشاء ZIP؟",
        "রপ্তানির আগে সম্পূর্ণ বিষয়বস্তু পর্যালোচনা করুন।\n\nঅন্তর্ভুক্ত: অ্যাপ/ডায়াগনস্টিক সংস্করণ, OS পরিবার/রিলিজ/আর্কিটেকচার, Python/Qt/PySide6/PyMuPDF সংস্করণ, ভাষা/থিম, পৃষ্ঠা সংখ্যা/বর্তমান পৃষ্ঠা/আনুমানিক PDF আকার, অসংরক্ষিত অবস্থা ও অবজেক্ট সংখ্যা, টাইল ক্যাশ কাউন্টার, সীমিত অপারেশন/সময়/ফলাফল এবং ক্র্যাশ লগের উপস্থিতি/আনুমানিক আকার।\n\nবাদ: PDF/রেন্ডার করা পৃষ্ঠা, নথির পাঠ/ছবি/টীকা/মেটাডেটা, ফাইলের নাম/পথ/সাম্প্রতিক ইতিহাস, ব্যবহারকারী/কম্পিউটার নাম/IP/হার্ডওয়্যার আইডি এবং মূল ত্রুটি বা ক্র্যাশ লগ।\n\nZIP তৈরি করবেন?",
        "Reveja todo o conteúdo antes de exportar.\n\nInclui: versões da aplicação/diagnóstico, sistema operativo e arquitetura, versões de Python/Qt/PySide6/PyMuPDF, idioma/tema, número de páginas/página atual/faixa aproximada do tamanho do PDF, estado não guardado e contagens de objetos, contadores de cache, operações/horas/resultados limitados e presença/tamanho aproximado do registo de falhas.\n\nExclui: PDF/páginas renderizadas, texto/imagens/anotações/metadados, nomes/caminhos/histórico de ficheiros, utilizador/computador/IP/identificadores de hardware e erros ou registo de falhas em bruto.\n\nCriar o ZIP?",
        "Tinjau seluruh isi sebelum ekspor.\n\nDisertakan: versi aplikasi/diagnostik, keluarga/rilis/arsitektur OS, versi Python/Qt/PySide6/PyMuPDF, bahasa/tema, jumlah dan halaman aktif serta kelompok ukuran PDF, status belum tersimpan dan jumlah objek, penghitung cache, operasi/waktu/hasil terbatas, serta keberadaan dan perkiraan ukuran log crash.\n\nTidak disertakan: PDF/halaman render, teks/gambar/anotasi/metadata, nama/jalur/riwayat file, nama pengguna/komputer/IP/ID perangkat keras, dan pesan kesalahan atau isi mentah log crash.\n\nBuat ZIP?",
        "برآمد سے پہلے مکمل مواد دیکھیں۔\n\nشامل: ایپ/تشخیص کے ورژن، OS خاندان/ریلیز/معماری، Python/Qt/PySide6/PyMuPDF ورژن، زبان/تھیم، صفحات/موجودہ صفحہ/PDF حجم کی عمومی درجہ بندی، غیر محفوظ حالت اور آبجیکٹ شمار، کیش کاؤنٹر، محدود آپریشن/وقت/نتیجہ، اور کریش لاگ کی موجودگی/عمومی حجم۔\n\nشامل نہیں: PDF/رینڈر شدہ صفحات، متن/تصاویر/تشریحات/میٹاڈیٹا، فائل نام/راستے/حالیہ تاریخ، صارف/کمپیوٹر نام/IP/ہارڈویئر شناخت، اور اصل خامیاں یا کریش لاگ مواد۔\n\nZIP بنائیں؟",
        "Před exportem zkontrolujte úplný obsah.\n\nZahrnuto:\n• čas vytvoření balíčku a verze aplikace/diagnostického formátu\n• příznak sestaveného EXE, rodina, vydání a architektura systému\n• verze Pythonu, Qt, PySide6 a PyMuPDF\n• jazyk rozhraní a režim vzhledu\n• počet stran, aktuální strana a hrubá kategorie velikosti PDF\n• příznak neuložených změn a počty rozpracovaných objektů\n• čítače mezipaměti dlaždic\n• omezené časy operací, náhodné ID relace pro každé spuštění, názvy a výsledky\n• existence aktuálního/předchozího protokolu pádu a hrubá velikost\n\nNezahrnuto:\n• PDF a vykreslené stránky\n• text, obrázky, anotace a metadata dokumentu\n• názvy souborů, cesty a historie posledních souborů\n• jméno uživatele/počítače, IP a identifikátory hardwaru\n• původní chybové zprávy a obsah protokolu pádu\n\nVytvořit ZIP?",
        "Pred exportom skontrolujte úplný obsah.\n\nZahrnuté: verzie aplikácie/diagnostiky, systém a architektúra, verzie Python/Qt/PySide6/PyMuPDF, jazyk/vzhľad, počet a aktuálna strana/hrubá veľkosť PDF, stav uloženia a počty objektov, čítače cache, obmedzené operácie/časy/výsledky a existencia/hrubá veľkosť záznamu pádu.\n\nNezahrnuté: PDF/vykreslené strany, text/obrázky/anotácie/metadáta, názvy/cesty/história súborov, používateľ/počítač/IP/hardvérové identifikátory a surové chyby alebo obsah záznamu pádu.\n\nVytvoriť ZIP?",
        "Przed eksportem sprawdź pełną zawartość.\n\nZawiera: wersje aplikacji/diagnostyki, system i architekturę, wersje Python/Qt/PySide6/PyMuPDF, język/motyw, liczbę i bieżącą stronę/przybliżony rozmiar PDF, stan zapisu i liczby obiektów, liczniki pamięci podręcznej, ograniczone operacje/czasy/wyniki oraz obecność/przybliżony rozmiar dziennika awarii.\n\nNie zawiera: PDF/renderowanych stron, tekstu/obrazów/adnotacji/metadanych, nazw/ścieżek/historii plików, nazwy użytkownika/komputera/IP/identyfikatorów sprzętu ani surowych błędów lub treści dziennika awarii.\n\nUtworzyć ZIP?"
    ),
})


_ROWS.update({
    "comments": ("Comments", "注释", "टिप्पणियाँ", "Comentarios", "Commentaires", "التعليقات", "মন্তব্য", "Comentários", "Komentar", "تبصرے", "Komentáře", "Komentáre", "Komentarze"),
    "add_comment": ("Add comment...", "添加注释...", "टिप्पणी जोड़ें...", "Añadir comentario...", "Ajouter un commentaire...", "إضافة تعليق...", "মন্তব্য যোগ করুন...", "Adicionar comentário...", "Tambah komentar...", "تبصرہ شامل کریں...", "Přidat komentář...", "Pridať komentár...", "Dodaj komentarz..."),
    "edit_comment": ("Edit selected comment...", "编辑所选注释...", "चुनी हुई टिप्पणी संपादित करें...", "Editar comentario seleccionado...", "Modifier le commentaire sélectionné...", "تعديل التعليق المحدد...", "নির্বাচিত মন্তব্য সম্পাদনা করুন...", "Editar comentário selecionado...", "Edit komentar terpilih...", "منتخب تبصرہ میں ترمیم کریں...", "Upravit vybraný komentář...", "Upraviť vybraný komentár...", "Edytuj wybrany komentarz..."),
    "delete_annotation": ("Delete selected annotation", "删除所选批注", "चुना हुआ एनोटेशन हटाएँ", "Eliminar anotación seleccionada", "Supprimer l’annotation sélectionnée", "حذف التعليق التوضيحي المحدد", "নির্বাচিত টীকা মুছুন", "Eliminar anotação selecionada", "Hapus anotasi terpilih", "منتخب تشریح حذف کریں", "Odstranit vybranou anotaci", "Odstrániť vybranú anotáciu", "Usuń wybraną adnotację"),
    "highlight_text": ("Highlight text", "突出显示文本", "पाठ हाइलाइट करें", "Resaltar texto", "Surligner le texte", "تمييز النص", "পাঠ হাইলাইট করুন", "Realçar texto", "Sorot teks", "متن نمایاں کریں", "Zvýraznit text", "Zvýrazniť text", "Wyróżnij tekst"),
    "comment_place_hint": ("Click the page where the comment icon should be placed. Press Esc to cancel.", "单击页面以放置注释图标。按 Esc 取消。", "पृष्ठ पर वहाँ क्लिक करें जहाँ टिप्पणी चिह्न रखना है। रद्द करने के लिए Esc दबाएँ।", "Haga clic en la página donde desea colocar el icono del comentario. Pulse Esc para cancelar.", "Cliquez sur la page où placer l’icône du commentaire. Appuyez sur Échap pour annuler.", "انقر على الصفحة حيث تريد وضع رمز التعليق. اضغط Esc للإلغاء.", "মন্তব্য আইকন যেখানে রাখতে চান সেখানে পৃষ্ঠায় ক্লিক করুন। বাতিল করতে Esc চাপুন।", "Clique na página onde pretende colocar o ícone do comentário. Prima Esc para cancelar.", "Klik halaman tempat ikon komentar akan diletakkan. Tekan Esc untuk batal.", "صفحے پر وہاں کلک کریں جہاں تبصرے کا نشان رکھنا ہے۔ منسوخ کرنے کے لیے Esc دبائیں۔", "Klikněte na stránku, kam chcete umístit ikonu komentáře. Klávesou Esc akci zrušíte.", "Kliknite na stranu, kam chcete umiestniť ikonu komentára. Klávesom Esc akciu zrušíte.", "Kliknij stronę w miejscu, w którym ma być ikona komentarza. Naciśnij Esc, aby anulować."),
    "comment_text_prompt": ("Comment text:", "注释文本：", "टिप्पणी का पाठ:", "Texto del comentario:", "Texte du commentaire :", "نص التعليق:", "মন্তব্যের পাঠ্য:", "Texto do comentário:", "Teks komentar:", "تبصرے کا متن:", "Text komentáře:", "Text komentára:", "Treść komentarza:"),
    "comment_empty": ("Enter comment text before placing the annotation.", "放置批注前请输入注释文本。", "एनोटेशन रखने से पहले टिप्पणी लिखें।", "Escriba el comentario antes de colocar la anotación.", "Saisissez le commentaire avant de placer l’annotation.", "أدخل نص التعليق قبل وضع التعليق التوضيحي.", "টীকা বসানোর আগে মন্তব্য লিখুন।", "Introduza o texto antes de colocar a anotação.", "Masukkan teks komentar sebelum menempatkan anotasi.", "تشریح رکھنے سے پہلے تبصرہ لکھیں۔", "Před vložením anotace zadejte text komentáře.", "Pred vložením anotácie zadajte text komentára.", "Przed umieszczeniem adnotacji wpisz treść komentarza."),
    "comment_added": ("Comment added. Use Undo to remove it.", "已添加注释。使用撤销可将其删除。", "टिप्पणी जोड़ दी गई। हटाने के लिए पूर्ववत करें।", "Comentario añadido. Use Deshacer para eliminarlo.", "Commentaire ajouté. Utilisez Annuler pour le supprimer.", "تمت إضافة التعليق. استخدم تراجع لإزالته.", "মন্তব্য যোগ হয়েছে। সরাতে পূর্বাবস্থায় ফেরান।", "Comentário adicionado. Use Anular para o remover.", "Komentar ditambahkan. Gunakan Urungkan untuk menghapusnya.", "تبصرہ شامل کر دیا گیا۔ ہٹانے کے لیے کالعدم کریں۔", "Komentář byl přidán. Pomocí Zpět jej odstraníte.", "Komentár bol pridaný. Pomocou Späť ho odstránite.", "Komentarz został dodany. Użyj Cofnij, aby go usunąć."),
    "highlight_added": ("Text highlighted. Use Undo to remove the highlight.", "文本已突出显示。使用撤销可删除突出显示。", "पाठ हाइलाइट किया गया। हाइलाइट हटाने के लिए पूर्ववत करें।", "Texto resaltado. Use Deshacer para quitar el resaltado.", "Texte surligné. Utilisez Annuler pour supprimer le surlignage.", "تم تمييز النص. استخدم تراجع لإزالة التمييز.", "পাঠ হাইলাইট হয়েছে। হাইলাইট সরাতে পূর্বাবস্থায় ফেরান।", "Texto realçado. Use Anular para remover o realce.", "Teks disorot. Gunakan Urungkan untuk menghapus sorotan.", "متن نمایاں کر دیا گیا۔ نمایاں کرنا ہٹانے کے لیے کالعدم کریں۔", "Text byl zvýrazněn. Pomocí Zpět zvýraznění odstraníte.", "Text bol zvýraznený. Pomocou Späť zvýraznenie odstránite.", "Tekst został wyróżniony. Użyj Cofnij, aby usunąć wyróżnienie."),
    "comment_updated": ("Comment updated. Use Undo to restore the previous text.", "注释已更新。使用撤销可恢复以前的文本。", "टिप्पणी अपडेट की गई। पिछला पाठ वापस लाने के लिए पूर्ववत करें।", "Comentario actualizado. Use Deshacer para restaurar el texto anterior.", "Commentaire mis à jour. Utilisez Annuler pour restaurer le texte précédent.", "تم تحديث التعليق. استخدم تراجع لاستعادة النص السابق.", "মন্তব্য আপডেট হয়েছে। আগের পাঠ্য ফেরাতে পূর্বাবস্থায় ফেরান।", "Comentário atualizado. Use Anular para restaurar o texto anterior.", "Komentar diperbarui. Gunakan Urungkan untuk memulihkan teks sebelumnya.", "تبصرہ اپ ڈیٹ ہو گیا۔ سابقہ متن بحال کرنے کے لیے کالعدم کریں۔", "Komentář byl upraven. Pomocí Zpět obnovíte předchozí text.", "Komentár bol upravený. Pomocou Späť obnovíte predchádzajúci text.", "Komentarz został zaktualizowany. Użyj Cofnij, aby przywrócić poprzednią treść."),
    "delete_annotation_question": ("Delete the selected annotation?", "删除所选批注？", "चुना हुआ एनोटेशन हटाएँ?", "¿Eliminar la anotación seleccionada?", "Supprimer l’annotation sélectionnée ?", "هل تريد حذف التعليق التوضيحي المحدد؟", "নির্বাচিত টীকা মুছবেন?", "Eliminar a anotação selecionada?", "Hapus anotasi terpilih?", "منتخب تشریح حذف کریں؟", "Odstranit vybranou anotaci?", "Odstrániť vybranú anotáciu?", "Usunąć wybraną adnotację?"),
    "annotation_deleted": ("Annotation deleted. Use Undo to restore it.", "批注已删除。使用撤销可将其恢复。", "एनोटेशन हटा दिया गया। वापस लाने के लिए पूर्ववत करें।", "Anotación eliminada. Use Deshacer para restaurarla.", "Annotation supprimée. Utilisez Annuler pour la restaurer.", "تم حذف التعليق التوضيحي. استخدم تراجع لاستعادته.", "টীকা মুছে ফেলা হয়েছে। ফেরাতে পূর্বাবস্থায় ফেরান।", "Anotação eliminada. Use Anular para a restaurar.", "Anotasi dihapus. Gunakan Urungkan untuk memulihkannya.", "تشریح حذف کر دی گئی۔ بحال کرنے کے لیے کالعدم کریں۔", "Anotace byla odstraněna. Pomocí Zpět ji obnovíte.", "Anotácia bola odstránená. Pomocou Späť ju obnovíte.", "Adnotacja została usunięta. Użyj Cofnij, aby ją przywrócić."),
    "annotation_without_comment": ("No comment text", "无注释文本", "कोई टिप्पणी नहीं", "Sin texto de comentario", "Aucun texte de commentaire", "لا يوجد نص تعليق", "কোনো মন্তব্যের পাঠ্য নেই", "Sem texto de comentário", "Tidak ada teks komentar", "کوئی تبصرہ متن نہیں", "Bez textu komentáře", "Bez textu komentára", "Brak treści komentarza"),
})


_TRANSLATIONS: dict[str, dict[str, str]] = {language.code: {} for language in LANGUAGES}
for key, values in _ROWS.items():
    if len(values) != len(_ROW_LANGUAGE_CODES):
        raise RuntimeError(f"Invalid translation row {key}: {len(values)} values")
    for code, value in zip(_ROW_LANGUAGE_CODES, values):
        _TRANSLATIONS[code][key] = value

for key, values in EUROPEAN_ROWS.items():
    if len(values) != len(EUROPEAN_LANGUAGE_CODES):
        raise RuntimeError(f"Invalid European translation row {key}: {len(values)} values")
    for code, value in zip(EUROPEAN_LANGUAGE_CODES, values):
        _TRANSLATIONS[code][key] = value


def translate(language: str, key: str, **values: object) -> str:
    template = (
        _REGIONAL.get(language, {}).get(key)
        or _TRANSLATIONS.get(language, {}).get(key)
        or BASE.get(key)
        or key
    )
    try:
        return template.format(**values)
    except (KeyError, ValueError):
        return template


def language_from_locale(locale_name: str) -> str:
    code = locale_name.lower().replace("-", "_").split("_", 1)[0]
    return code if code in LANGUAGE_CODES else "en"


def _star(center_x: float, center_y: float, outer: float, inner: float | None = None) -> QPolygonF:
    inner = inner if inner is not None else outer * 0.42
    points: list[QPointF] = []
    for index in range(10):
        angle = math.radians(-90 + index * 36)
        radius = outer if index % 2 == 0 else inner
        points.append(QPointF(center_x + math.cos(angle) * radius, center_y + math.sin(angle) * radius))
    return QPolygonF(points)


def language_icon(code: str, size: int = 28) -> QIcon:
    pixmap = QPixmap(size + 4, round(size * 0.72) + 4)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(2, 2, size, round(size * 0.66))

    def fill(color: str) -> None:
        painter.fillRect(rect, QColor(color))

    def band(color: str, y: float, height: float) -> None:
        painter.fillRect(QRectF(rect.left(), rect.top() + y * rect.height(), rect.width(), height * rect.height()), QColor(color))

    if code == "en":
        fill("#21468b")
        painter.setPen(QPen(Qt.white, rect.height() * 0.23))
        painter.drawLine(rect.topLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomLeft())
        painter.setPen(QPen(QColor("#cf142b"), rect.height() * 0.09))
        painter.drawLine(rect.topLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomLeft())
        painter.fillRect(QRectF(rect.left(), rect.center().y() - rect.height() * 0.15, rect.width(), rect.height() * 0.30), Qt.white)
        painter.fillRect(QRectF(rect.center().x() - rect.width() * 0.10, rect.top(), rect.width() * 0.20, rect.height()), Qt.white)
        painter.fillRect(QRectF(rect.left(), rect.center().y() - rect.height() * 0.08, rect.width(), rect.height() * 0.16), QColor("#cf142b"))
        painter.fillRect(QRectF(rect.center().x() - rect.width() * 0.055, rect.top(), rect.width() * 0.11, rect.height()), QColor("#cf142b"))
    elif code == "zh":
        fill("#de2910")
        painter.setBrush(QColor("#ffde00"))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(_star(rect.left() + rect.width() * 0.23, rect.top() + rect.height() * 0.28, rect.height() * 0.19))
    elif code == "hi":
        band("#ff9933", 0, 1 / 3)
        band("#ffffff", 1 / 3, 1 / 3)
        band("#138808", 2 / 3, 1 / 3)
        painter.setPen(QPen(QColor("#000080"), 1.2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect.center(), rect.height() * 0.12, rect.height() * 0.12)
    elif code == "es":
        band("#aa151b", 0, 0.25)
        band("#f1bf00", 0.25, 0.5)
        band("#aa151b", 0.75, 0.25)
    elif code == "fr":
        painter.fillRect(QRectF(rect.left(), rect.top(), rect.width() / 3, rect.height()), QColor("#0055a4"))
        painter.fillRect(QRectF(rect.left() + rect.width() / 3, rect.top(), rect.width() / 3, rect.height()), Qt.white)
        painter.fillRect(QRectF(rect.left() + rect.width() * 2 / 3, rect.top(), rect.width() / 3, rect.height()), QColor("#ef4135"))
    elif code == "ar":
        fill("#006c35")
        painter.setPen(QPen(Qt.white, 1.5))
        painter.drawLine(QPointF(rect.left() + rect.width() * 0.23, rect.top() + rect.height() * 0.70), QPointF(rect.left() + rect.width() * 0.80, rect.top() + rect.height() * 0.70))
        painter.drawLine(QPointF(rect.left() + rect.width() * 0.35, rect.top() + rect.height() * 0.42), QPointF(rect.left() + rect.width() * 0.67, rect.top() + rect.height() * 0.42))
    elif code == "bn":
        fill("#006a4e")
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#f42a41"))
        painter.drawEllipse(QPointF(rect.left() + rect.width() * 0.45, rect.center().y()), rect.height() * 0.27, rect.height() * 0.27)
    elif code == "pt":
        painter.fillRect(QRectF(rect.left(), rect.top(), rect.width() * 0.40, rect.height()), QColor("#046a38"))
        painter.fillRect(QRectF(rect.left() + rect.width() * 0.40, rect.top(), rect.width() * 0.60, rect.height()), QColor("#da291c"))
        painter.setPen(QPen(QColor("#ffcc29"), 1.8))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(rect.left() + rect.width() * 0.40, rect.center().y()), rect.height() * 0.20, rect.height() * 0.20)
    elif code == "id":
        band("#ce1126", 0, 0.5)
        band("#ffffff", 0.5, 0.5)
    elif code == "ur":
        fill("#01411c")
        painter.fillRect(QRectF(rect.left(), rect.top(), rect.width() * 0.20, rect.height()), Qt.white)
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white)
        center = QPointF(rect.left() + rect.width() * 0.59, rect.center().y())
        painter.drawEllipse(center, rect.height() * 0.27, rect.height() * 0.27)
        painter.setBrush(QColor("#01411c"))
        painter.drawEllipse(QPointF(center.x() + rect.height() * 0.10, center.y() - rect.height() * 0.05), rect.height() * 0.24, rect.height() * 0.24)
        painter.setBrush(Qt.white)
        painter.drawPolygon(_star(rect.left() + rect.width() * 0.69, rect.top() + rect.height() * 0.31, rect.height() * 0.10))
    elif code == "de":
        band("#000000", 0, 1 / 3)
        band("#dd0000", 1 / 3, 1 / 3)
        band("#ffce00", 2 / 3, 1 / 3)
    elif code == "ru":
        band("#ffffff", 0, 1 / 3)
        band("#0039a6", 1 / 3, 1 / 3)
        band("#d52b1e", 2 / 3, 1 / 3)
    elif code == "tr":
        fill("#e30a17")
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white)
        center = QPointF(rect.left() + rect.width() * 0.42, rect.center().y())
        painter.drawEllipse(center, rect.height() * 0.27, rect.height() * 0.27)
        painter.setBrush(QColor("#e30a17"))
        painter.drawEllipse(
            QPointF(center.x() + rect.height() * 0.11, center.y()),
            rect.height() * 0.21,
            rect.height() * 0.21,
        )
        painter.setBrush(Qt.white)
        painter.drawPolygon(
            _star(
                rect.left() + rect.width() * 0.64,
                rect.center().y(),
                rect.height() * 0.11,
            )
        )
    elif code == "it":
        painter.fillRect(QRectF(rect.left(), rect.top(), rect.width() / 3, rect.height()), QColor("#009246"))
        painter.fillRect(QRectF(rect.left() + rect.width() / 3, rect.top(), rect.width() / 3, rect.height()), Qt.white)
        painter.fillRect(QRectF(rect.left() + rect.width() * 2 / 3, rect.top(), rect.width() / 3, rect.height()), QColor("#ce2b37"))
    elif code == "nl":
        band("#ae1c28", 0, 1 / 3)
        band("#ffffff", 1 / 3, 1 / 3)
        band("#21468b", 2 / 3, 1 / 3)
    elif code == "ro":
        painter.fillRect(QRectF(rect.left(), rect.top(), rect.width() / 3, rect.height()), QColor("#002b7f"))
        painter.fillRect(QRectF(rect.left() + rect.width() / 3, rect.top(), rect.width() / 3, rect.height()), QColor("#fcd116"))
        painter.fillRect(QRectF(rect.left() + rect.width() * 2 / 3, rect.top(), rect.width() / 3, rect.height()), QColor("#ce1126"))
    elif code == "hu":
        band("#ce2939", 0, 1 / 3)
        band("#ffffff", 1 / 3, 1 / 3)
        band("#477050", 2 / 3, 1 / 3)
    elif code == "uk":
        band("#0057b7", 0, 0.5)
        band("#ffd700", 0.5, 0.5)
    elif code == "cs":
        band("#ffffff", 0, 0.5)
        band("#d7141a", 0.5, 0.5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#11457e"))
        painter.drawPolygon(QPolygonF([rect.topLeft(), QPointF(rect.left() + rect.width() * 0.45, rect.center().y()), rect.bottomLeft()]))
    elif code == "sk":
        band("#ffffff", 0, 1 / 3)
        band("#0b4ea2", 1 / 3, 1 / 3)
        band("#ee1c25", 2 / 3, 1 / 3)
        shield = QRectF(rect.left() + rect.width() * 0.25, rect.top() + rect.height() * 0.25, rect.width() * 0.16, rect.height() * 0.48)
        painter.fillRect(shield, QColor("#ee1c25"))
        painter.setPen(QPen(Qt.white, 1.1))
        painter.drawLine(QPointF(shield.center().x(), shield.top() + 1), QPointF(shield.center().x(), shield.bottom() - 1))
        painter.drawLine(QPointF(shield.left() + 1, shield.top() + shield.height() * 0.38), QPointF(shield.right() - 1, shield.top() + shield.height() * 0.38))
    elif code == "pl":
        band("#ffffff", 0, 0.5)
        band("#dc143c", 0.5, 0.5)
    else:
        fill("#73808c")

    painter.setPen(QPen(QColor(0, 0, 0, 125), 1.0))
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(rect)
    painter.end()
    return QIcon(pixmap)
