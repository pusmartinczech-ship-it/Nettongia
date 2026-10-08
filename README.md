# Nettongia PDF Editor 1.0.0

Nettongia PDF Editor is an offline Windows desktop application for genuine PDF content editing. It physically removes selected source text and deleted images before writing the new page content; it does not merely cover the old objects with annotations.

Edited horizontal text now reflows inside its frame instead of silently
shrinking to fit one line. When a longer replacement needs more lines, the
frame grows downward within the page while retaining the selected font size.
The resize handle can then be used to choose a different width and reflow.
Consecutive lines from the same uniformly formatted PDF text block are opened
as one paragraph; line-end hyphenation is removed when the following line
continues with a lower-case letter. Lists, tables and mixed-format blocks stay
separate to avoid merging unrelated content.
Vertical and freely rotated source text keeps its original direction and uses
the established non-wrapping behavior.

### Update checking

On startup the editor checks GitHub's latest stable release in the background,
at most once per 24 hours. Disable this in **Help > Automatically check for
updates (GitHub)** for fully offline operation. **Help > Check for updates...**
always permits a manual check. Offline failures do not interrupt editing;
manual checks report when the service is unavailable. A new release is announced
once per version, with an option to open its GitHub release page. Nothing is
automatically downloaded or installed and your portable copy is never replaced.

This optional request sends no PDF content, filenames, paths or diagnostics.
GitHub receives normal connection information, including your IP address and a
generic application user-agent. The last check time, last announced version and
enabled setting are stored locally with the existing application preferences.
Disabling checks also suppresses notifications from any request already running.
The update feature is included in version 0.20.0.

### Comments and text markup

Use **Comments > Add comment...** or `Ctrl+Alt+M`, then click the page and enter
the note text. Nettongia writes a standard native PDF sticky-note annotation,
not a flattened picture. The new **Comments** tab lists both newly created and
existing annotations in the right tool panel; double-click an entry to open its page and location, or
right-click it to edit its comment text or delete it.

Right-click source or inserted text and choose **Highlight text**, **Underline text**
or **Strike out text** to add a native PDF annotation. Multi-line source text
is marked along each line rather than across the blank space between lines.
Comments, edits, deletions and text markup are single Undo/Redo operations,
remain visible in other compatible PDF
readers, and are included when the document is saved. The workflow is
translated in all 21 interface languages.

### Permanent redaction

Choose **Edit > Permanently redact area...** or press `Ctrl+Shift+R`, then drag
a rectangle over sensitive page content and confirm the operation. Nettongia
physically removes intersecting text, image pixels, vector content, links,
comments and form fields, then fills the selected area in black. The operation
is reversible with Undo/Redo until the document is saved.

Redaction applies only to the selected area on the current page. It does not
remove another occurrence elsewhere in the document, document metadata or
attachments. A confirmation dialog states this scope before the change is
made. Pages containing unapplied redaction annotations are rejected to avoid
silently applying marks that the user did not select in Nettongia.

Version 0.19.0 adds reversible page rotation. Rotate the selected page left or right from the **Page** menu, the thumbnail context menu, or the `Ctrl+Shift+Left` / `Ctrl+Shift+Right` shortcuts. The page contents, pending text, images and visual signatures rotate together, and Undo/Redo restores the complete earlier state. Rotated source pages now expose their text and image selection geometry in the visible orientation, so editing remains aligned after a quarter turn.

The reversible page reordering and direct transformation of images already embedded in a PDF from version 0.18.0 remain available. Drag a page thumbnail to a new position in the left **Pages** panel, just as in PowerPoint; bookmarks, internal links and pending editor objects follow their logical page. Click an embedded image directly to select it, then move, resize or freely rotate it with the same controls used for inserted images. The optional **Image > Edit original image** command is useful when the page contains overlapping objects and limits selection to source images. Selecting an original image is non-mutating: its PDF stream and pixels remain untouched until a deliberate transform is committed, including transparency, existing orthogonal rotation and text drawn above the image.

The left sidebar now contains only page thumbnails and the document tree.
Comments and Forms live in a collapsible Acrobat-style tool rail on the right;
click a vertical tool icon to open its panel and click it again, or use the
arrow in the panel header, to return to the compact rail. This right rail is
the home for additional document tools added in future versions.

Use **Forms > Create form field...**, `Ctrl+Alt+F`, or the plus button in the
right Forms panel to create a native interactive text field, check box,
drop-down list, list box or signature field. Configure its name, tooltip,
default value, choices, required state and other properties, then drag its
rectangle directly on the page. Multiline and read-only fields are supported,
and fields with the same name intentionally share their value according to the
AcroForm standard. Creation and deletion participate in Undo/Redo and remain
editable in compatible PDF readers after saving.

