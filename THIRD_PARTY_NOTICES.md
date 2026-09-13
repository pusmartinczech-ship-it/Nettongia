# Third-party notices

The installed `licenses` directory contains license files copied from the exact
Python packages used to create that build. This summary identifies the principal
components and their upstream license pages.

- PyMuPDF and MuPDF: GNU Affero General Public License v3, or a separately
  purchased commercial license. <https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright>
- PySide6, Shiboken6 and Qt modules: GNU LGPLv3/GPLv3 or Qt commercial terms,
  with module-specific third-party notices. <https://doc.qt.io/qtforpython-6/licenses.html>
- Pillow: HPND license. <https://python-pillow.github.io/license.html>
- Tesseract OCR and Leptonica: Apache License 2.0 and BSD-style license. Their
  OCR engine is embedded in the pinned PyMuPDF/MuPDF build; no separate runtime
  executable is downloaded or installed. <https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE>
  <https://github.com/DanBloomberg/leptonica/blob/master/leptonica-license.txt>
- Tesseract language data: Apache License 2.0, checked into `vendor/ocr` from
  the official `tessdata_fast` 4.1.0 tag. <https://github.com/tesseract-ocr/tessdata_fast>
  The exact file notice and SHA-256 manifest are shipped beside the models.
- PyInstaller: GPLv2 with an exception for distributing bundled applications.
  <https://pyinstaller.org/en/stable/license.html>
- Inno Setup: see the upstream license. <https://jrsoftware.org/files/is/license.txt>

OpenPDF Editor source code is licensed under AGPL-3.0-or-later. The corresponding
source archive included with the installer contains the application source,
tests, build scripts and dependency declarations for that exact release.
