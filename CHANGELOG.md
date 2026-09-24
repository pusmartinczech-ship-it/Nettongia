# Changelog

## 0.21.0

- Introduced a modern liquid-glass-inspired desktop appearance with layered
  translucent surfaces, subtle gradients, rounded controls and clearer hover,
  pressed and selected states in both light and dark themes.
- Added a centered welcome card with direct New PDF and Open actions while
  keeping the existing compact toolbar usable on narrower windows.
- Added the new official Nettongia bettong mascot to the welcome card, with a
  clear PDF mark on the document it holds and a transparent background.
- Preserved the established Pages/Tree navigation on the left and the
  collapsible Comments, Forms and Fill & Sign tools on the right.
- Added regression coverage for mascot loading, welcome-card positioning and
  the transition between the empty state and an opened document.

## 0.20.0

- Fixed a native Windows crash when a signature field was clicked in Forms
  Preview mode. The temporary signature is inserted into the existing page
  scene without replacing its active `QGraphicsProxyWidget` hierarchy.
- Applied the same in-place scene update to committed Fill & Sign signatures;
  PDF state, recovery and Undo history are updated without destroying the
  originating proxy control during its event dispatch.
- Forms Preview now renders the typed or drawn test signature inside its field
  while keeping it temporary, resettable and outside both PDF bytes and Undo.
- Added synchronously flushed local crash tracing for every visual-signature
  stage, Qt diagnostics and native Python fault stacks. Signature text and PDF
  content are excluded, clean exits remove the trace, and an abnormal run is
  retained as `crash.log` / `crash.previous.log` for diagnosis.
- Added native AcroForm signature fields and required-field flags, including
  canonical field widgets and appearance streams for compatible PDF readers.
- Added separate Forms Edit and Preview modes. Preview values are temporary and
  never modify the PDF or its Undo history.
- Added a Fill & Sign tool with live on-page controls, reversible value changes,
  one-step form clearing and visual signatures fitted into signature fields.
- Clearly distinguishes image-based visual signatures from certificate-based
  digital signatures; native signature fields remain cryptographically unsigned.
- Replaced the Comments and Forms tabs in the left navigation area with an
  Acrobat-style collapsible tool rail on the right. Pages and the document
  tree remain on the left; the right rail is ready for future tools.
- Added creation and deletion of native AcroForm text fields, check boxes,
  drop-down lists and list boxes. New fields support names, tooltips, default
  values, choice lists, multiline text, read-only state, rotated pages and
  complete Undo/Redo.
- Added independent validation of the canonical AcroForm field tree, page
  widgets and appearance streams so created fields remain interactive in
  compatible PDF readers after saving.
- Added permanent rectangular redaction from the Edit menu. Selected text,
  image pixels, vector content, links, comments and form fields are removed
  before a black replacement area is written, with confirmation and Undo/Redo.
- Added regressions that inspect extracted text, PDF object streams, rendered
  pixels, rotated-page geometry and overlapping interactive objects after
  redaction.
- Added a Forms sidebar for standard AcroForm text fields, check boxes, radio
  buttons, combo boxes and list boxes, including protected read-only fields,
  page navigation, Undo/Redo and saved-value preservation.
- Fixed update checks for the published v0.19.0 public beta and other official
  prereleases while continuing to reject drafts and malformed metadata.
- Made the default local and GitHub Windows build portable-only; installer
  generation is now an explicit legacy opt-in.
- Added native PDF sticky-note comments from a page-placement mode and standard
  yellow highlights from the text-object context menu.
- Added a Comments sidebar for existing and new annotations, including page
  navigation, comment editing and deletion.
- Made comment insertion, editing, deletion and text highlighting reversible
  Undo/Redo operations, with correct geometry on rotated pages and all 21 UI
  languages.
- Added clockwise and counter-clockwise page rotation from the Page menu, the
  thumbnail context menu and keyboard shortcuts.
