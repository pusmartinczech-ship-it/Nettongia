# Independent-style technical audit — OpenPDF Editor 0.18.0

Date: 2026-09-10

## Scope and independence limitation

This is an evidence-based adversarial review performed separately from the
implementation pass, but not an external third-party certification. The same
development environment was used. A public 1.0 release should still receive
hands-on testing by unrelated users on clean Windows computers.

## Verdict

**Overall: 8.1 / 10 — strong public beta, not yet a fully supported 1.0 product.**

| Area | Score | Finding |
| --- | ---: | --- |
| Functional coverage | 9.0 | Editing, OCR, page management, image transformation, signatures, print, compression, search and recovery form a broad practical set. |
| Data safety | 9.0 | Atomic validated writes, Save a Copy, recovery and explicit signed-PDF warnings are unusually strong for a small desktop editor. |
| Stability | 8.5 | Rendering, OCR, inspection and writes are process-isolated; 132 automated tests pass. |
| Visual fidelity | 8.0 | Golden no-op saves are pixel-exact and representative edits remain local. Source-image promotion is pixel-exact for transparency, orthogonal rotation and overlaid text. |
| Performance | 8.0 | Large-document rendering is bounded and cached. Moving one page in the 798-page EPLAN file took about 2.1 seconds, which can briefly pause the GUI. |
| PDF compatibility | 7.0 | Common and industrial PDFs are covered well, but arbitrary affine image transforms, unusual inline images, XFA, portfolios and certified PDFs remain difficult. |
| User interface | 7.5 | The new functions are discoverable in Page and Image menus and have shortcuts, but thumbnail drag-and-drop and numeric geometry entry are still absent. |
| Maintainability | 6.5 | Worker coordinators improved separation, but `main_window.py` remains large and localization is manually maintained. |
| Distribution readiness | 5.5 | A reproducible signed Windows executable/installer and clean-machine test matrix are still missing. |

## Evidence collected

- Complete automated suite: **132 passed** with all supplied reference PDFs enabled.
- Golden PDF audit: **passed**; no-op save changed **0 pixels** on all three pages.
- Representative edited page: **0 pixels changed outside the allowed regions**.
- Original transparent image with 90-degree source rotation and later text:
  promotion to editable state changed **0 pixels** before deliberate movement.
- Page reordering preserved content order and updated a bookmark destination.
- Supplied 798-page EPLAN PDF: 798 pages and all 28,971 outline entries remained;
  one adjacent middle-page move took approximately 2.1 seconds and the first,
  middle and last pages rendered successfully afterward.

## Principal remaining risks

1. Source images using shear, perspective-like affine matrices or unusual inline
   encodings need a broader real-world corpus. The editor supports ordinary and
   orthogonally rotated occurrences, not arbitrary image skew controls.
2. Extracting an embedded image turns it into a PNG-backed editable replacement.
   Appearance is preserved, but file size and original JPEG/color-profile
   representation can change. Images above 32 million pixels are rejected for
   safety rather than risking excessive GUI memory.
3. Page reordering is synchronous. It is fast for ordinary files but briefly
   pauses the interface on the 798-page engineering sample.
4. Text remains run-based rather than paragraph-based; complex shaping and font
   subsets can still reduce fidelity.
5. There is no signed installer, reproducible Windows build pipeline or external
   clean-machine beta evidence yet.

## Release recommendation

Release 0.18.0 as a public beta. Before calling the editor 1.0, isolate page-tree
mutations, add thumbnail drag-and-drop with multi-page selection, add numeric
object geometry, build and sign a reproducible Windows package, and run an
external beta against a substantially larger PDF corpus.
