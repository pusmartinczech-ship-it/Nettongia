#!/usr/bin/env python3
"""Render the DE/ES/FR landing pages from the English source before publishing.

The generated pages are committed so Cloudflare Pages serves static HTML.
Requires lxml only when changing the translations; production has no build step.
"""

import hashlib
import json
from pathlib import Path
from lxml import html

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "index.html"
SOURCE_LABELS_SHA256 = "fd6968172559f3fdf75a7c3d8b51e1798163d8e7d0413525a5a3a994993e4460"

# Entries correspond to the data-en strings in index.html, in document order.
# A count check below prevents a new feature from silently appearing in English.
TRANSLATIONS = {
    "de": """Funktionen|Datenschutz|Download|Support|Signaturrichtlinie
PDFS OFFLINE UNTER WINDOWS BEARBEITEN|Kostenloser Offline-PDF-Editor für Windows.|Bearbeiten Sie echten Text, Seiten und Bilder direkt auf Ihrem Computer. Nettongia muss Ihre Dokumente niemals auf einen Server hochladen.|Version 0.22.0 herunterladen|Entwicklung unterstützen|Funktioniert offline|Keine Dokument-Telemetrie|Fünf OCR-Sprachen enthalten
Windows-Tests bestanden|unerwartete Abweichungen in Referenzbildern|enthaltene OCR-Sprachen|lokale Dokumentverarbeitung
FÜR DIE TÄGLICHE ARBEIT MIT PDFS|Nützliche Werkzeuge ohne Cloud.|Echten Text bearbeiten|Ändern Sie vorhandenen Text und fügen Sie verschiebbare, skalierbare Textfelder hinzu, ohne die Seitenausrichtung zu verändern.|Seiten einfach verwalten|Verschieben Sie Seitenminiaturen wie Folien, drehen Sie Seiten nach links oder rechts und löschen Sie sie mit der Entf-Taste oder über das Kontextmenü.|Mit Bildern arbeiten|Verschieben, skalieren und drehen Sie eingefügte oder vorhandene PDF-Bilder ohne unnötigen Qualitätsverlust.|OCR integriert|Erkennen Sie tschechische, slowakische, polnische, deutsche und englische Texte, ohne Tesseract zu installieren.|Sichere Kopie speichern|Mit „Kopie speichern“ bleibt die Originaldatei unverändert. Hinweise zur Kompatibilität helfen bei der Entscheidung.|Änderungen sicher rückgängig machen|Machen Sie Änderungen an Seiten, Text und Objekten rückgängig und wiederholen Sie sie. Die automatische lokale Wiederherstellung schützt nicht gespeicherte Arbeit.
DATENSCHUTZ DURCH DIE ARCHITEKTUR|Am sichersten ist es, nichts hochzuladen.|Nettongia verarbeitet PDFs, OCR und Diagnosedaten lokal. Es enthält keine Werbetracker und sendet Dokumentinhalte, Dateinamen oder Pfade nicht automatisch an andere Stellen.|Datenschutzerklärung lesen →
NEUESTE VERIFIZIERTE VERSION|Portable ZIP für Windows 10/11 x64. Entpacken Sie die Datei in einen Ordner und starten Sie NettongiaPDFEditor.exe; eine Installation ist nicht erforderlich. Diese Version wurde geprüft, ist aber noch nicht digital signiert.|Portable Version herunterladen|Signaturstatus|Nicht signierte Version. Windows kann eine Warnung über einen unbekannten Herausgeber anzeigen; deaktivieren Sie weder SmartScreen noch den Virenschutz.|Wir freuen uns über Feedback, Fehlermeldungen und Verbesserungsvorschläge:|GitHub Issues|Plattform|SHA-256 der portablen ZIP-Datei
Besuche|Downloads|Live-Zähler sind vorübergehend nicht verfügbar.|Datenschutz|Lizenzen|E-Mail-Support|Problem oder Idee melden|Quellcode|Für PDFs entwickelt, nicht zum Sammeln von Daten.""",
    "es": """Funciones|Privacidad|Descargar|Asistencia|Política de firma
EDICIÓN DE PDF SIN CONEXIÓN PARA WINDOWS|Editor de PDF gratuito y sin conexión para Windows.|Edita texto, páginas e imágenes del PDF directamente en tu ordenador. Nettongia no necesita subir tus documentos a un servidor.|Descargar versión 0.22.0|Apoyar el desarrollo|Funciona sin conexión|Sin telemetría de documentos|Incluye OCR para cinco idiomas
Pruebas de Windows superadas|diferencias inesperadas en imágenes de referencia|idiomas de OCR incluidos|procesamiento local de documentos
CREADO PARA TRABAJAR CON PDF A DIARIO|Herramientas útiles sin depender de la nube.|Editar texto real|Modifica el texto existente y añade cuadros de texto que puedes mover y redimensionar sin alterar la orientación de la página.|Organizar páginas fácilmente|Arrastra las miniaturas como diapositivas, gira las páginas a izquierda o derecha y elimínalas con Supr o desde el menú contextual.|Trabajar con imágenes|Mueve, redimensiona y gira imágenes insertadas o ya presentes en el PDF sin pérdidas de calidad innecesarias.|OCR incluido|Reconoce texto en checo, eslovaco, polaco, alemán e inglés sin instalar Tesseract.|Guardar una copia segura|Con «Guardar una copia», el archivo original no se sobrescribe; las indicaciones de compatibilidad te ayudan a decidir.|Deshacer con confianza|Deshaz y rehace cambios en páginas, texto y objetos. La recuperación local automática protege el trabajo sin guardar.
PRIVACIDAD DESDE EL DISEÑO|La opción más segura es no subir nada.|Nettongia procesa los PDF, el OCR y los datos de diagnóstico de forma local. No incluye rastreadores publicitarios ni envía automáticamente el contenido, los nombres o las rutas de tus documentos.|Leer la política de privacidad →
ÚLTIMA VERSIÓN VERIFICADA|Archivo ZIP portátil para Windows 10/11 x64. Descomprímelo en una carpeta y ejecuta NettongiaPDFEditor.exe; no hace falta instalarlo. Esta versión ha sido verificada, pero aún no tiene firma digital.|Descargar versión portátil|Estado de la firma|Versión sin firma digital. Windows puede mostrar una advertencia de editor desconocido; no desactives SmartScreen ni el antivirus.|Agradecemos tus comentarios, informes de errores e ideas para mejorar:|GitHub Issues|Plataforma|SHA-256 del ZIP portátil
visitas|descargas|Los contadores en tiempo real no están disponibles temporalmente.|Privacidad|Licencias|Asistencia por correo|Informar de un problema o proponer una idea|Código fuente|Creado para trabajar con PDF, no para recopilar datos.""",
    "fr": """Fonctionnalités|Confidentialité|Télécharger|Assistance|Politique de signature
MODIFIER DES PDF HORS LIGNE SUR WINDOWS|Éditeur PDF gratuit et hors ligne pour Windows.|Modifiez le texte, les pages et les images des PDF directement sur votre ordinateur. Nettongia n’a pas besoin de transférer vos documents vers un serveur.|Télécharger la version 0.22.0|Soutenir le développement|Fonctionne hors ligne|Aucune télémétrie des documents|OCR intégré pour cinq langues
Tests Windows réussis|écarts inattendus dans les images de référence|langues OCR intégrées|traitement local des documents
POUR LE TRAVAIL QUOTIDIEN SUR LES PDF|Des outils utiles, sans cloud.|Modifier le vrai texte|Modifiez le texte existant et ajoutez des zones de texte déplaçables et redimensionnables tout en préservant l’orientation de la page.|Gérer les pages simplement|Faites glisser les miniatures comme des diapositives, pivotez les pages à gauche ou à droite et supprimez-les avec Suppr ou le menu contextuel.|Travailler avec les images|Déplacez, redimensionnez et faites pivoter les images ajoutées ou déjà présentes dans le PDF sans perte de qualité inutile.|OCR inclus|Reconnaissez les textes en tchèque, slovaque, polonais, allemand et anglais sans installer Tesseract.|Enregistrer une copie sûre|Avec « Enregistrer une copie », le fichier d’origine n’est pas écrasé ; les indications de compatibilité vous aident à décider.|Annuler en toute confiance|Annulez et rétablissez les modifications des pages, du texte et des objets. La récupération locale automatique protège le travail non enregistré.
LA CONFIDENTIALITÉ DÈS LA CONCEPTION|Le transfert le plus sûr est celui qu’on ne fait pas.|Nettongia traite les PDF, l’OCR et les diagnostics localement. Il ne contient pas de traceurs publicitaires et n’envoie pas automatiquement le contenu, les noms ou les chemins des documents.|Lire la politique de confidentialité →
DERNIÈRE VERSION VÉRIFIÉE|Archive ZIP portable pour Windows 10/11 x64. Décompressez-la dans un dossier et lancez NettongiaPDFEditor.exe ; aucune installation n’est nécessaire. Cette version est vérifiée, mais n’est pas encore signée numériquement.|Télécharger la version portable|État de la signature|Version non signée. Windows peut afficher un avertissement « Éditeur inconnu » ; ne désactivez jamais SmartScreen ni l’antivirus.|Vos retours, signalements de bugs et idées d’amélioration sont les bienvenus :|GitHub Issues|Plateforme|SHA-256 du ZIP portable
visites|téléchargements|Les compteurs en direct sont temporairement indisponibles.|Confidentialité|Licences|Assistance par e-mail|Signaler un problème ou proposer une idée|Code source|Conçu pour les PDF, pas pour collecter des données.""",
}