In the Forms panel, select a field and use **Label** to edit its descriptive
tooltip for screen readers. Use the ↑ and ↓ buttons to set the Tab traversal
order among fields on the same page; this order is stored in the PDF and can be
undone. **Check form** reports missing labels, missing explicit Tab order and
basic AcroForm structure or appearance problems. It is a focused form check,
not a full PDF accessibility certification.

The Forms panel has separate **Edit** and **Preview** modes. Preview provides
live controls directly on the page and keeps all test entries temporary, so the
PDF and Undo history are not changed. The separate **Fill & Sign** tool uses the
same on-page controls for real values saved into the PDF, supports Undo/Redo and
can clear editable values in one reversible operation. Existing AcroForm text
fields, check boxes, radio buttons, combo boxes and list boxes are supported;
read-only fields are identified and protected.

A visual signature can be fitted into a native signature-field rectangle, but
it is deliberately identified as an image-based visual signature. It does not
create a certificate-based digital signature and the native `/Sig` field stays
cryptographically unsigned. Certificate-based signing is a separate operation
described below. Creation of radio-button groups, XFA forms and push buttons is
not included.

The Pages panel also supports an unmodified **Delete** key for the selected
thumbnail. Right-click a thumbnail for move-earlier, move-later, and delete
commands, or right-click an object on the page for object-specific actions.
Text objects offer **Edit text** and **Delete selected text**; source images
offer **Edit original image** and **Delete image**; inserted images and visual
signatures offer **Delete image**. Opening a menu or selecting its target does
not create a history entry; choosing a command uses the same undoable state and
recovery path as the toolbar and menus.

Version 0.17.0 added process-isolated optical character recognition for the current page or the complete document. Image-only and mixed-content pages receive an invisible searchable text layer while their original page pixels, links, bookmarks, and document structure remain intact. Existing PDF text is retained and overlapping OCR results are ignored. The OCR result is validated and applied as one undoable document change. Recognized lines are now grouped into editable blocks: double-click a block and edit it with the normal text tools. Committing an OCR edit clears the corresponding source pixels locally before drawing the replacement, so the scanned lettering does not remain underneath it.

Inserted images are now interactive after placement. Click an image to select it, drag it to move it, use the lower handle to resize it, and use the upper handle to rotate it freely. Geometry and rotation survive Undo/Redo, crash recovery, tile rendering, printing, and saving.

Version 0.16.0 moves production high-detail tile rasterisation into a dedicated helper process. A malformed page or native rasteriser failure can no longer terminate the editor while it refines a zoomed view. Jobs use a bounded, non-executable ZIP + JSON state package; returned RGB data is accepted only after validating its dimensions, exact byte length, filename, and SHA-256 digest. A 20-second timeout and deterministic cancellation discard obsolete work while the existing preview remains usable.

Version 0.15.0 adds a process-isolated compatibility inspection. After a document opens, a separate helper scans its structure and performs low-memory preflight renders of the first, middle, and last pages while the editor remains responsive. A crash in that inspection process is reported without terminating the editor. The result is available from **File > Document compatibility**.

Existing signed digital signatures, forms/XFA, JavaScript, attachments, layers, portfolios, tagged structure, encryption, annotations, and unusually large pages are identified. Saving a document with an existing signed signature requires explicit confirmation. Every save is also reopened and its representative pages rendered before the completed temporary file is allowed to atomically replace the destination.

Certificate-based signatures are also listed in the collapsible **Digital
signatures** panel on the right. Validation runs in the same isolated inspection
process and reports cryptographic integrity, signed revision coverage, changes
after signing, certificate subject and issuer, validity dates, algorithms,
fingerprint and embedded timestamp status. Integrity is deliberately shown
separately from certificate trust. Trust-chain checks use the bundled CA store
without network access, so the panel explicitly states that current revocation
status was not queried and never presents a sound hash alone as a trusted
signature.

Version 0.14.1 hardens progressive tiled rendering for sustained use with large engineering PDFs. Unedited pages now use one PDF document handle instead of two, obsolete queued work is removed during rapid navigation, and revision-keyed tiles remain reusable across page and zoom changes in the bounded 96 MB LRU cache. The included profiler records preview latency, detail latency, cache behaviour, and process memory as JSON.

Large or highly zoomed pages first appear as a memory-bounded full-page preview, then the visible area is refined in 768 × 768 pixel tiles by an isolated worker process. Tiles nearest the viewport centre are rendered first and scrolling prefetches one tile beyond the viewport. Generation and revision checks ensure that cached or late worker results can never replace newer page content.

Version 0.13.2 keeps explicit lifetime references to the rendered page and its interactive graphics layers. This prevents PySide from releasing the page background while the mouse button is held on blank page space; the page now remains continuously visible from press through release, including when a click confirms an inline text edit.

Version 0.13.1 removes the distracting full-page repaint after an ordinary click on blank page space. The page-integrity safeguard introduced for malformed interaction states remains active, but now repaints only when the base page layer is actually hidden or its bounds need repair.

