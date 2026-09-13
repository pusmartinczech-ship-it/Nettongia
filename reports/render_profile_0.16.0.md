# Process-isolated tile profile — OpenPDF Editor 0.16.0

The three supplied regression documents were exercised at 400% zoom. Each run displayed the bounded whole-page preview, refined the visible region in a separate process, revisited the first page to verify cache reuse, and stressed rapid scrolling and cancellation.

| Document | Pages | Preview range | Isolated detail range | Cached return |
| --- | ---: | ---: | ---: | ---: |
| 33-E00 EPLAN | 798 | 0.161–0.263 s | 0.821–0.983 s | 0.007 s |
| KUKA project specification | 38 | 0.086–0.170 s | 0.393–0.420 s | 0.008 s |
| LV-15D drawing | 1 | 0.803 s | 1.060 s | 0.008 s |

The separate-process boundary intentionally adds startup and integrity-validation latency to an uncached high-detail pass. The bounded preview remains visible during that interval, and revisiting cached content is effectively immediate. Compared with the previous in-process reference run, the coordinator's observed peak resident memory across the complete three-document sequence fell from approximately 391 MiB to 350 MiB. Child-process allocations are reclaimed by the operating system when each job exits.

No stale result replaced a newer page or zoom state, the 96 MiB LRU bound remained enforced, and all helper workspaces were removed. Exact per-page timings, cache counters, and memory samples are stored in `render_profile_0.16.0.json`.
