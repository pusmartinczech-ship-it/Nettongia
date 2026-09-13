# Packaged portable OCR acceptance checkpoint

Date: 2026-09-13  
Application version: 0.18.0  
Stage: OCR package II (in progress)

## Result

- Added the non-GUI `--ocr-acceptance` entry point to the frozen application.
- Built an actual PyInstaller onedir package and copied it to
  `/tmp/OpenPDF frozen – žluťoučký kůň/balíček`.
- Removed `TESSDATA_PREFIX` and used a `PATH` containing no `tesseract` binary.
- The frozen application passed all seven checks: private bundle integrity,
  absence of system Tesseract, isolated OCR execution, controlled unavailable
  language failure, modified-model rejection, process cancellation and Unicode
  path handling.
- Full source regression: 132 passed, 21 conditional/platform fixtures skipped.
- Golden PDF audit passed: no-op save changed zero pixels on all fixture pages;
  the representative edit changed zero pixels outside its allowed regions.

## Measured development package size

- Unpacked onedir: 713,527,631 bytes (budget 850 MiB).
- ZIP: 284,267,372 bytes (budget 400 MiB).
- OCR data and integrity manifest: 29,202,278 bytes (budget 32 MiB).

The Linux development package intentionally contains optional packages present
in the shared test environment and is therefore larger than the clean Windows
build should be. The measurements validate the gates, not a release size target.

## Remaining gate

The same `--ocr-acceptance` matrix must run from the clean Windows portable ZIP.
Until that happens, stage 7 remains in progress and no new release version is
created.
