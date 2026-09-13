# Isolated compatibility inspection soak — OpenPDF Editor 0.15.0

The supplied 27 MB, 798-page EPLAN document was inspected twelve consecutive times. Each cycle launched a fresh helper process, scanned every page for compatibility-sensitive structures, and rendered the first, middle, and final pages. Lazy thumbnail generation and detailed tile rendering were disabled for this measurement so their independent caches could not be mistaken for an inspection leak.

| Measurement | Result |
| --- | ---: |
| Cycles | 12 |
| Average cycle | 2.252 s |
| Fastest / slowest cycle | 1.417 s / 3.416 s |
| Parent RSS after first cycle | 173.4 MiB |
| Parent RSS after final cycle | 173.4 MiB |
| Steady-state growth | 24 KiB |
| Allowed steady-state growth | 64 MiB |
| Leaked temporary workspaces | 0 |
| Result | Passed |

The test environment exposes a Qt process identifier that cannot be correlated reliably with the container's `/proc` identifiers. Child-process RSS is therefore recorded as unavailable rather than presenting a misleading combined value. Process termination, result validation, parent-process stability, and temporary-data cleanup were all verified. Full machine-readable samples are stored in `inspection_soak_0.15.0.json`.