META = {
    "de": {
        "title": "Kostenloser Offline-PDF-Editor für Windows | Nettongia",
        "description": "Kostenloser Open-Source-PDF-Editor für Windows. Text, Bilder und Seiten bearbeiten, PDF unterschreiben und OCR nutzen – ohne Dokumente hochzuladen.",
        "og": "PDFs lokal bearbeiten: Text, Seiten, Bilder, visuelle Signaturen und OCR für fünf Sprachen. Kein Upload von Dokumenten erforderlich.",
        "twitter": "Open-Source-PDF-Bearbeitung und OCR direkt auf Ihrem Windows-Computer.",
        "skip": "Zum Inhalt springen", "primary": "Hauptnavigation", "language": "Sprache", "brand": "Nettongia PDF Editor – Startseite",
        "highlights": "Vorteile", "preview": "Vorschau der Nettongia-Anwendung",
        "hero": "PDFs nach Ihren\nWünschen.", "status": "Seite 1 / 3", "ready": "Offline • Bereit",
        "guide": "Anleitung zum Offline-PDF-Editor (EN)", "signing": "Signaturrichtlinie (EN)", "privacy": "Datenschutzerklärung (EN)", "licenses": "Lizenzen (EN)",
    },
    "es": {
        "title": "Editor de PDF gratuito y sin conexión para Windows | Nettongia",
        "description": "Editor de PDF gratuito y de código abierto para Windows. Edita texto, imágenes y páginas, firma documentos y utiliza OCR sin subir los archivos.",
        "og": "Edita PDF localmente: texto, páginas, imágenes, firmas visuales y OCR para cinco idiomas. No hace falta subir documentos.",
        "twitter": "Edición de PDF y OCR de código abierto en tu ordenador Windows.",
        "skip": "Saltar al contenido", "primary": "Navegación principal", "language": "Idioma", "brand": "Inicio de Nettongia PDF Editor",
        "highlights": "Ventajas", "preview": "Vista previa de Nettongia",
        "hero": "Tus PDF, a tu\nmanera.", "status": "Página 1 / 3", "ready": "Sin conexión • Listo",
        "guide": "Guía del editor PDF sin conexión (EN)", "signing": "Política de firma (EN)", "privacy": "Política de privacidad (EN)", "licenses": "Licencias (EN)",
    },
    "fr": {
        "title": "Éditeur PDF gratuit et hors ligne pour Windows | Nettongia",
        "description": "Éditeur PDF gratuit et open source pour Windows. Modifiez le texte, les images et les pages, signez et utilisez l’OCR sans transférer vos documents.",
        "og": "Modifiez vos PDF localement : texte, pages, images, signatures visuelles et OCR pour cinq langues. Aucun transfert requis.",
        "twitter": "Édition PDF et OCR open source sur votre ordinateur Windows.",
        "skip": "Aller au contenu", "primary": "Navigation principale", "language": "Langue", "brand": "Accueil de Nettongia PDF Editor",
        "highlights": "Points forts", "preview": "Aperçu de Nettongia",
        "hero": "Vos PDF, à votre\nfaçon.", "status": "Page 1 / 3", "ready": "Hors ligne • Prêt",
        "guide": "Guide de l’éditeur PDF hors ligne (EN)", "signing": "Politique de signature (EN)", "privacy": "Politique de confidentialité (EN)", "licenses": "Licences (EN)",
    },
}