- Made page rotation one reversible history operation that keeps page content,
  pending text, images, signatures and deletions together.
- Corrected text and image geometry on PDFs whose pages already carry a PDF
  rotation value; newly inserted text remains upright in the visible page.
- Changed the public website to offer only the portable Windows ZIP and added a
  clear invitation for bug reports and improvement ideas.
- Added a tag-only GitHub release gate that publishes the portable ZIP only
  after Windows regression, golden-PDF, memory and clean OCR checks pass.

## Privacy-safe diagnostics checkpoint after 0.18.0

- Added a local JSON-lines operation log capped at 256 KiB / 512 records. It
  stores only allowlisted event names, coarse outcomes, counters, page indexes,
  and a random per-start session identifier.
- Added **Help > Export anonymized diagnostics**. A mandatory review lists the
  included and excluded data before the user chooses a ZIP destination.
- The diagnostic ZIP contains fixed JSON members for versions, non-identifying
  system characteristics, current editor counters, bounded operation history,
  and crash-log presence/size only.
- PDF bytes, rendered pages, document content and metadata, file names and
  paths, recent-file history, user/computer/network identifiers, raw exception
  messages, and raw crash logs are excluded by construction.
- Preserved the latest abnormal-run crash log across the following clean start
  as `crash.previous.log`; its content remains local and is never exported.
- Added privacy, bounding, archive-integrity, UI-review, crash-rotation, and
  packaged self-test regressions.

## Follow-up interaction controls after 0.18.0

- Added `Delete` handling to the focused thumbnail list. It removes the exact
  selected page, keeps the last-page guard, remaps page-scoped editor state,
  and remains one Undo/Redo operation.
- Added PowerPoint-style right-click menus to page thumbnails with move earlier,
  move later, and delete commands for the thumbnail under the pointer.
- Added right-click menus to page objects. Text objects offer Edit text and
  Delete selected text; source images offer Edit original image and Delete
  image; inserted images and signatures offer Delete image.
- Right-click selection is non-mutating until a command is chosen. All object
  and page commands use the existing history, recovery, and atomic-save paths.
- Added GUI regressions for thumbnail Delete, page context-menu targeting, and
  image context-menu actions.

## Interaction and offline OCR checkpoint after 0.18.0

- Bundled the complete Czech, Slovak, Polish, German, English and orientation
  OCR models in `vendor/ocr`, with a checked-in SHA-256 manifest and license
  notice. Source and Windows builds now use the same verified assets; no
  Tesseract install or model download is required.
- Added PowerPoint-style internal drag-and-drop for individual page thumbnails.
  The PDF page order, bookmarks, internal links and pending editor objects are
  updated as one undoable operation.
- Made embedded images directly selectable in the normal page view. A click is
  now non-mutating; an image is promoted only when a move, resize or rotation
  is committed.
- Preserved original JPEG/PNG streams and orthogonal PDF rotations for the
  first edit, avoiding the previous automatic turn and quality loss. Arbitrary
  angles use a lossless raster replacement and remain undoable.
- Added regressions for offline OCR execution, thumbnail drag order/Undo and
  click-before-transform image fidelity.

## Distribution checkpoint after 0.18.0

- Added a non-GUI `--ocr-acceptance` command that tests the isolated worker from
  the frozen application, including controlled failure, tamper detection,
  Unicode paths and cancellation; the clean Windows workflow now requires it.
- Added a clean portable-ZIP OCR acceptance gate, Unicode-path and cancellation
  regressions, explicit missing/corrupt-model failures and distribution size
  budgets. Windows execution is still required before this stage is complete.
- Added a version-pinned PyInstaller onedir build and Inno Setup installer.
- Added a packaged `--self-test` mode for PDF rendering, saving, verification
  and bundled OCR discovery.
- Added checked-in Czech, Slovak, Polish, German and English OCR language data
  plus an orientation model; the OCR engine remains the one embedded in the
  pinned PyMuPDF/MuPDF build.