Version 0.13.0 moves normal saves and PDF compression into a separate helper process. Long writes no longer monopolize the Python interpreter or freeze the editor, a native PDF-library failure cannot terminate the GUI process, and the progress window offers safe cancellation. The worker receives a validated, non-executable snapshot and normal output replacement remains atomic.

Normal Save now uses fast safe object compaction and reserves expensive whole-document stream deduplication for **Compress PDF**. In the supplied 27 MB / 798-page EPLAN reference, an unchanged full rewrite dropped from more than three minutes to about 2.4 seconds on the development machine, while sample pages before and after the rewrite rendered pixel-identically.

Version 0.12.0 added password-protected PDF opening through a masked password dialog, clean retry after an incorrect password, and page import from protected PDFs. Passwords are not retained in application state. The unlocked working document and edited copies are deliberately saved without password protection, which is reported in the interface.

This version was exercised against a deterministic random sample of 100 public PDFs from the PDF.js, veraPDF, and qpdf test repositories. It fully opened, rendered, inspected, and rebuilt 99 files; the remaining intentionally malformed zero-page PDF was rejected during loading. There were no process crashes, timeouts, or post-open failures. The process-isolated audit tool and machine-readable result are included in `tools/` and `reports/`.

Version 0.11.1 preserved the original baseline direction when existing vertical, upside-down, or obliquely rotated PDF text is edited. The direction is retained in the page preview, saved PDF, and crash-recovery state, including small non-orthogonal angles commonly found in CAD/EPLAN documents.

Version 0.11.0 added automatic crash recovery and a persistent **Recent files** menu. A confirmed unsaved state is captured after a short debounce in a background worker, including page changes, original and inserted text, images, image deletions, signatures, the current page, and zoom. If the process or computer stops unexpectedly, the editor offers to restore that state on the next start.

Recovery files use a non-executable ZIP + JSON format with strict field, size, member-name, and SHA-256 integrity checks. Both recovery and normal PDF saves use atomic temporary-file replacement. The original source PDF is stored without recompression, so even the supplied 27 MB / 798-page EPLAN reference can be captured without rebuilding the PDF or blocking the interface.

The page-visibility fixes from version 0.10.4, atomic scene replacement from version 0.10.3, and font-preservation fixes from version 0.10.2 remain in place. PostScript names such as `TimesNewRomanPS-BoldItalicMT` are mapped to the correct Windows font files, a styled PDF fallback is used when an installed font is unavailable, explicitly selected point sizes are not silently reduced, and the selected text target remains active while the font toolbar is used.

The previous large-document protections remain in place: search work runs off the GUI thread, high-resolution renders have a safe pixel cap, thumbnails and the Acrobat/EPLAN-style tree are loaded lazily, malformed empty document trees are accepted, and saved PDFs use atomic temporary-file replacement.

## Main document scrolling

Move the pointer over the main PDF page and use the mouse wheel. When a zoomed page is larger than the window, the wheel first scrolls within that page. At the top or bottom edge it continues to the previous or next page. This keeps navigation natural without rendering hundreds of PDF pages at once.

## Background saving and compression

Save, Save As, and Compress PDF run in a separate process. A non-modal progress window remains visible while the document can still be read or edited. If editing continues during Save, the output contains the consistent snapshot taken when Save was pressed and the newer state remains marked with an asterisk until it is saved again.

Opening, closing, or replacing the active document is temporarily disabled until the write completes. This prevents a result from being associated with the wrong document. **Cancel** terminates the isolated worker; because the PDF target is replaced only after a complete temporary file has been written, an incomplete write cannot truncate an existing destination.

## Run on Windows

1. Install Python 3.11 or newer from python.org and enable **Add Python to PATH**.
2. Extract the complete project folder.
3. Double-click `start.bat`.
4. In a source checkout, the first start downloads the Python packages declared
   in `requirements.txt`; later starts are local. The packaged Windows ZIP and
   installer already contain their dependencies and offline OCR models.

You can also drag a PDF onto the window or pass a PDF path to `run_editor.py`.

For documents with hundreds of pages, the page list appears immediately with placeholders. Their previews are generated in short batches; the document can already be read, edited, searched, or closed while the remaining thumbnails are being filled.

## Password-protected PDFs

Open a protected PDF normally. Nettongia PDF Editor asks for its password in a masked field and allows another attempt if the password is incorrect. The same workflow is available when importing pages from another protected PDF.

The password is used only to unlock the source and is not retained in the editor state or recovery data. The working document is decrypted in memory, and ordinary edited or recovered copies are saved without password protection. The status bar reports this behavior after a protected document is opened.

Use **File > Add password protection...** to create a separate AES-256 encrypted
copy of the current working document, including pending edits. The password must
contain at least eight characters, is confirmed before saving, and is passed only
to the isolated write process; it is not written to settings, recovery snapshots
or diagnostics. When a protected PDF has been opened, **File > Remove password
protection...** becomes available and writes a separate unencrypted copy. Neither
operation changes the identity or unsaved state of the document currently open in
the editor.

