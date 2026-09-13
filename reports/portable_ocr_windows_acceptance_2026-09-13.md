# Portable OCR Windows acceptance — 2026-09-13

## Result

Stage 7 passed on GitHub-hosted Windows Server 2022 from commit
`3ac5fa777f66b621ecbf79ae6c1502a0587d0093`, workflow run `34759413759`.

- Build and packaged self-test: passed.
- Source regression: 133 passed, 21 conditional tests skipped.
- Clean portable extraction below a Czech Unicode path: passed.
- System Tesseract absent and inherited `TESSDATA_PREFIX` removed: confirmed.
- Required languages `ces`, `slk`, `pol`, `deu`, `eng`: passed.
- Missing-language error, modified-model rejection and hard cancellation: passed.
- OCR temporary-output cleanup: passed.

## Sizes

- Unpacked application: 220,891,741 bytes (budget 850 MiB).
- Portable ZIP: 100,693,707 bytes (budget 400 MiB).
- OCR assets: 29,202,291 bytes (budget 32 MiB).

## SHA-256

- GitHub artifact ZIP: `e4f1745031b37269bd363d06f4421e152e3598662995d575e1d726a7edac9639`
- Portable ZIP: `0591e73126b9b95423fff6ad9d6c017a10545a49304783a2c63e6b8b149b16a3`
- Unsigned installer: `b6380621a3df2c0c4eee71d8f0102d5984d2886ff9ee8c2e96fd4ff104222168`

## Remaining release risks

The candidate is unsigned because SignPath repository variables and approval
are not configured. Windows 10 and Windows 11 clean-machine tests, the
long-duration memory test and the final golden-PDF gate remain open. Version
0.18.0 is therefore unchanged and this is not a final release.