- Added automatic license collection, corresponding-source packaging and an
  explicit dependency policy for AGPL/LGPL-compliant distribution.
- Added a GitHub-hosted Windows build with opt-in free SignPath Foundation
  signing after project-owner approval.

## 0.18.0

- Added reversible page reordering from the Page menu and keyboard shortcuts,
  preserving bookmarks, internal links and every pending editor object.
- Added direct editing of original embedded images: select one, then move,
  proportionally resize or freely rotate it with Undo/Redo support.
- Preserved the original image's transparency, orthogonal rotation and stacking
  below existing text when it is converted into an editable object.
- Extended crash recovery, isolated rendering and document writing for the new
  original-image replacement metadata while retaining older recovery support.
- Added pixel-exact visual regression coverage for conversion before the first
  deliberate transformation.
- Expanded the complete automated suite to 132 tests and repeated the golden
  PDF audit with zero unexpected changed pixels.

## Development checkpoint after 0.17.0

- Added **Save a Copy** (`Ctrl+Alt+S`) through the isolated, validated and atomic
  writer without changing the active path, Save target, history marker or
  unsaved-work state.
- Added green / yellow / red compatibility summaries for safe documents,
  possible rewrite changes and high-risk PDF structures while preserving the
  detailed inspection report.
- Added localized labels for all 21 interface languages and focused regression
  coverage for copy semantics and compatibility classification.

## 0.17.0

- Added process-isolated Tesseract OCR for the current page or complete document, using only locally installed language models.
- Added invisible searchable OCR words directly to original image-only pages without rasterising or visually replacing the source page; pages with an existing text layer are skipped.
- Preserved links, bookmarks, page structure, existing editor overlays, and pixel-identical page appearance while making recognized text searchable and available to the editor.
- Added cancellable non-modal OCR progress, child-process crash isolation, strict job/result validation, output SHA-256 verification, representative output renders, and atomic result handling.
- Applied each successful OCR operation as one undoable, crash-recoverable document state change and discarded late results if the open document changed.
- Made inserted images selectable, movable, proportionally resizable, and freely rotatable after placement with the same visible controls used for signatures.
- Persisted inserted-image rotation through Undo/Redo, crash recovery, isolated tile rendering, printing, and PDF output while retaining compatibility with older recovery files.
- Added localized OCR controls and status messages for all 21 interface languages.
- Expanded the complete automated suite to 102 tests.

## 0.16.0

- Moved production high-detail tile rendering from a `QThreadPool` task into a short-lived helper process, preventing a native PDF rasteriser failure from terminating the editor.
- Kept one immutable source snapshot per open document instead of copying a large PDF into every render request.
- Reused the strict recovery ZIP + JSON schema for unsaved text and image mutations while excluding visual signatures that remain resolution-independent overlays.
- Added a 20-second timeout, hard process cancellation for obsolete page/zoom/scroll requests, bounded tile and descriptor counts, and automatic workspace cleanup.
- Validated every returned tile's rectangle, dimensions, stride, exact byte count, constrained filename, and SHA-256 digest before creating a GUI pixmap.
- Preserved the immediate memory-bounded page preview and 96 MB LRU cache; failed or timed-out detail work leaves the preview usable.
- Added isolated worker, modified-payload rejection, unsaved-edit fidelity, GUI responsiveness, and supplied-reference regressions.
- Expanded the complete automated suite to 97 tests.

## 0.15.0

