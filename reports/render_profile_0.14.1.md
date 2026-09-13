# Rendering and memory profile — OpenPDF Editor 0.14.1

The 0.14.0 archive and 0.14.1 candidate were run in separate fresh processes with the same off-screen 1000 × 700 viewport. Each representative page was rendered at 400%, the first page was revisited, and scrollbar movement was spaced beyond the tile debounce interval to exercise cancellation and replacement. Times vary by machine; the comparison is meaningful because both candidates used the same runtime and input files.

## Supplied 798-page EPLAN reference

| Measurement | 0.14.0 | 0.14.1 | Change |
| --- | ---: | ---: | ---: |
| Page 1 detail | 0.393 s | 0.220 s | 44% faster |
| Page 400 detail | 0.387 s | 0.181 s | 53% faster |
| Page 798 detail | 0.377 s | 0.206 s | 45% faster |
| Revisit page 1 detail | 0.371 s | 0.003 s | 99% faster |
| Observed peak resident memory | 331.7 MiB | 318.4 MiB | 13.3 MiB lower |

The retained cache held approximately 37 MiB after the navigation and scroll sequence, below its hard 96 MiB limit. The cached revisit produced four direct tile hits. Cache keys include document generation, content revision, page, render scale, preview scale, and tile bounds; a hit cannot reuse content from an earlier edit revision.

## Additional supplied regression documents

- The 38-page KUKA project document completed all sampled previews, detail passes, revisit, and scroll stress without failure.
- The formerly crashing single-page LV-15D engineering drawing completed the same workflow. Its cached revisit detail pass fell from 0.575 seconds to 0.003 seconds.
- The full automated suite, including dedicated tile rendering for all three supplied regression documents, passed with 82 tests.

The machine-readable candidate measurements are in `render_profile_0.14.1.json`. Resident-memory figures include Qt, PyMuPDF, loaded PDF bytes, page previews, and the tile cache; allocators may retain freed arenas for later reuse, so the hard cache bound remains the primary long-session safeguard.
