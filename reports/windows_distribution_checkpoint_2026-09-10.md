# Windows distribution checkpoint — 2026-09-10

## Outcome

The source tree now contains an auditable Windows build path but no Windows
binary is declared released yet. Stable application version remains 0.18.0.

## Implemented

- PyInstaller onedir specification with isolated worker entry points retained.
- Exact direct Python package versions for the Windows build input.
- Packaged `--self-test` for PDF open, render, save and post-save inspection.
- Private bundled OCR directory discovery before PyMuPDF loads.
- Tesseract runtime staging with `ces`, `slk`, `pol`, `deu`, `eng` and `osd`.
- OCR file SHA-256 manifest and Tesseract/Leptonica license retrieval.
- Dependency license collection from the installed Python distributions.
- Inno Setup installer with per-user installation support.
- Complete corresponding-source ZIP inside the installed application tree.
- GitHub-hosted Windows build and optional SignPath Foundation request.

## Verified in the development environment

- Source self-test: passed.
- Full regression suite: 132 passed, 3 Windows-only tests skipped.
- Distribution specification and mandatory-file tests: passed.

## Gates before release 0.19.0

1. Put this exact source tree in a public AGPL Git repository.
2. Run the Windows workflow and retain its dependency and self-test manifests.
3. Install the unsigned candidate on clean Windows 10 and Windows 11 virtual
   machines and execute the manual acceptance matrix in `SIGNING.md`.
4. Apply for SignPath Foundation, connect the repository and configure its
   artifact policy.
5. Re-run the workflow, verify the Authenticode signature and timestamp, then
   repeat both clean-machine tests on the signed installer.
6. Only after those gates pass, change the stable version and publish binaries
   together with the matching source archive and checksums.

## License decision

Replacing MuPDF, Qt, image codecs and Tesseract with original implementations
was rejected. It would not eliminate licensing—the new code would also need a
license—and would create a much larger security and document-fidelity burden.
The selected route keeps a small set of established components under compatible
open-source terms and automates attribution plus corresponding-source delivery.
