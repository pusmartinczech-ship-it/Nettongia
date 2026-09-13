from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .runtime import bundled_tessdata_path, configure_packaged_runtime

try:
    import pymupdf
except ImportError:  # PyMuPDF before 1.24
    import fitz as pymupdf


OCR_JOB_FORMAT = "openpdf-editor-ocr"
OCR_JOB_SCHEMA_VERSION = 1
MAX_DESCRIPTOR_BYTES = 1024 * 1024
MAX_OCR_PAGES = 100_000
SUPPORTED_DPI = {150, 200, 300}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The OCR result is too large.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def available_ocr_languages() -> dict[str, str]:
    names = {
        "ces": "Čeština",
        "deu": "Deutsch",
        "eng": "English",
        "fra": "Français",
        "hun": "Magyar",
        "ita": "Italiano",
        "nld": "Nederlands",
        "pol": "Polski",
        "por": "Português",
        "ron": "Română",
        "rus": "Русский",
        "slk": "Slovenčina",
        "spa": "Español",
        "tur": "Türkçe",
        "ukr": "Українська",
    }
    configure_packaged_runtime()
    root = bundled_tessdata_path()
    if root is None:
        return {}
    return {
        path.stem: names.get(path.stem, path.stem)
        for path in sorted(root.glob("*.traineddata"))
        if path.stem != "osd"
    }


def prepare_ocr_job(
    workspace: str | Path,
    source_bytes: bytes,
    page_indices: Iterable[int],
    language: str,
    dpi: int = 200,
) -> tuple[Path, Path, Path]:
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    pages = tuple(page_indices)
    if not pages or len(pages) > MAX_OCR_PAGES:
        raise ValueError("Invalid OCR page selection.")
    if any(type(index) is not int or index < 0 for index in pages) or len(set(pages)) != len(pages):
        raise ValueError("Invalid OCR page selection.")
    if not isinstance(language, str) or not language.isascii() or not language.replace("+", "").isalnum():
        raise ValueError("Invalid OCR language.")
    if dpi not in SUPPORTED_DPI:
        raise ValueError("Invalid OCR resolution.")
    source_path = root / "source.pdf"
    output_path = root / "ocr-output.pdf"
    result_path = root / "result.json"
    source_path.write_bytes(source_bytes)
    payload = {
        "format": OCR_JOB_FORMAT,
        "schema_version": OCR_JOB_SCHEMA_VERSION,
        "source_path": str(source_path),
        "output_path": str(output_path),
        "result_path": str(result_path),
        "page_indices": list(pages),
        "language": language,
        "dpi": dpi,
    }
    _write_json_atomic(root / "job.json", payload)
    return root / "job.json", result_path, output_path