## Compare PDF documents

Choose **File > Compare with PDF...** to compare the current working document
with another PDF. Pending text, image, page and signature edits are materialized
inside an isolated process, so the comparison reflects what would be saved
without first changing the active file. Password-protected comparison files are
supported through the normal masked password prompt.

The result lists every page as identical, changed, present in only one document,
or using different page geometry. Selecting a row shows the current and selected
pages side by side, plus a third preview where changed pixels are highlighted in
red. Rendering is bounded for unusually large pages, and changing the active
document while comparison is running safely discards the stale result.

## Headers, footers, and watermarks

Choose **Page > Header, footer & watermark...** to add left, center, or right
header and footer text and an optional diagonal text watermark. The dialog
shows a live page preview and supports `{page}`, `{pages}`, `{date}`, and
`{title}` tokens. Decorations can target all, odd, or even pages, optionally
skipping the first page. Font, size, color, margin, watermark angle, opacity,
and foreground/background placement are configurable.

Nettongia tags only the content streams it creates. Opening the same dialog
later therefore allows those decorations to be replaced or removed without
deleting the page's original text, graphics, or images. Applying and removing
decorations are normal document edits and support Undo/Redo.

## Voluntary development support

Nettongia remains free and does not restrict features based on financial
support. After five successful saves of genuinely changed documents, the
editor may show one optional support message. It is never displayed at startup.
Choosing **Maybe later** postpones it for at least ten more successful saves;
choosing **Don't ask again** disables it permanently. The same support link is
always available in **Help > Support development...**.

Only the bounded save counter and reminder preference are stored in local
application settings. No document information is collected, and the approved
Stripe support page is opened only after an explicit user click.

## Public PDF corpus audit

The reproducible audit tool is `tools/pdf_corpus_audit.py`. It launches a separate process for every PDF, applies a per-file timeout, renders the first, middle, and last pages, extracts text and image objects, walks a bounded portion of the outline tree, rebuilds the complete document, reopens it, and renders the rebuilt result. Native-library crashes therefore cannot terminate the coordinator or hide later results.

The checked release used 40 random PDF.js files, 35 random veraPDF conformance files, and 25 random qpdf files from the exact repository commits recorded in `reports/pdf_corpus_audit_0.13.0.json`. A controlled rejection is distinct from a crash: the only rejected file in the final run contains no pages and cannot be edited as a PDF document.

## Recent files

Choose **File > Recent files** to reopen one of the ten most recently opened or saved PDFs. Opening the same file moves it to the top instead of creating a duplicate. The list is stored only in the local application settings and can be cleared directly from the submenu. If a file has been moved or deleted, selecting it removes the stale entry and reports the missing path.

## Save, Save As, and Save a Copy

Use **File > Save** or **Ctrl+S** for the normal save command. A PDF opened from disk is not overwritten automatically: its first Save opens **Save As** with an `_edited.pdf` suggestion. After a target has been chosen, later Save commands write atomically to that target. Use **File > Save As** or **Ctrl+Shift+S** whenever you want another copy or filename.

Use **File > Save a Copy** or **Ctrl+Alt+S** for an independent safety copy. It uses the same isolated, validated, atomic write path, but never changes the active document path, its normal Save target, the saved history point, or the unsaved-work marker.

## PDF document tree

When a PDF contains bookmarks or an EPLAN navigation structure, the left sidebar opens on the **Tree** tab. Expand and collapse its branches just as in Acrobat. A single click navigates to the linked page; EPLAN device links also center and enlarge the destination area. The **Pages** tab remains available for thumbnail navigation.

The tree is lazy: only visible portions are read into the view. The supplied 798-page EPLAN reference contains 28,971 entries in nine levels, including page and device trees, and can be browsed without creating all entries at once. PDFs without a document tree simply keep the Pages tab active.

## Edit text

1. Open a PDF.
2. Move the pointer over text. A blue outline identifies the editable text object.
3. Double-click it and type directly on the PDF page.
4. Press **Ctrl+Enter** or click outside the editor to confirm. Press **Esc** to cancel.
5. Use the text toolbar to choose the installed font, size, bold, italic, underline, and text color.
6. Drag a selected text frame to move it, or drag its lower-right handle to resize the frame. Press **Delete** to remove it.
7. Use **File > Save As** to create the edited PDF.

Entering an empty replacement deletes the selected source text. Editing currently operates on one visual text run (usually one line or one styled part of a line) at a time. Automatic reflow of surrounding PDF paragraphs is not performed in version 0.18.0.

## Optical character recognition (OCR)

