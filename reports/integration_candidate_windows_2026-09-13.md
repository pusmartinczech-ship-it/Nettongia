# Integration candidate Windows gate — 2026-09-13

## Result

The automated portion of stage 8 passed on GitHub-hosted Windows Server 2022
from commit `987bf89ae931094b1d506b0b8716cd907b0d125c`, pull request 1, workflow
run `34779226429`.

- Build and packaged self-test: passed.
- Source regression: 133 passed, 21 conditional tests skipped.
- Final golden-PDF audit: passed; no-op save pixel exact on all three pages.
- Representative golden edit: 10,762 changed pixels, zero outside allowed areas.
- Repeated GUI soak: 60 document lifecycles and 180 page renders, passed.
- Windows RSS measurement available: yes.
- Steady-state RSS growth: 7,999,488 bytes (limit 100,663,296 bytes).
- Post-warmup peak growth: 10,147,840 bytes (limit 268,435,456 bytes).
- Leaked temporary workspaces: zero.
- Clean extracted portable OCR acceptance: all seven checks passed.

## Artifact

- Name: `OpenPDF-Editor-Windows-unsigned`
- Size: 173,408,126 bytes.
- SHA-256: `abbf7599fa2109fa08b521988b7c1e89eae87e236aff8cf1d532c0dc95b7432d`

## Remaining release gates

This is not a final release and the application version remains 0.18.0. The
artifact is unsigned because SignPath is not configured or approved. Clean
Windows 10 and Windows 11 installer/portable acceptance tests also remain open;
Windows Server 2022 evidence does not replace those two target-system checks.
