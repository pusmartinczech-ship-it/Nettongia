from __future__ import annotations

import os
import sys
import hashlib
import json
from pathlib import Path


_DLL_HANDLES: list[object] = []
REQUIRED_OCR_LANGUAGES = frozenset({"ces", "slk", "pol", "deu", "eng", "osd"})
REQUIRED_OCR_USER_LANGUAGES = REQUIRED_OCR_LANGUAGES - {"osd"}


def resource_root() -> Path:
    """Return the source or PyInstaller data root."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def bundled_ocr_root() -> Path | None:
    """Return the checked-in or frozen OCR asset directory.

    A source checkout keeps the models below ``vendor/ocr``. PyInstaller maps
    that directory to ``ocr`` beside the frozen application. No system
    Tesseract installation or user download is part of either lookup.
    """

    root = resource_root()
    for candidate in (root / "ocr", root / "vendor" / "ocr"):
        if (candidate / "tessdata").is_dir():
            return candidate
    return None


def bundled_tessdata_path(*, verify: bool = False) -> Path | None:
    root = bundled_ocr_root()
    if root is None:
        return None
    tessdata = root / "tessdata"
    if not REQUIRED_OCR_LANGUAGES.issubset(
        {path.stem for path in tessdata.glob("*.traineddata") if path.is_file()}
    ):
        return None
    if verify and not verify_bundled_ocr(root):
        return None
    return tessdata


def verify_bundled_ocr(root: Path | None = None) -> bool:
    """Verify every vendored OCR file against the immutable manifest."""

    root = root or bundled_ocr_root()
    if root is None:
        return False
    manifest_path = root / "SHA256SUMS.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest["files"]
        if manifest.get("format") != "openpdf-ocr-assets-v1" or not isinstance(files, dict):
            return False
        for relative_name, expected_hash in files.items():
            if not isinstance(relative_name, str) or not isinstance(expected_hash, str):
                return False
            relative_path = Path(relative_name)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                return False
            payload = (root / relative_path).read_bytes()
            if hashlib.sha256(payload).hexdigest() != expected_hash.lower():
                return False
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return REQUIRED_OCR_LANGUAGES.issubset(
        {
            Path(name).stem
            for name in files
            if Path(name).suffix == ".traineddata"
        }
    )


def configure_packaged_runtime() -> None:
    """Make the self-contained OCR models visible before PyMuPDF loads."""

    ocr_root = bundled_ocr_root()
    if ocr_root is None:
        return
    tessdata = bundled_tessdata_path()
    if tessdata is not None:
        # Deliberately replace, rather than merely default, an inherited value.
        # A stale system TESSDATA_PREFIX must not make the packaged application
        # depend on files outside its own directory.
        os.environ["TESSDATA_PREFIX"] = str(tessdata)

    binary_root = ocr_root / "bin"
    if not binary_root.is_dir():
        return
    os.environ["PATH"] = str(binary_root) + os.pathsep + os.environ.get("PATH", "")
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        try:
            _DLL_HANDLES.append(os.add_dll_directory(str(binary_root)))
        except OSError:
            pass
