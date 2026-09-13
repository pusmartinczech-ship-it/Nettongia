# Anonymized diagnostics audit

Date: 2026-09-11  
Scope: OpenPDF Editor 0.18.0 follow-up diagnostics checkpoint

## Result

The local operation log and diagnostic export are accepted for the current
public-beta tree. The stable application version remains 0.18.0 until the
signed Windows release gate is completed.

## Privacy and integrity controls

- The persistent JSON-lines log is capped at **256 KiB** and **512 records**.
- Only fixed event names and allowlisted integer, Boolean, language, and enum
  fields are accepted. Unknown fields and free-form values are discarded.
- Timestamps must match the fixed UTC format and per-start session identifiers
  must be random 12-character hexadecimal values. Forged values are rejected
  again while reading the log for export.
- The ZIP is written to a temporary sibling, reopened, checked for its exact
  five-member allowlist and CRC integrity, then atomically moved to the target.
- The export contains `manifest.json`, `system.json`, `session.json`,
  `operations.json`, and `crash-summary.json` only.
- PDF bytes, page renders, text, images, annotations, metadata, file names,
  paths, recent-file history, user/computer/network/hardware identifiers, raw
  exceptions, and raw crash logs are excluded.
- The user must review the included/excluded inventory before choosing a ZIP
  destination. The workflow is localized for all 21 interface languages.

## Failure evidence

The most recent non-empty `crash.log` is moved to `crash.previous.log` before a
new run opens its own empty log. This fixes the earlier loss of crash evidence
at the next launch. The diagnostic ZIP records only whether current/previous
logs exist and the largest coarse size bucket; their contents remain local.
Isolated inspection, OCR, tile-render, and document-write outcomes are recorded
as fixed categories such as `timeout`, `process_error`, or `validation_error`,
never as worker output text.

## Verification

- Full suite with every supplied PDF enabled: **147 passed**.
- Local suite without conditional fixtures/platforms: **126 passed, 21 skipped**.
- Packaged-style self-test: **passed**, including diagnostic ZIP creation.
- Golden PDF visual audit: **passed**.
  - no-op save: 0 changed pixels on all three pages;
  - representative edit: 10,222 changed pixels;
  - changed pixels outside allowed regions: 0.
- Adversarial privacy fixtures containing a Windows user path, customer file
  name, document text, forged timestamp/session identifier, and raw crash text
  produced none of those strings in the exported archive.

## Remaining release gate

This Linux environment cannot produce or sign the final Windows executable.
The next external step remains the pinned GitHub-hosted Windows build, free
SignPath Foundation signature, and clean Windows 10/11 installer and portable
package acceptance matrix.
