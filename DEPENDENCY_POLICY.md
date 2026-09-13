# Dependency and license policy

This document records the engineering decision for the Windows distribution. It
is not legal advice; every public release must still be checked against the exact
versions and files it contains.

## Decision

OpenPDF Editor will not replace its PDF engine, GUI toolkit, font/image codecs or
OCR engine with unreviewed home-grown implementations merely to remove third-party
names. Implementing and auditing those components would take years and would make
document corruption and security defects more likely. All software, including our
own, has a license. The useful goal is a small, auditable dependency set whose
licenses fit the release model.

| Component | Role | Distribution choice | Reason |
|---|---|---|---|
| PyMuPDF / MuPDF | PDF parsing, editing, rendering | Keep under AGPL-3.0 | The complete editor is already distributed under AGPL-3.0-or-later with corresponding source. A proprietary build would require an Artifex commercial license. |
| PySide6 / Qt | Windows GUI | Keep dynamically linked under LGPLv3/GPL terms | The onedir build keeps Qt DLLs as separate replaceable files and ships the applicable notices and license files. |
| Pillow | Imported image decoding and transforms | Keep for now | Its permissive HPND-style license does not impose copyleft or a commercial fee. Removal is only worthwhile if profiling proves a meaningful size reduction. |
| Tesseract / Leptonica | Offline OCR | Use the OCR engine embedded in the pinned PyMuPDF/MuPDF build and ship the checked-in `tessdata_fast` models | No Tesseract executable or system installation is required. The model files are integrity-pinned to the official `tessdata_fast` 4.1.0 tag and their Apache notice is shipped with the source and application. |
| PyInstaller | Windows freezing | Build tool | Its bootloader exception permits distributing applications built with it; its notices are collected into the package. |
| Inno Setup | Installer | Build tool | Used to create a per-user-capable Windows installer. |

## Release requirements

1. Ship `LICENSE`, `NOTICE.txt`, `THIRD_PARTY_NOTICES.md` and license texts found
   in the exact installed Python distributions.
2. Include the complete corresponding source archive, build specification,
   pinned direct dependencies and build-environment manifest in every installer.
3. Keep Qt shared libraries separate. Do not statically link or prevent a user
   from replacing those libraries for debugging/modification.
4. Publish the same source archive beside every binary release and retain it for
   at least the period required by the applicable licenses.
5. Run `OpenPDFEditor.exe --self-test result.json` on the packaged tree before
   compiling the installer.
6. Review the generated `BUILD_ENVIRONMENT.txt` and installed `licenses/`
   directory before signing.

## What “own libraries” still means here

Application-specific safety logic remains ours: atomic file replacement,
validated worker protocols, crash recovery, page/object transformation rules,
compatibility classification and the packaged self-test. These are the places
where custom code improves the editor without recreating mature standards stacks.