Choose **Page > OCR current page** or **Page > OCR document**, then select one of the models bundled in `vendor/ocr/tessdata`. OCR runs in a separate process and can be cancelled without changing the open document. It handles image-only pages as well as scans mixed with native PDF text, ignores OCR words that overlap existing text, adds an invisible searchable layer, and reports the number of recognized pages and words.

OCR text is also editable. Hover or double-click a recognized line just like
ordinary PDF text; replacements support reflow, formatting and Undo/Redo. The
original scan image remains embedded when a line is edited. The invisible
recognized text is removed, and a transparent overlay repairs only pixels
identified as scanned lettering before inserting real PDF text. Original line
breaks remain editable. Gradients and surrounding texture are retained where
possible; lettering over detailed photographs may still need manual cleanup.
New OCR results keep each recognized line at its scan coordinates, so editing
one table row does not reflow other rows into the same cell. To benefit from
this change in a document processed by an older version, reopen the original
scan and run OCR again before editing.

Release and checkpoint archives already contain all OCR models and never need
network access at runtime. After a clean Git checkout, run
`python tools/fetch_ocr_assets.py` once. It downloads only the files from the
pinned `tesseract-ocr/tessdata_fast` 4.1.0 source and rejects any file whose
SHA-256 differs from `vendor/ocr/SHA256SUMS.json`. The Windows workflow performs
this source-preparation step automatically before testing and packaging.

The OCR engine is the one exposed by the pinned PyMuPDF/MuPDF build; the
language models and their SHA-256 manifest are shipped inside the source tree
and Windows package. Neither a Tesseract installation nor an internet
connection is needed for recognition. A source checkout and a packaged build
therefore use the same offline assets. The editor lists only models it can
actually verify. OCR never uploads the document.

Recognition accuracy depends on scan resolution, contrast, rotation, and the selected language model. Keep the source file when processing archival or certified documents.

## Transform inserted images

After inserting an image, click it once. Drag the image itself to change its position, drag the lower handle to scale it proportionally, or drag the upper handle to rotate it. The transformed outer bounds are constrained to the page. **Delete image**, the Delete key where applicable, and Undo/Redo continue to work with the selected object.

The same direct-click workflow applies to images that were already present in
the PDF. The first click only selects and outlines the source image; it does not
rewrite, rotate, rasterise or lower its quality. Moving, resizing or rotating
and releasing the mouse creates one undoable replacement. JPEG streams and
orthogonal PDF rotations are kept in their original form whenever possible;
only an arbitrary-angle transform needs a new lossless raster surface.

## Rendering performance profile

Run `python tools/render_profile.py document.pdf --output profile.json` to exercise first, middle, and last pages at high zoom, revisit the first page, stress scrolling, and record timing, tile-cache counters, and resident memory. Release measurements are included in `reports/render_profile_0.14.1.json` and `reports/render_profile_0.16.0.json`; the latter records the intentional process-isolation latency and lower parent-process memory footprint.

Run `python tools/inspection_soak.py document.pdf --cycles 12 --output inspection.json` to repeat the isolated compatibility scan, sample parent and child resident memory, enforce a steady-state growth limit, and verify that temporary workspaces are removed.

## Document compatibility

Open **File > Document compatibility** after loading a PDF. The check runs automatically and does not block editing. Its summary uses a three-level status: green for a normal document with no recognized risky structures, yellow for features that can change during rewriting, and red for high-risk structures such as signed digital signatures, XFA, JavaScript, or PDF portfolios. The detailed feature list and representative-render result remain below the summary. A signed digital signature still requires explicit confirmation before saving because any content change invalidates it.

This check cannot guarantee that every PDF consumer will preserve every proprietary extension. Keep the original file when working with certified, archival, accessibility-tagged, layered, portfolio, XFA, or JavaScript-enabled documents.

## Add new text

Choose **Insert > Add text box**, click the `T+` toolbar icon, or press **Ctrl+Alt+T**. Drag a rectangle on the page, or click once to create a standard-size box, and type directly into it. New text supports multiple lines and the same font, style, color, move, resize, Delete, Undo, and Redo controls as edited source text. It is written as real, searchable PDF text.

## Find text

Choose **Edit > Find** or press **Ctrl+F**. Enter text in the search strip and use its up/down buttons to move through every result in the document. The current result is highlighted directly on the page and the counter shows its position. **F3** moves to the next result, **Shift+F3** to the previous one, and **Esc** closes the search strip.

Search uses the current working version of the PDF, including unsaved edited and newly inserted text. The search runs in a worker thread, so a large document does not freeze the editor; starting a new query cancels the previous result. Image-only scans still require OCR before their text can be found.

## Create a new PDF

Choose **File > New PDF** or press **Ctrl+N**. Select a standard paper size (A3, A4, A5, Letter, or Legal) or enter a custom size, choose portrait or landscape orientation, and set the initial number of blank pages.

The new document is shown as `Untitled.pdf *` until it is saved for the first time. Use **File > Save As** to choose its location and filename.

## Zoom controls

