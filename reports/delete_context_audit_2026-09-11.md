# Page deletion and context-menu audit

Date: 2026-09-11  
Scope: OpenPDF Editor 0.18.0 follow-up interaction checkpoint

## Result

The new interaction paths are accepted for the current public-beta tree.

- `Delete` in the focused Pages thumbnail list removes the exact selected page.
- The last-page guard and confirmation dialog remain active.
- Page deletion remaps page-scoped source edits, inserted text, images,
  signatures, and image deletions through the existing state engine.
- Page deletion is one history entry and is restored by Undo.
- A thumbnail context menu selects the clicked page and offers move earlier,
  move later, and delete.
- A page-object context menu distinguishes text, original images, inserted
  images, and visual signatures. It exposes only valid actions for the target.
- Opening a menu and selecting its target does not rewrite the PDF or create a
  history entry. A chosen action follows the existing recovery and atomic-save
  path.

## Verification

- Full source and supplied-fixture suite: **142 passed, 21 skipped**.
- GUI interaction subset: **16 passed**.
- Packaged-style self-test: **passed** (`pdf_open_render`, `pdf_save_verify`,
  and bundled offline OCR discovery).
- Golden PDF audit: **passed**.
  - no-op save: 0 changed pixels on all three pages;
  - representative edit: 10,222 changed pixels;
  - changed pixels outside allowed regions: 0.

## Review notes

The thumbnail Delete handler is intentionally limited to an unmodified Delete
key while the Pages list owns focus; the page canvas keeps Delete for its
selected text or visual object. Context menus are suppressed during inline
editing, placement/deletion modes, OCR, and document writes so a menu cannot
race an active mutation. Windows-only frozen-build acceptance remains a
separate release gate because this environment is Linux.
