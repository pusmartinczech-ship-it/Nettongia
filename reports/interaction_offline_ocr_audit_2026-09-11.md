# Interaction and offline OCR audit — 2026-09-11

## Scope

This checkpoint addresses three regressions reported during manual review:

1. OCR must work from the distributed application without downloading language
   data or requiring a machine-wide Tesseract installation.
2. Page order should be changed by dragging a concrete thumbnail in the left
   Pages panel, like PowerPoint.
3. Selecting an original embedded image must not rotate, rasterise, or lower its
   quality before the user commits a transform.

The stable application version remains `0.18.0`; this is an interaction and
distribution checkpoint pending a real signed Windows acceptance run.

## Implementation evidence

- `vendor/ocr/tessdata` contains `ces`, `slk`, `pol`, `deu`, `eng` and `osd`
  models from the official `tessdata_fast` 4.1.0 tag.
- `vendor/ocr/SHA256SUMS.json` and `tools/verify_ocr_bundle.py` validate every
  model and license file before OCR is offered.
- Runtime lookup is limited to the frozen `ocr` directory or source
  `vendor/ocr`; inherited `TESSDATA_PREFIX` values cannot redirect the editor
  to external data.
- The PyMuPDF/MuPDF OCR engine receives the verified `tessdata` path directly.
- Page thumbnails use Qt `InternalMove`; the model move is translated into one
  PDF page move with bookmark/link and pending-object remapping.
- Source-image overlays are transparent interaction proxies over MuPDF's page
  pixels. A click changes selection only. A committed move, resize or rotation
  creates the existing undoable delete-plus-placement state.
- Original self-contained image streams are reused for orthogonal rotations;
  arbitrary angles use a lossless PNG replacement.

## Verification

| Check | Result |
|---|---:|
| Full suite with the three supplied PDFs (`OPENPDF_TEST_SAMPLES`) | **139 passed** |
| Suite without optional supplied fixtures | **118 passed, 21 skipped** |
| Offline OCR bundle verification | **passed** |
| Real OCR smoke test in `--self-test` | **passed** |
| OCR model manifest corruption rejection | **passed** |
| Thumbnail move order and Undo/Redo | **passed** |
| Click-before-transform source-image history invariant | **passed** |
| JPEG stream and quarter-turn preservation | **passed** |
| Golden PDF no-op audit | **passed; 0 changed pixels** |
| Golden PDF representative edit outside allowed regions | **0 changed pixels** |

The supplied 27 MiB / 798-page EPLAN reference is included in the fixture run.
No source image is rewritten merely because its overlay was clicked, and no
test observed an automatic first-click rotation or quality change.

## Remaining release gate

The Linux environment cannot produce or sign the Windows executable. The
checked-in PyInstaller/Inno Setup workflow and free SignPath Foundation request
remain ready, but the next release gate is still a clean Windows 10/11 run of
the frozen self-test, OCR, page-thumbnail drag, image transforms, save/reopen,
and installer/uninstaller checks.
