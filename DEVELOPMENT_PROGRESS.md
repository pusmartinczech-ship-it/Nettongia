# Nettongia PDF Editor development progress

Updated: 2026-09-20

## Update-check development checkpoint (version remains 0.19.0)

- Added background GitHub stable-release checking on startup, limited to one
  attempt per 24 hours, plus a manual Help action and persistent opt-out.
- No document data is sent; normal connection metadata reaches GitHub. No
  downloads, installation or replacement of the running application occurs.
- GUI results are delivered through queued QObject slots, offline automatic
  failures are silent, late results after close are ignored, and repeated
  notifications for the same version are suppressed.
- Corrected the unfinished implementation's initialization placement (it was
  accidentally inside recovery writing instead of window construction).
- Targeted update/i18n tests: **25 passed**. Full regression in the isolated
  update-check worktree: **158 passed, 14 skipped, 7 failed**; all seven
  failures are missing external PDF fixtures, not assertion failures.
- Missing fixtures: Test_Word_PDF.pdf, KS_Teil_3_2_04_ROB-KUKA_KL.pdf,
  0015_001.pdf. OCR assets were restored from a local copy and verified against
  the repository's SHA-256 manifest before the full run.
- Golden audit passed: zero changed pixels on all three unchanged pages and
  zero changed pixels outside allowed edit regions.
- No new ZIP or version bump. Windows verification and full fixture regression
  remain pending. Annotations/comments are not implemented by this checkpoint.
- Next: restore original test PDFs, rerun the complete suite and Windows gate,
  then prepare a separately versioned portable candidate.

## 0.19.0 page-rotation and portable-publication candidate

- Added 90-degree page rotation in both directions through the Page menu,
  thumbnail context menu and `Ctrl+Shift+Left` / `Ctrl+Shift+Right`.
- Rotation is covered by Undo/Redo and materializes pending editor objects into
  the rotated working snapshot so content cannot drift away from its page.
- Corrected visible-coordinate mapping for text and source images on pages that
  already carry `/Rotate`; added regression coverage for visible geometry,
  replacement text, upright inserted text and GUI Undo/Redo.
- The website now exposes one portable ZIP download only and explicitly invites
  user feedback, bug reports and improvement proposals. The unverified Stripe
  test link remains unpublished.
- Local targeted result: **45 passed, 7 fixture-dependent skipped**; website
  validation passed. The full suite, Windows package gate, final ZIP SHA-256 and
  public release are still pending, so this candidate is not yet complete.
- Next step: run the complete regression and golden checks, then build and test
  the portable ZIP on GitHub Windows before publishing tag `v0.19.0`.

## Completed checkpoint: Nettongia branding and bettong icon

- Renamed the visible product identity to **Nettongia PDF Editor** across the
  application, dialogs, translations, diagnostics, README, Windows executable,
  portable archive, installer and GitHub artifacts.
- Added a teal-and-amber application icon whose mascot is a stylized bettong
  with upright ears, long tail and strong hind feet beside a PDF page. The SVG
  source and 16/32/48/64-pixel Windows ICO are checked in, together with a
  matching file-action icon family.
- Preserved the Inno Setup AppId and the established OpenPDF Editor settings,
  recovery and local-diagnostic locations, so an upgrade does not orphan
  user preferences or recoverable work.
- Commit `799eef1be04c2d4605ce2f85b76bf1a00a60e4f2` passed GitHub-hosted
  Windows Server 2022 workflow run 34862626578: frozen application self-test,
  **135 source tests passed / 21 conditional tests skipped**, pixel-exact golden
  no-op audit, 60-cycle / 180-render GUI memory soak and the full clean-portable
  OCR matrix including Unicode paths and cancellation.
- Golden audit changed zero pixels on all three no-op pages and zero pixels
  outside declared regions for the representative edit. Memory steady-state
  growth was 8,140,800 bytes, with no leaked temporary workspaces.
- Unsigned GitHub artifact `Nettongia-PDF-Editor-Windows-unsigned` is
  173,337,618 bytes; artifact SHA-256:
  `fdcafa0323c7ca9f4e79f2f6b1370007ed5bfa6c0f816e9e43a652d4d464af21`.
  Portable ZIP SHA-256:
  `2e2022e6a107ea678e7e5aa79d000baf5c9d78bcc85915917da389b6e843649e`.
  Installer SHA-256:
  `4f6d9dd6862a73783be4ead26dc5d0f12ca1e89abf17e592fc2c106a59b3b8aa`.
