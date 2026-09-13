from __future__ import annotations

import importlib.metadata
import shutil
import sys
from pathlib import Path


PACKAGES = ("PyMuPDF", "PySide6", "shiboken6", "Pillow", "pyinstaller")
LICENSE_NAMES = ("license", "copying", "notice", "authors")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: collect_licenses.py OUTPUT_DIRECTORY")
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    copied = 0
    for package in PACKAGES:
        distribution = importlib.metadata.distribution(package)
        package_output = output / f"{distribution.metadata['Name']}-{distribution.version}"
        for relative in distribution.files or ():
            name = Path(str(relative)).name.lower()
            if not any(name.startswith(prefix) for prefix in LICENSE_NAMES):
                continue
            source = Path(distribution.locate_file(relative))
            if not source.is_file():
                continue
            package_output.mkdir(parents=True, exist_ok=True)
            target = package_output / Path(str(relative)).name
            if target.exists():
                continue
            shutil.copy2(source, target)
            copied += 1
    if copied == 0:
        raise RuntimeError("No dependency license files were found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
