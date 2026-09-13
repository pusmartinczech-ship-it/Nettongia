# Free Windows code signing with SignPath Foundation

The repository contains an opt-in GitHub Actions signing step. Unsigned builds
work without secrets; signing remains disabled until the project is accepted by
SignPath Foundation.

## One-time owner actions

1. Publish the complete OpenPDF Editor repository publicly under AGPL-3.0-or-later.
2. Apply at <https://signpath.org/apply> and identify that public repository.
3. After approval, install/authorize the SignPath GitHub App for the repository.
4. Create a SignPath artifact configuration for the Inno Setup installer. The
   initial policy may sign the outer installer; a later hardened configuration
   should also sign `OpenPDFEditor.exe` before the installer is compiled.
5. Add repository secret `SIGNPATH_API_TOKEN`.
6. Add repository variables `SIGNPATH_ORGANIZATION_ID`,
   `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_POLICY_SLUG`,
   `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG`, and set `SIGNPATH_ENABLED` to `true`.

The private signing key is not stored in this repository or on the build runner.
SignPath holds it in its signing service. Approval and repository connection must
be performed by the project owner; they cannot be fabricated by the build script.

## Release gate

A signed file is a candidate, not proof that the editor works. Before publishing:

- verify the SignPath signature and timestamp in Windows file properties;
- install on clean Windows 10 and Windows 11 virtual machines;
- run the installed executable self-test;
- open, edit, save and reopen a representative PDF;
- confirm OCR lists `ces`, `slk`, `pol`, `deu` and `eng` without a system install;
- uninstall and verify that user documents were not removed.