- Use the high-contrast magnifying-glass buttons to move through standard zoom levels.
- Enter an exact percentage in the zoom box.
- Use the horizontal-arrow button to fit the page width to the window.
- Very large pages are automatically capped at a safe pixel budget (32 million RGB pixels). The displayed percentage is the effective zoom, so a request such as 400% on an A0 sheet may be reduced while smaller pages can still reach 400%.

## Printing

Choose **File > Print**, click the printer icon between Save and Undo, or press **Ctrl+P**. Nettongia PDF Editor first shows its own complete print preview. Use the printer button in that window to open the editor-owned printer settings dialog. It lists the installed printers and supports all pages, the current page, or a selected page range; available driver properties remain accessible through the printer settings. Because this dialog belongs to Nettongia PDF Editor, its title no longer inherits `Python` from `pythonw.exe`. Unsaved text, image, page, and signature changes are included in both the preview and the print job. Vector drawings and text outlines are retained when printing ordinary PDF pages, including to a PDF printer; pages with annotations or form widgets use raster rendering to keep their appearance. Saving or extracting pages as PDF keeps the original PDF drawing objects.

## Pages

- **Insert > Add blank page** adds a blank page of the same size after the current page.
- **Insert > Insert pages from PDF** inserts pages from another PDF after the current page. Enter `1-` for every page or a selection such as `1,3-5`.
- In the Pages sidebar, select several thumbnails with `Ctrl` or `Shift`, then use **Page > Extract selected pages** to save those pages to a separate PDF. Pending edits on those pages are included; the open document stays intact.
- **Page > Split PDF into parts** saves consecutive groups of a specified number of pages as numbered PDFs in a chosen folder. Existing output files are never overwritten.
- **Page > Crop pages** sets independent margins in millimetres for the current page, selected thumbnails, or every page. Cropping follows the visible orientation of rotated pages and is non-destructive: hidden content remains in the PDF.
- **Page > Resize pages** changes the physical page size using A4/A3/A5, Letter, Legal, current-size, or custom dimensions. Choose proportional content fitting to avoid distortion, or change only the centred canvas while preserving the content's visual size. The operation can target the current page, selected thumbnails, or the whole document.
- **Page > Delete current page** removes the selected page.
- Select a thumbnail in the left **Pages** panel and press **Delete** to remove
  that exact page; right-click a thumbnail for the same delete command and for
  move-earlier/move-later actions.
- Page operations and all pending content changes participate in Undo/Redo.

## Images

- Choose **Image > Insert image**, select PNG, JPEG, BMP, TIFF, or WebP, set the width, and click the desired page position.
- Choose **Image > Edit original image**, then click an image already contained in the PDF. It becomes selectable and can be moved, proportionally resized, or freely rotated. Press **Esc** before selecting to cancel.
- Click an image already contained in the PDF to select it directly. Use **Image > Edit original image** when you want an explicit source-image selection mode; press **Esc** before selecting to cancel.
- Choose **Image > Delete image** and click an outlined image to remove it.
- Right-click an image or signature on the page for its available object
  actions. Right-click editable text for **Edit text** or **Delete selected
  text**.

## Reorder pages

Drag a page thumbnail in the left **Pages** panel to the desired position, or use **Page > Move page earlier/later** / **Alt+Shift+Up/Down**. Each move is one Undo/Redo step. Existing bookmarks and internal links are retained, and unsaved text, images, signatures and deletions are remapped to the page they belong to.
- The same delete mode can remove an inserted visual signature.
- Original images are removed from the page content when the PDF is saved.

## Visual signatures

1. Choose **Insert > Add visual signature** or click the signature icon.
2. Draw a signature with the mouse/pen, or switch to **Type signature**.
3. Set its width and rotation angle, then confirm.
4. Click the desired position on the PDF page. Press **Esc** to cancel placement.

After insertion, click a signature to select it:

- drag the signature itself to move it,
- drag the lower-right circular handle to resize it proportionally,
- drag the circular handle above the signature to rotate it freely,
- use Undo/Redo to step through every completed transformation.

The signature is stored with a transparent background. It is visible page content, not a certificate-based digital signature, and does not verify identity.

## Certificate-based digital signatures

Choose **Sign with certificate...** in the Forms ribbon or the right **Digital
signatures** panel. Select a PKCS#12 certificate (`.p12` or `.pfx`), enter its
password, choose an existing unsigned signature field or create a new invisible
field, and optionally provide a reason, location and contact. You can also
choose **Create a visible signature on a page** to place a certificate signature
stamp near the bottom right of a selected page. The stamp carries a signing
date, while the Digital signatures panel shows the verified certificate owner.
The visible stamp is part of the cryptographic signature, distinct from the
handwritten visual signature tool.