- Version remains 0.18.0. Stage 8 remains open because SignPath signing and
  acceptance on clean Windows 10 and Windows 11 have not yet been completed.

## In-progress stage: integration candidate

- Draft pull request 1, commit `987bf89ae931094b1d506b0b8716cd907b0d125c`,
  passed GitHub-hosted Windows Server 2022 workflow run 34779226429.
- The complete source regression passed: **133 tests passed, 21 conditional
  tests skipped**. The frozen application self-test and clean portable OCR
  acceptance matrix also passed.
- The final golden-PDF audit passed. All three no-op pages were pixel exact and
  the representative edit changed zero pixels outside its declared regions.
- The repeated GUI memory gate completed 60 open/render/zoom/scroll/close
  cycles and 180 page renders with real Windows working-set measurements.
  Steady-state RSS growth was 7,999,488 bytes; post-warmup peak growth was
  10,147,840 bytes. No temporary inspection or render workspace remained.
- The gate exposed and fixed two false-success risks: command-line Qt deferred
  deletions are now drained by the harness, and unavailable Windows RSS
  measurements fail instead of being accepted as zero. It also exposed and
  fixed a real Windows cleanup race by closing native QProcess handles before
  removing an inspection workspace.
- Unsigned integration artifact SHA-256:
  `abbf7599fa2109fa08b521988b7c1e89eae87e236aff8cf1d532c0dc95b7432d`.
- Version remains 0.18.0 and stage 8 remains open. The candidate is unsigned;
  SignPath approval/configuration and acceptance on clean Windows 10 and
  Windows 11 installations have not yet been completed.

## Completed stage: portable OCR acceptance

- GitHub-hosted Windows Server 2022 run 34759413759 completed successfully at
  commit `3ac5fa777f66b621ecbf79ae6c1502a0587d0093`.
- The real frozen portable ZIP was extracted below
  `Čistý OCR balíček žluťoučký kůň` with no system Tesseract available and no
  inherited `TESSDATA_PREFIX`. All seven packaged checks passed: bundle
  integrity, isolated OCR, controlled missing-language failure, tamper
  detection, process cancellation, cleanup and Unicode paths.
- Windows source regression: **133 passed, 21 conditional tests skipped**.
  Packaged PDF open/render/save verification, OCR execution and anonymized
  diagnostic export also passed.
- Measured package sizes: 220,891,741 bytes unpacked, 100,693,707 bytes for the
  portable ZIP and 29,202,291 bytes of OCR assets. The enforced budgets are
  850 MiB, 400 MiB and 32 MiB respectively.
- Unsigned GitHub artifact SHA-256:
  `e4f1745031b37269bd363d06f4421e152e3598662995d575e1d726a7edac9639`.
  Portable ZIP SHA-256:
  `0591e73126b9b95423fff6ad9d6c017a10545a49304783a2c63e6b8b149b16a3`.
  Installer SHA-256:
  `b6380621a3df2c0c4eee71d8f0102d5984d2886ff9ee8c2e96fd4ff104222168`.
- Version remains 0.18.0. This completes stage 7 only; SignPath signing and the
  clean Windows 10/11 integration matrix remain stage-8 release gates.

- Windows Server 2022 validation on 2026-09-13 now builds the portable ZIP and
  Inno Setup installer successfully; the packaged self-test and the complete
  source suite passed (**132 passed, 21 conditional tests skipped**).
- The first clean portable OCR invocation returned a non-zero exit code before
  the acceptance matrix could be confirmed. Stage 7 therefore remains open.
  Workflow run 34748344611 is the latest completed evidence.
- Commit `2065b2608d43fe9cd3b69e8e5fe5a4950e57203d` adds deterministic capture of
  the packaged OCR acceptance JSON. Its Windows run 34748573829 is queued for
  a hosted runner; no failure has been reported for that diagnostic run yet.