- Added an asynchronous document compatibility inspection in a separate process, so a native-library failure during the scan or representative preflight renders cannot terminate the editor.
- Scanned every page for signed and unsigned signature fields, AcroForms/XFA, annotations, attachments, optional-content layers, JavaScript, portfolios, tagged-PDF structure, encryption, and unusually large page geometry.
- Added **File > Document compatibility** with localized progress, result, and warning messages in all 21 interface languages.
- Added an explicit confirmation before writing a document that contains a signed digital signature field.
- Reopened every newly written temporary PDF and rendered its first, middle, and last pages before atomically replacing the destination file; failed validation leaves an existing target untouched.
- Added strict, non-executable JSON job/result validation, a 45-second process timeout, cancellation on document replacement/close, and automatic temporary-workspace cleanup.
- Added repeatable inspection latency and parent/child memory soak tooling plus real-document regression coverage for the supplied 798-page EPLAN, KUKA, and LV-15D PDFs.
- Expanded the complete automated suite to 91 tests.

## 0.14.1

- Reduced high-detail tile rendering to a single PyMuPDF document handle when a page has no pending content changes; edited snapshots release their redundant source handle before rasterisation.
- Removed queued tile jobs that have become obsolete after scrolling, zooming, page changes, or document closure, preventing delayed work from accumulating behind the active worker.
- Retained safe, revision-keyed tiles across page and zoom navigation in the existing 96 MB LRU cache, making return navigation effectively immediate without allowing stale content to appear.
- Added cache hit, miss, and eviction counters for repeatable development profiling.
- Added a reusable end-to-end rendering and memory profiler with JSON output.
- Added regressions for the single-document fast path, queued-task cleanup, and tile reuse after page navigation.
- Profiled the supplied 798-page EPLAN reference: representative detail passes improved from 0.38–0.39 seconds to 0.19–0.23 seconds, cached return detail from 0.37 seconds to 0.008 seconds, and observed peak RSS fell by about 13 MiB.
- Re-ran the complete suite with all supplied large and problematic PDFs: 82 tests passed.

## 0.14.0

- Added progressive tiled rendering for large and highly zoomed PDF pages.
- Displayed a complete preview capped at 2.5 million pixels, then refined the visible region with target-resolution 768 × 768 pixel tiles in a background worker.
- Prioritized tiles near the viewport centre and prefetched one tile around the visible area for smoother scrolling.
- Added cancellation and generation checks so page changes, edits, and rapid zooming cannot display stale tiles.
- Added a 96 MB least-recently-used tile cache and removed off-screen graphics items to keep memory usage bounded.
- Preserved unsaved text, image, and deletion changes in both the preview and high-resolution tiles; signatures remain sharp interactive overlays.
- Stress-tested rapid navigation across pages 10, 399, 798, and 2 of the supplied 798-page EPLAN document; the final view refined in 1.77 seconds with a 13.5 MB tile cache.
- Added clipped-render equivalence, cancellation, high-zoom integration, cache-bound, and tile-size regression coverage.
- Expanded the complete automated suite to 76 passing tests.

## 0.13.2

- Prevented the rendered page from disappearing while the left mouse button is held on blank page space.
- Retained explicit Python references to the base page and interactive scene layers for their complete scene lifetime, avoiding premature PySide wrapper disposal.
- Extended the existing real-document interaction regression to verify page visibility before mouse release.
- Added a press-hold-release regression that deliberately avoids the local wrapper reference which previously masked the fault in tests.
- Reproduced the former failure in 20 of 20 isolated processes and verified the corrected path in 20 of 20 isolated processes.
- Expanded the complete automated suite to 73 passing tests.

## 0.13.1

- Removed the distracting full-page repaint after an ordinary click on blank page space.
- Kept the disappearing-page integrity safeguard, but limited repainting to cases where the base page layer is hidden or the scene bounds are damaged.
- Added a regression test covering both the no-repaint path and automatic repair of a hidden base layer.
- Expanded the complete automated suite to 72 passing tests.

## 0.13.0