For a verifiable signing time, enable **Add a trusted timestamp (RFC 3161)**
and enter the HTTPS endpoint supplied by your timestamp authority. The address
is used only for that signing operation and is not remembered. The standard TSA
request sends a cryptographic digest, not the PDF itself. A bounded network
timeout prevents an unavailable service from leaving the operation waiting
indefinitely.

To include available revocation evidence, enable **Include available revocation
responses** and provide a timestamp server. The isolated signing process
contacts the OCSP/CRL endpoints advertised by the certificates; those requests
can disclose certificate identifiers to the certificate authority, but never
upload the PDF. It checks the chain against bundled public trust roots, stores
the responses in the PDF document security store (DSS), and verifies that a
signature-specific VRI entry actually refers to OCSP or CRL evidence before
publishing the signed copy. If certificate trust or revocation evidence is
unavailable, the requested copy is not published. Embedded data supports
future validation but does not guarantee long-term trust or replace renewed
archive timestamps.

Signing and post-sign verification run in a dedicated child process. The
certificate password is supplied only through that process environment and is
not written to settings, recovery data, the job descriptor or diagnostics. The
operation always writes a separate PDF and refuses to overwrite the currently
open document. Pending editor changes are materialized before signing, and the
finished copy is accepted only when its new signature passes a cryptographic
integrity check. When a timestamp was requested, its embedded token must also
be cryptographically valid. The result distinguishes a TSA certificate chain
trusted by the bundled offline store from a valid token whose chain is not in
that store; current revocation status is not queried. A failure, incorrect
password or invalid TSA response leaves an existing target untouched.

An unchanged document that already contains certificate signatures can be
signed again. Nettongia appends the new signature as an incremental PDF
revision instead of rewriting the signed bytes. Pending editor changes must be
saved or discarded first. The output is accepted only when the new signature
and every earlier signature pass cryptographic integrity verification.

## Appearance

Choose **View > Appearance** and select:

- **Automatic (system)** to follow the Windows light/dark setting,
- **Dark** to force the dark appearance,
- **Light** to force the light appearance.

The choice is remembered for the next start. Toolbar icons, button borders, selection handles, the top menu, drop-down menus, and the page workspace use separate high-contrast colors for both appearances.

## Interface language

Click the flag button at the right side of the main toolbar, or choose **View > Language**. Each language is shown with its commonly associated flag and native name. The editor detects the Windows language on first start and remembers later changes.

The included languages are English, Mandarin Chinese, Hindi, Spanish, Standard Arabic, French, Bengali, Portuguese, Indonesian, Urdu, German, Russian, Turkish, Italian, Dutch, Romanian, Hungarian, Ukrainian, Czech, Slovak, and Polish. Arabic and Urdu switch the complete interface to a right-to-left layout.

## Unsaved changes

An asterisk in the window title marks a document with unsaved changes. Before closing the application, closing the current document, opening another PDF, or creating a new PDF, the editor offers **Save**, **Discard**, and **Cancel**. Cancelling leaves the current document open. After the first **Save As**, a later Save from this prompt writes to the same file.

Choose **File > Close document** or press **Ctrl+W** to close only the active PDF while keeping Nettongia PDF Editor running.

Saved PDFs are first written beside the destination as a temporary file and then replaced atomically. If a save is interrupted, the previously existing PDF is not left truncated and temporary files are cleaned up.

## Automatic crash recovery

After a confirmed document change, Nettongia PDF Editor waits briefly for further edits and then records the latest working state on a background thread. It stores one current snapshot rather than the Undo history, so recovery remains bounded and does not render, compress, or rewrite every page. A newer snapshot atomically replaces the previous complete snapshot; an interrupted write therefore cannot damage the last usable recovery point.

At the next start, choose **Restore** to reopen the recovered state or **Discard** to remove it. Recovered work is deliberately marked as unsaved until you save the PDF. A successful save, an explicit discard, or a normal document close removes the recovery data. A damaged recovery file is not executed or silently discarded: it is renamed with a `.damaged-<date>` suffix and its location is shown for diagnostics.

For seamless upgrades, Windows recovery data remains at the established `%LOCALAPPDATA%\OpenPDF Editor\Recovery\current.openpdf-recovery`. It can contain the source document and inserted images or signatures, remains exclusively on the computer, and is never transmitted automatically.

If Windows ever terminates the GUI without an error dialog, the editor keeps a local diagnostic at the established `%LOCALAPPDATA%\OpenPDF Editor\crash.log`. A clean run leaves no log file. The diagnostic remains on the computer and is never transmitted automatically.

The raw local log also records synchronously flushed, content-free checkpoints
through visual-signature creation (dialog, rendering, PNG encoding, form-field
placement and Undo-state update), together with Qt warnings and native Python
fault traces. Signature text and PDF content are not written to these
checkpoints. This makes the final completed checkpoint usable even when Windows
terminates the process abruptly.