- Added `--ocr-acceptance`, a non-GUI packaged acceptance mode that executes an
  isolated OCR worker and validates success, a missing-language failure,
  tamper detection, Unicode paths and hard process cancellation from the exact
  frozen application tree.
- The clean Windows workflow now requires this complete packaged matrix instead
  of relying only on the smaller general self-test.
- Built a real Linux PyInstaller onedir package and copied it below a Czech
  Unicode path with system Tesseract excluded from `PATH`. All seven packaged
  OCR acceptance checks passed. Measured sizes were 713,527,631 bytes unpacked,
  284,267,372 bytes compressed and 29,202,278 bytes of OCR assets, all within
  the configured budgets. This deliberately broad development environment is
  larger than the clean release environment.
- Current local result: **132 passed, 21 conditional tests skipped**; the golden
  PDF audit remained pixel exact with zero changes outside allowed regions.
- Added deterministic failures for a missing or modified bundled language
  model and a real cancellation regression that verifies child-process and
  Unicode-workspace cleanup without applying a result.
- Added a real OCR execution test below a path containing Czech diacritics while
  an invalid inherited `TESSDATA_PREFIX` is present; the application replaces it
  with its verified private data directory.
- The Windows pipeline now creates a portable ZIP only after its packaged
  self-test, records unpacked/ZIP/OCR byte counts, and enforces explicit 850 MiB,
  400 MiB and 32 MiB ceilings.
- Added a clean-extraction Windows gate in `Čistý OCR balíček žluťoučký kůň`.
  It rejects a runner with system Tesseract and requires real OCR execution from
  the extracted package.
- Earlier local result: **131 passed, 21 conditional tests skipped**; the golden
  PDF audit stayed pixel exact. A clean source copy also completed the real OCR
  self-test from a Czech Unicode path with `/usr/bin/tesseract` excluded from
  `PATH`.
- Linux/source coverage for these paths is complete. The stage remains open
  until the clean portable acceptance gate is actually executed on Windows;
  no Windows release version is created by this checkpoint.

## Completed checkpoint: bounded anonymized diagnostics

- Added a 256 KiB / 512-record local operation log with an explicit allowlist
  of events and scalar fields. Free-form errors, paths, names, PDF content, and
  document metadata cannot be written to it.
- Added **Help > Export anonymized diagnostics** with a mandatory pre-export
  inventory of every data category included and excluded.
- Added an atomic, integrity-checked ZIP containing only five fixed JSON files:
  manifest, system versions, current editor counters, bounded operation records,
  and crash-log presence/coarse size.
- Rotated evidence from the most recent abnormal run to `crash.previous.log`
  before starting a new empty crash log. Raw crash content is never placed in
  the diagnostic ZIP.
- Added the export to the packaged `--self-test` and localized its workflow for
  all 21 interface languages.
- Full supplied-fixture suite: 147/147 passed; local suite: 126 passed with 21
  conditional platform/fixture tests skipped; golden PDF audit remained exact.

## Completed checkpoint: page deletion and context menus

- Added a dedicated thumbnail-list widget that handles an unmodified `Delete`
  key only when the Pages pane has focus, so object deletion on the page view
  remains independent.
- Refactored page deletion into an indexed, confirmation-protected operation;
  deleting from a thumbnail now targets that exact page and preserves the
  existing page-remapping and Undo/Redo invariants.
- Added right-click menus for thumbnails and page objects. Text, original
  images, inserted images, and signatures expose only actions valid for their
  object type.
- Added focused GUI tests for page-key deletion, thumbnail-menu targeting,
  image-menu actions, and Undo restoration. The local suite now passes 121
  tests with 21 platform/fixture-dependent skips.

## Completed checkpoint: offline OCR and direct PowerPoint-style interactions

- Added the complete, integrity-pinned `tessdata_fast` 4.1.0 bundle to the
  repository and frozen application. OCR now executes with the PyMuPDF/MuPDF
  embedded engine and never looks for a system Tesseract installation or
  downloads language data.
- Added a real OCR smoke test to the packaged self-test and an integrity check
  for every model and license file.
- Added internal drag-and-drop for a concrete page thumbnail in the left Pages
  panel. The final PDF order and all pending page-scoped edits are remapped in
  one undoable operation.
