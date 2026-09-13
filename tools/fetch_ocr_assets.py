"""Restore the hash-pinned OCR data required by source and Windows builds.

Release archives contain these files already and never download at runtime.
This helper is only for a clean source checkout, where storing the large model
blobs as ordinary Git objects would make repository maintenance unnecessarily
expensive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OCR_ROOT = ROOT / "vendor" / "ocr"
MANIFEST_PATH = OCR_ROOT / "SHA256SUMS.json"
SOURCE_BASE = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_url(relative: str) -> str:
    name = "LICENSE" if relative == "LICENSE-tessdata.txt" else Path(relative).name
    return f"{SOURCE_BASE}/{name}"


def restore_assets(*, verify_only: bool = False) -> list[str]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("format") != "openpdf-ocr-assets-v1":
        raise RuntimeError("Unsupported OCR asset manifest format.")

    restored: list[str] = []
    for relative, expected in manifest["files"].items():
        destination = OCR_ROOT / relative
        if destination.is_file() and _sha256(destination) == expected:
            continue
        if verify_only:
            raise RuntimeError(f"Missing or invalid OCR asset: {relative}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".part")
        temporary.unlink(missing_ok=True)
        request = Request(
            _source_url(relative),
            headers={"User-Agent": "Nettongia-OCR-bootstrap/1"},
        )
        digest = hashlib.sha256()
        try:
            with urlopen(request, timeout=120) as response, temporary.open("wb") as output:
                while block := response.read(1024 * 1024):
                    digest.update(block)
                    output.write(block)
            actual = digest.hexdigest()
            if actual != expected:
                raise RuntimeError(
                    f"Hash mismatch for {relative}: expected {expected}, got {actual}"
                )
            os.replace(temporary, destination)
            restored.append(relative)
        finally:
            temporary.unlink(missing_ok=True)

    return restored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="fail instead of downloading when an asset is missing or invalid",
    )
    args = parser.parse_args(argv)
    try:
        restored = restore_assets(verify_only=args.verify_only)
    except Exception as exc:
        print(f"OCR asset preparation failed: {exc}", file=sys.stderr)
        return 1
    if restored:
        print("Restored and verified: " + ", ".join(restored))
    else:
        print("All pinned OCR assets are present and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