The most recent non-empty crash log is preserved across the next start as
`crash.previous.log`. Its raw content may contain technical paths or exception
text, so Nettongia PDF Editor never puts it in an exported diagnostic package.
After reproducing a crash, copy `crash.log` before restarting, or restart once
and collect the rotated `crash.previous.log`.

## Anonymized diagnostics

Nettongia PDF Editor keeps a local operation log at `%LOCALAPPDATA%\OpenPDF
Editor\operation-log.jsonl`. It is capped at 256 KiB and 512 records and accepts
only fixed event names, coarse outcomes, page/count values, timestamps, and a
random identifier that changes at every program start. It does not accept PDF
content, file names, paths, recent-file history, or free-form error messages.

Choose **Help > Export anonymized diagnostics** to create a small ZIP. Before a
destination is selected, the editor shows the complete included/excluded data
inventory and requires confirmation. The ZIP contains only `manifest.json`,
`system.json`, `session.json`, `operations.json`, and `crash-summary.json`.
Crash information is limited to whether a current or previous log exists and a
coarse size category; raw crash text is excluded. Nothing is uploaded or sent
automatically.

## PDF compression

Choose **File > Compress PDF** and select one of these profiles:

- **Lossless** cleans and compresses PDF objects without lowering image quality.
- **Balanced** downsamples oversized images to approximately 150 dpi and uses moderate JPEG compression.
- **Strong** downsamples oversized images to approximately 105 dpi with stronger JPEG compression.

Vector text and graphics remain sharp in all profiles. Lossy profiles are intended mainly for scans and photographs.

## Current limitations

- Interactive form filling supports standard AcroForm text, check, radio and
  choice fields. Dynamic XFA and push-button actions are intentionally not
  modified.
- Certificate signing currently supports local PKCS#12 files. Windows
  certificate-store keys, smart cards and remote signatures are not included
  yet. Sequential signatures are supported only on an unchanged signed
  revision; content editing between approval signatures is intentionally
  blocked to avoid invalidating earlier signatures.
  RFC 3161 timestamp servers are supported through a user-supplied HTTPS URL;
  TSA authentication credentials and recurring archive timestamps are not
  included. Revocation evidence requires reachable certificate-authority
  services and a chain trusted by the bundled trust roots.
- OCR requires the checked-in language bundle; both source and packaged builds use it offline, with no Tesseract installation or model download. A damaged or incomplete bundle is reported by the self-test.
- Letters converted to vector outlines cannot be treated as text.
- Deleting an original image preserves underlying page content. When the same image object is reused elsewhere, individual removal is currently blocked to protect the other copies.
- An existing cryptographic PDF signature becomes invalid after any content edit.
- Printing keeps vector paths on supported pages. Pages with annotations or form widgets and pages whose SVG representation is too large use raster rendering with the same safe memory budget as the editor view. Printing through Qt may convert text to outlines, so use Save or Extract Pages when searchable text is required in an exported PDF.

## Build a portable Windows version

Install Python 3.12, then double-click `build_exe.bat`. The
build uses `requirements-windows.lock`, verifies the five checked-in OCR models
(it never downloads them), collects dependency license files, includes the
complete corresponding source and runs the frozen executable self-test before
creating:

`dist\Nettongia_PDF_Editor_<version>-portable.zip`

The intermediate folder build remains at `dist\NettongiaPDFEditor`. Run
`dist\NettongiaPDFEditor\NettongiaPDFEditor.exe --self-test result.json` to repeat its
non-GUI open/render/save/inspection check. The GitHub workflow builds, tests and
publishes only the portable ZIP. An installer can still be built explicitly for
legacy testing with `tools\build_windows.ps1 -IncludeInstaller` when Inno Setup
6 is installed.

## Run the supplied-file tests

Install `requirements-dev.txt`, set `OPENPDF_TEST_SAMPLES` to a folder containing the supplied PDF fixtures, and run `pytest`.

Run `python tools/golden_pdf_audit.py` to perform the deterministic visual
regression audit. It verifies pixel-exact no-op saves and confirms that
representative edits change only their declared page regions. Compact JSON and
Markdown results are written below `reports/golden_pdf` by default.

## License note

Nettongia PDF Editor's application source is licensed under
**AGPL-3.0-or-later**. The complete license text is in `LICENSE`; the
corresponding source is supplied alongside released binaries. You may fork,
modify, redistribute or sell a copy under that license, provided you meet its
terms, including the applicable source and copyright-notice requirements.
The Nettongia name and mascot identify the original project; permission to use
the source code does not itself grant rights to its branding.

PyMuPDF / MuPDF is a **separate dependency** offered by its owner, Artifex,
under AGPLv3 or an Artifex commercial agreement. Nettongia does not grant an
Artifex commercial license to its own code or to PyMuPDF. A proprietary version
would require independently resolving the rights to every relevant component
and contribution. See `DEPENDENCY_POLICY.md`, `THIRD_PARTY_NOTICES.md` and
the bundled dependency licenses before publishing a binary.