- Made original PDF images clickable in the normal page view. Selection alone
  leaves history, bytes, pixels and quality unchanged; the first committed
  transform preserves original streams and 90-degree rotations where possible.
- Fixed the previous first-click rotation/rasterisation regression and added
  JPEG byte-fidelity and pixel-level interaction tests.
- Stable version remains 0.18.0 until a real signed Windows installer passes
  the clean Windows 10 and Windows 11 acceptance matrix.

## Completed checkpoint: Windows distribution foundation

- Recorded a dependency policy that keeps the mature PDF and GUI stacks under
  compatible open-source terms instead of replacing them with unsafe bespoke
  parsers, renderers and codecs.
- Added a pinned Windows input set, a deterministic PyInstaller specification
  and an Inno Setup installer that includes the corresponding source archive.
- Added a packaged non-GUI self-test covering PDF creation, open, render, save,
  verification and OCR language discovery.
- Added checked-in offline OCR language data (Czech, Slovak, Polish, German,
  English and orientation) plus automatic collection of dependency licenses.
- Added a GitHub-hosted Windows build and opt-in SignPath Foundation signing
  request. Signing remains gated on project-owner approval and repository setup.
- Stable version remains 0.18.0 until the produced Windows installer passes the
  clean Windows 10 and Windows 11 acceptance matrix.

## Completed checkpoint: golden PDF visual regression

- Added deterministic three-page fixture generation covering text, vector
  graphics, raster images, annotations, page rotation and transparency.
- Added reusable RGB render and pixel-diff primitives with changed-pixel ratio,
  mean/max channel delta, changed bounding box and allowed-region enforcement.
- A no-op save must remain pixel exact on every fixture page. Representative
  text/image edits must change pixels, but zero changed pixels may occur outside
  their declared regions.
- Added a standalone `tools/golden_pdf_audit.py` command and compact JSON/Markdown
  reports under `reports/golden_pdf_0.17.0`.
- Added no-op pixel checks for Word, scan and technical PDFs, including sampled
  pages from the 27 MiB / 798-page supplied document.
- Golden subset: 8/8 passed. Full suite with every supplied PDF enabled:
  126/126 passed.

## Completed checkpoint: refactoring V

- Added `OcrCoordinator`, which owns OCR job preparation, child-process state,
  cancellation, result validation and temporary-workspace cleanup.
- The coordinator now returns validated immutable PDF bytes instead of exposing
  a temporary output path to `MainWindow`.
- OCR outcomes carry document generation and content revision. Results from an
  older document or revision are discarded before they can enter Undo/Redo.
- Kept language selection, progress UI, translated messages and history updates
  as UI policy in `MainWindow`.
- Reduced `main_window.py` from 5,565 to 5,492 lines and added three focused
  coordinator/regression tests.
- Full result with Tesseract and all supplied PDFs enabled: 118/118 passed.

## Completed checkpoint: refactoring IV

- Added `TileRenderCoordinator`, which owns isolated high-detail rendering,
  timeout handling, process cancellation, result validation and workspace cleanup.
- Tile results carry their immutable render context and are discarded if the
  document revision, page, zoom or preview scale has changed in the meantime.
- Kept visible-area selection, the bounded 96 MiB LRU cache and QPixmap/UI work
  in `MainWindow`.
- Preserved the `_tile_task` compatibility view and legacy runnable-cancellation
  path used by established stress tests.
- Reduced `main_window.py` from 5,664 to 5,565 lines and added three focused
  coordinator/regression tests.
- Full result: 98 passed, 17 conditional/platform tests skipped (115 collected).
  The tile subset also passed 21/21 with all three supplied technical PDFs enabled.

## Completed checkpoint: refactoring III

- Added `InspectionCoordinator`, which owns the isolated compatibility process,
  its 45-second timeout, result validation and temporary-workspace cleanup.
- Added immutable inspection context/outcome values. A delayed result is now
  accepted only when it belongs to the currently active document generation.
- Preserved compatibility reporting, translated status messages and save-risk
  acknowledgement as UI policy in `MainWindow`.
- Preserved the `_inspection_process` compatibility view used by established
  GUI and integration tests.
- Reduced `main_window.py` from 5,774 to 5,664 lines and added three focused
  coordinator/regression tests.