def render(language: str, labels: list[str], translated: list[str]) -> None:
    if len(translated) != len(labels):
        raise ValueError(f"{language}: {len(translated)} translations for {len(labels)} source strings")
    cfg = META[language]
    tree = html.parse(str(SOURCE))
    doc = tree.getroot()
    doc.set("lang", language)
    for element, value in zip(doc.xpath('//*[@data-en]'), translated, strict=True):
        element.text = value
        element.attrib.pop("data-en")
        element.attrib.pop("data-cs")
    doc.xpath("//title")[0].text = cfg["title"]
    for query, value in (
        ('//meta[@name="description"]', cfg["description"]),
        ('//meta[@property="og:title"]', cfg["title"]),
        ('//meta[@property="og:description"]', cfg["og"]),
        ('//meta[@property="og:url"]', f"https://nettongia.com/{language}/"),
        ('//meta[@name="twitter:title"]', cfg["title"]),
        ('//meta[@name="twitter:description"]', cfg["twitter"]),
    ):
        doc.xpath(query)[0].set("content", value)
    doc.xpath('//link[@rel="canonical"]')[0].set("href", f"https://nettongia.com/{language}/")
    app = doc.xpath('//script[@type="application/ld+json"]')[0]
    data = json.loads(app.text)
    data["url"] = f"https://nettongia.com/{language}/"
    data["inLanguage"] = language
    app.text = "\n    " + json.dumps(data, ensure_ascii=False, indent=2) + "\n  "
    doc.xpath('//a[@class="skip"]')[0].text = cfg["skip"]
    doc.xpath('//header//a[@class="brand"]')[0].set("aria-label", cfg["brand"])
    doc.xpath('//nav[@aria-label="Primary"]')[0].set("aria-label", cfg["primary"])
    doc.xpath('//nav[contains(@class,"language")]')[0].set("aria-label", cfg["language"])
    for item in doc.xpath('//nav[contains(@class,"language")]/a'):
        item.attrib.pop("aria-current", None)
        if item.get("hreflang") == language:
            item.set("aria-current", "page")
    doc.xpath('//ul[contains(@class,"trust")]')[0].set("aria-label", cfg["highlights"])
    doc.xpath('//div[contains(@class,"product")]')[0].set("aria-label", cfg["preview"])
    hero = doc.xpath('//div[contains(@class,"page")]/h2')[0]
    first, second = cfg["hero"].split("\n")
    hero.text = first
    hero.xpath("./br")[0].tail = second
    status = doc.xpath('//div[contains(@class,"window-status")]/span')
    status[0].text, status[1].text = cfg["status"], cfg["ready"]
    for item in doc.xpath('//a[@href="offline-pdf-editor-windows.html"]'):
        item.text = cfg["guide"]
    for item in doc.xpath('//a[@href="code-signing-policy.html"]'):
        item.text = cfg["signing"] if item.xpath('ancestor::footer') else (item.text or "") + " (EN)"
    for item in doc.xpath('//a[@href="privacy.html"]'):
        item.text = cfg["privacy"] if item.xpath('ancestor::footer') else (item.text or "") + " (EN)"
    # Legal documents are available in English; label the links explicitly.
    for url, label in (("privacy.html", cfg["privacy"]), ("license.html", cfg["licenses"])):
        for item in doc.xpath(f'//footer//a[@href="{url}"]'):
            item.text = label
    for item in doc.xpath('//a[@href="./"]'):
        item.set("href", f"/{language}/")
    for element in doc.xpath('//*[@src or @href]'):
        for attr in ("src", "href"):
            value = element.get(attr)
            if value and not value.startswith(("/", "#", "http:", "https:", "mailto:")):
                element.set(attr, "../" + value)
    directory = ROOT / language
    directory.mkdir(exist_ok=True)
    (directory / "index.html").write_text(
        "<!doctype html>\n" + html.tostring(doc, encoding="unicode", method="html") + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    source = html.parse(str(SOURCE))
    labels = [element.get("data-en") for element in source.xpath('//*[@data-en]')]
    if hashlib.sha256("\n".join(labels).encode()).hexdigest() != SOURCE_LABELS_SHA256:
        raise ValueError("The English landing-page copy changed; review and update every translation")
    for language, text in TRANSLATIONS.items():
        translated = [part.strip() for part in text.replace("\n", "|").split("|")]
        render(language, labels, translated)
