# OpenPDF Editor 0.13.0 - public PDF corpus audit

Audit date: 2026-09-09  
Selection seed: `20260908`  
Per-file timeout: 20 seconds

## Result

| Outcome | Files |
| --- | ---: |
| Completed every audit stage | 99 |
| Safely rejected during validation | 1 |
| Crash, timeout, or post-open failure | 0 |
| Total | 100 |

The safely rejected PDF (`poppler-91414-0-54.pdf`) contains no pages. A zero-page
document cannot be edited, so it is rejected before thumbnail, outline, or page-
rendering code is entered.

Two encrypted documents are included in the sample. Both completed the audit with
their passwords supplied through the audit environment; password values are not
written to the report or retained by the editor.

## Public sources

| Repository | Random files | Audited commit |
| --- | ---: | --- |
| Mozilla PDF.js | 40 | `70890788983063e4618480ae89db1b9e5f380375` |
| veraPDF corpus | 35 | `01e40281d48e2f3755006fdf596ca25caaea8634` |
| qpdf | 25 | `54d6053af283bbeb8b325f4886c0f65cc51f2b80` |

These upstream test repositories intentionally contain difficult and malformed
files, so this is a stronger robustness sample than a collection made only from
ordinary office documents. The selection is deterministic, and every JSON result
records its repository, commit, and repository-relative path.

## Operations performed for every accepted PDF

1. Open and validate the document.
2. Render the first, middle, and last pages (deduplicated for short documents).
3. Extract sampled text and image objects.
4. Traverse a bounded sample of the document outline.
5. Rebuild the complete PDF through OpenPDF Editor's composition path.
6. Reopen the rebuilt bytes and render a page again.

Each file runs in a separate child process. The coordinator classifies a native
library termination independently and continues with the remainder of the sample.
Peak recorded child-process memory was 85,448 KiB and the slowest file completed in
0.682 seconds on the audit machine.

## Large-document write integration

The separate process-backed Save path was additionally exercised on the supplied
27 MB / 798-page EPLAN document. The complete write finished in 2.432 seconds while
the GUI event-loop heartbeat fired 111 times. The output reopened with 798 pages.
PyMuPDF rendering of pages 1, 399, and 798 before and after the write produced zero
changed color channels across 3,734,640 compared channels. The same three saved pages
were additionally rendered with Poppler and visually inspected for layout defects.

The complete per-file evidence is in `pdf_corpus_audit_0.13.0.json`. The reusable
runner is `tools/pdf_corpus_audit.py`.
