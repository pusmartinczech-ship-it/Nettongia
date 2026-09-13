# Portable OCR acceptance checkpoint

Date: 2026-09-12  
Application version: 0.18.0  
Stage: OCR package II (in progress)

## Verified in this checkpoint

- Full local regression suite: 131 passed, 21 conditional/platform fixtures skipped.
- Focused OCR/distribution/self-test suite: 19 passed.
- Golden PDF audit: passed; no-op save changed 0 pixels on all three pages and
  the representative edit changed 0 pixels outside its allowed regions.
- The real OCR self-test passed from a freshly unpacked source copy below
  `/tmp/OpenPDF Čistý balíček žluťoučký kůň`.
- `TESSDATA_PREFIX` was removed and the test process `PATH` excluded
  `/usr/bin/tesseract`; Czech, Slovak, Polish, German and English were still
  discovered from the private bundle and English OCR executed successfully.
- Missing and modified model files are rejected.
- An unavailable language produces a controlled worker error and no output PDF.
- Immediate OCR cancellation kills the worker, removes a Unicode workspace,
  emits no stale result and remains safe when cancel is requested again.
- OCR assets remain below the enforced 32 MiB budget (29,202,278 bytes including
  the integrity manifest).

## Windows gate prepared but not yet executed

The Windows workflow now creates a portable ZIP, records OCR/unpacked/ZIP byte
counts, applies 32 MiB / 850 MiB / 400 MiB ceilings, extracts the candidate into
a Czech Unicode path, rejects a runner with a system `tesseract.exe`, and
requires the packaged `ocr_execution` self-test to pass.

This stage must not be marked complete until that workflow runs successfully on
Windows. No new release version or Windows binary was created here.
