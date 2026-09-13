from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    if len(sys.argv) > 2:
        return 2
    root = Path(sys.argv[1]) if len(sys.argv) == 2 else project_root / "vendor" / "ocr"
    sys.path.insert(0, str(project_root))
    from openpdf_editor.runtime import REQUIRED_OCR_LANGUAGES, verify_bundled_ocr

    if not verify_bundled_ocr(root):
        print(f"Offline OCR bundle failed integrity validation: {root}", file=sys.stderr)
        return 1
    print(
        "Offline OCR bundle verified: "
        + ", ".join(sorted(REQUIRED_OCR_LANGUAGES))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