- Moved Save, Save As, and PDF compression into a separate helper process so PyMuPDF cannot monopolize the GUI interpreter during long writes.
- Isolated native-library failures from the editor process and added a cancellable, non-modal progress window.
- Passed immutable editor snapshots through the existing strictly validated, non-executable ZIP + JSON format; no pickle or executable job data is used.
- Preserved edits made while a save is running: the completed file contains its original snapshot, while newer work remains visibly unsaved and recoverable.
- Prevented document replacement, closing, and concurrent writes until the active write has completed or been cancelled.
- Changed normal Save from expensive global duplicate-stream analysis to fast level-2 garbage collection, while retaining physical removal of replaced content and atomic destination replacement.
- Reduced the supplied 27 MB / 798-page EPLAN full-save test from more than three minutes to 2.43 seconds, with identical rendered pixels on pages 1, 399, and 798.
- Added regression tests for process-backed saves, GUI responsiveness, concurrent edits, cancellation, compression results, fast-save options, and physical text removal.
- Expanded the complete automated suite to 71 passing tests and repeated the deterministic 100-file public PDF corpus audit without a crash or timeout.

## 0.12.0

- Added masked password entry, retry after an incorrect password, and safe cancellation when opening encrypted PDFs.
- Added password handling when importing pages from another protected PDF.
- Kept passwords out of application and recovery state and explicitly reports that edited copies are saved without password protection.
- Added complete password-dialog translations for all 21 interface languages.
- Rejected zero-page PDFs during engine loading before they can reach thumbnail, outline, or page rendering code.
- Added a process-isolated, timeout-protected public PDF corpus audit with exact source repository commits and per-file JSON results.
- Audited 100 deterministic random public files from PDF.js, veraPDF, and qpdf: 99 completed every operation, one malformed zero-page file was safely rejected, and none crashed or timed out.
- Expanded the complete automated suite to 62 passing tests.

## 0.11.1

- Preserved each source text run's PDF baseline direction when replacing or formatting vertical, reversed, and obliquely rotated text.
- Kept fitting, multiline insertion, underlining, movement, and resizing aligned with the original text direction.
- Added the normalized baseline direction to crash-recovery data while retaining compatibility with recovery files created by version 0.11.0.
- Verified the fix on the supplied 798-page EPLAN reference and added regression coverage for 90°, 270°, and arbitrary 33° text.
- Expanded the complete automated suite to 58 passing tests, including the full inline-edit close path.

## 0.11.0

- Added automatic recovery of confirmed unsaved work after a crash or power loss.
- Moved recovery writes to a debounced background worker so large PDFs remain responsive.
- Added atomic recovery-file replacement, SHA-256 integrity checks, strict ZIP member validation, and a non-executable JSON manifest.
- Added restoration of text edits, text boxes, page structure, images, image removals, visual signatures, current page, zoom, and the established save target.
- Added preservation and reporting of damaged recovery files for diagnostics.
- Added a persistent, deduplicated list of the ten most recently opened or saved PDFs, including stale-entry removal and a clear-list command.
- Split **Save** (`Ctrl+S`) from **Save As** (`Ctrl+Shift+S`) while retaining a safe first-save copy for newly opened source PDFs.
- Added complete translations for the new controls and messages in all 21 interface languages.
- Expanded automated coverage to 54 tests, including recovery round trips, cancellation safety, archive validation, UI restoration, recent-file persistence, and standard Save behavior.

## 0.10.4

- Prevented the rendered page from disappearing when a text edit was confirmed by clicking between text frames.
- Deferred scene interaction-mode changes until the matching pointer release and verified the base page layer after every gesture.

## 0.10.3

- Replaced page scenes atomically and kept rendering safe while an inline text editor is active.

## 0.10.2

- Preserved source font family, weight, style, and explicitly selected size during direct text editing.
- Kept the selected text target active while toolbar formatting controls are used.

## Earlier preview releases

- Added direct text editing and movable text boxes, page and image management, visual signatures, printing and preview, compression, search, light/dark/automatic appearance, a lazy Acrobat/EPLAN-style document tree, main-page scrolling, and 21 interface languages.
- Added progressive thumbnails, background search, render memory limits, atomic PDF saves, and local crash diagnostics for large and malformed documents.