def _read_job(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The OCR job is too large.")
    try:
        job = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The OCR job is damaged.") from exc
    if not isinstance(job, dict) or job.get("format") != OCR_JOB_FORMAT:
        raise ValueError("The OCR job format is invalid.")
    if job.get("schema_version") != OCR_JOB_SCHEMA_VERSION:
        raise ValueError("The OCR job version is not supported.")
    for name in ("source_path", "output_path", "result_path"):
        value = job.get(name)
        if not isinstance(value, str) or not value or len(value) > 32_768:
            raise ValueError(f"Invalid OCR field: {name}.")
    pages = job.get("page_indices")
    if not isinstance(pages, list) or not pages or len(pages) > MAX_OCR_PAGES:
        raise ValueError("Invalid OCR page selection.")
    if any(type(index) is not int or index < 0 for index in pages) or len(set(pages)) != len(pages):
        raise ValueError("Invalid OCR page selection.")
    language = job.get("language")
    if not isinstance(language, str) or not language.isascii() or not language.replace("+", "").isalnum():
        raise ValueError("Invalid OCR language.")
    if job.get("dpi") not in SUPPORTED_DPI:
        raise ValueError("Invalid OCR resolution.")
    return job


def _ocr_font_path() -> str | None:
    candidates = (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    )
    return str(next((path for path in candidates if path.is_file()), "")) or None


def _insert_invisible_word(page, word: tuple, font_path: str | None) -> bool:
    rect = pymupdf.Rect(word[:4]) & page.rect
    text = str(word[4]).strip()
    if not text or rect.is_empty or rect.width < 0.5 or rect.height < 0.5:
        return False
    font_size = min(96.0, max(3.0, rect.height * 0.78))
    kwargs = {
        "fontname": "ocrfont" if font_path else "helv",
        "fontfile": font_path,
        "fontsize": font_size,
        "render_mode": 3,
        "overlay": True,
    }
    result = page.insert_textbox(rect, text, **kwargs)
    if result < 0:
        page.insert_text((rect.x0, rect.y1 - max(0.5, rect.height * 0.12)), text, **kwargs)
    return True


def run_ocr_job(job_path: str | Path) -> int:
    result_path: Path | None = None
    document = None
    try:
        job = _read_job(job_path)
        result_path = Path(job["result_path"])
        output_path = Path(job["output_path"])
        document = pymupdf.open(job["source_path"])
        if any(index >= document.page_count for index in job["page_indices"]):
            raise ValueError("The OCR page selection is out of range.")
        languages = available_ocr_languages()
        tessdata = bundled_tessdata_path(verify=True)
        if tessdata is None:
            raise ValueError("The bundled OCR data is missing or failed integrity validation.")
        language_parts = job["language"].split("+")
        missing = [code for code in language_parts if code not in languages]
        if missing:
            raise ValueError("Missing Tesseract language data: " + ", ".join(missing))
        processed = 0
        skipped = 0
        words_inserted = 0
        font_path = _ocr_font_path()
        for page_index in job["page_indices"]:
            page = document[page_index]
            if len(page.get_text("text").strip()) >= 3:
                skipped += 1
                continue
            textpage = page.get_textpage_ocr(
                language=job["language"],
                dpi=job["dpi"],
                full=True,
                tessdata=str(tessdata),
            )
            words = page.get_text("words", textpage=textpage, sort=True)
            inserted = sum(_insert_invisible_word(page, word, font_path) for word in words)
            if inserted:
                processed += 1
                words_inserted += inserted
        if processed:
            temporary = output_path.with_suffix(".tmp.pdf")
            document.save(temporary, garbage=2, deflate=True)
            with pymupdf.open(temporary) as verification:
                if verification.page_count != document.page_count:
                    raise ValueError("OCR output page count changed.")
                for index in dict.fromkeys((0, verification.page_count // 2, verification.page_count - 1)):
                    page = verification[index]
                    area = max(1.0, page.rect.width * page.rect.height)
                    scale = min(0.35, max(0.05, math.sqrt(500_000 / area)))
                    page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, annots=True)
            os.replace(temporary, output_path)
            payload = output_path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            output_size = len(payload)
        else:
            digest = ""
            output_size = 0
        _write_json_atomic(
            result_path,
            {
                "format": OCR_JOB_FORMAT,
                "status": "succeeded",
                "processed_pages": processed,
                "skipped_pages": skipped,
                "words_inserted": words_inserted,
                "output_size": output_size,
                "sha256": digest,
            },
        )
        return 0
    except Exception as exc:
        if result_path is not None:
            try:
                _write_json_atomic(
                    result_path,
                    {"format": OCR_JOB_FORMAT, "status": "failed", "error": str(exc)},
                )
            except OSError:
                pass
        return 1
    finally:
        if document is not None:
            document.close()


def read_ocr_result(path: str | Path, output_path: str | Path) -> tuple[dict[str, int] | None, str | None]:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The OCR result is too large.")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The OCR result is damaged.") from exc
    if not isinstance(result, dict) or result.get("format") != OCR_JOB_FORMAT:
        raise ValueError("The OCR result is invalid.")
    if result.get("status") == "failed":
        return None, str(result.get("error") or "OCR failed.")
    names = ("processed_pages", "skipped_pages", "words_inserted", "output_size")
    if result.get("status") != "succeeded" or any(type(result.get(name)) is not int or result[name] < 0 for name in names):
        raise ValueError("The OCR result is invalid.")
    output_size = result["output_size"]
    digest = result.get("sha256")
    if result["processed_pages"]:
        payload = Path(output_path).read_bytes()
        if output_size != len(payload) or not isinstance(digest, str) or hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("The OCR output failed integrity validation.")
    elif output_size or digest:
        raise ValueError("The OCR result is invalid.")
    return {name: result[name] for name in names}, None


def main() -> int:
    import sys

    if len(sys.argv) != 2:
        return 2
    return run_ocr_job(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