- Full result: 95 passed, 17 platform-dependent tests skipped (112 collected).

## Completed checkpoint: refactoring II

- Added `DocumentWriteCoordinator`, which owns the complete lifecycle of the
  isolated save/compression process: request identity, launch, cancellation,
  result validation and temporary-workspace cleanup.
- Added immutable `DocumentWriteOutcome` values so `MainWindow` receives one
  terminal result instead of inspecting mutable process fields.
- Kept translated prompts, progress UI and post-save document decisions in
  `MainWindow`; the coordinator has no application-specific UI policy.
- Preserved the `_write_process` compatibility view used by established GUI
  tests while removing the underlying process state from `MainWindow`.
- Reduced `main_window.py` from 5,875 to 5,774 lines and added two focused
  coordinator tests, including cleanup after job-preparation failure.
- Full result: 92 passed, 17 platform-dependent tests skipped (109 collected).

## Completed checkpoint: refactoring I

- Added `DocumentSession`, an independently testable model for document identity,
  save targets, history save points, document generations and content revisions.
- Routed document activation, close, edit branching, undo/redo and save completion
  through the session model.
- Replaced five mutable background-write identity fields with one immutable
  `DocumentWriteContext`, which owns the output path, source generation,
  content revision, compression mode and confirmation policy.
- Preserved the existing `MainWindow` attribute interface for compatibility with
  UI code, recovery files and existing tests.
- Added five focused regression tests, including the case where a background save
  finishes after a newer edit and the document must remain marked as unsaved.
- Full result: 90 passed, 17 platform-dependent tests skipped (107 collected).

## Architecture map

The remaining responsibilities in `main_window.py` are grouped into these seams:

1. Window construction, actions, menus, localization and theme.
2. Recovery scheduling and restoration.
3. Document inspection and compatibility reporting.
4. Search, outline and thumbnail navigation.
5. Preview and isolated tile rendering.
6. Text editing and history commands.
7. Visual object placement and transformation.
8. Printing and OCR orchestration.
9. Isolated document-write process and progress UI.

`DocumentSession` is dependency-free. Document writes, compatibility checks,
high-detail tile rendering and OCR now use signal-based coordinators. The main
remaining risk is visual fidelity across unusual PDF structures rather than
worker-process lifecycle state.

## Completed checkpoint: safe copies and compatibility summary

- Added **File > Save a Copy** (`Ctrl+Alt+S`) using the existing isolated,
  validated and atomic document-write coordinator.
- Kept the active document path, normal Save target, saved history point,
  crash-recovery data and unsaved-work marker unchanged after a copy succeeds.
- Added a deterministic three-tier compatibility classification: safe,
  possible changes and high risk.
- Classified signed digital signatures, XFA, JavaScript and PDF portfolios as
  high risk; other recognized rewrite-sensitive structures remain possible
  changes.
- Added a green/yellow/red summary to the compatibility dialog while retaining
  the detailed feature and representative-render report.
- Added localized action and status labels for all 21 interface languages and
  direct regressions for document identity, copied content and all three tiers.

## Next stage

Complete stage 8: configure the approved free SignPath Foundation project,
sign the Windows candidate, then run the signed portable package and installer
acceptance matrix on clean Windows 10 and Windows 11 systems together with the
long-duration memory and final golden-PDF gates. Do not create a new release
version unless every material gate passes.

## Completed release candidate: 0.18.0 page and source-image editing

- Added Page menu commands and keyboard shortcuts for moving the current page
  one position earlier or later as a single Undo/Redo operation.
- Remapped pending source-text edits, inserted text, signatures, inserted
  images and source-image deletions to their logical page after every move.
- Verified preservation of page content, bookmarks and internal link targets.
- Added an explicit original-image edit mode. Selecting a source image creates
  a reversible replacement that uses the existing move, proportional resize
  and free-rotation controls.
- Preserved alpha masks, orthogonal source rotation and the source stacking
  position below later text. Conversion before the first transformation is
  pixel-identical in the deterministic regression fixture.
- Added a 32-million-pixel safety limit for interactive source-image extraction.
- Full development-tree result: 132 tests passed with all supplied reference
  PDFs enabled. Golden visual audit: passed, zero unexpected changed pixels.
