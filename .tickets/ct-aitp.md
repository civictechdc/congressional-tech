---
id: ct-aitp
status: in_progress
deps: []
links: [ct-a73a, ct-n3ik, ct-hz8y, ct-yy07]
created: 2026-11-13T18:46:40Z
type: task
priority: 1
assignee: mikewolfd
tags: [body_text, quality, recovery]
---
# Resume PDF extraction from durable matched page checkpoints

Whole-document staging discards completed page work when a late page or worker fails. Separate durable pre-cleanup page checkpoints from batch commits, so retry extracts only unfinished matching pages. OCR remains paused; implementation uses native and scripted failure fixtures.

## Design

Reuse spicy-docs DocumentExtractor selected pages and streamed PageResult values, native observations and GPO cleanup. CT owns atomic durable storage, source/page/extraction identity, checksums, failure evidence and final assembly. Key by exact source, reader/render/backend/routing and code/dependency evidence; cleanup runs over the complete ordered page set. Never reuse diagnostic logs as checkpoints without complete identity. Keep checkpoints outside transient batch stages.

## Acceptance Criteria

1. Inject a late-page failure; a new process reuses completed pages and retries only unfinished pages. No partial body becomes completed.
2. Refuse corrupt, mismatched or conflicting checkpoints; preserve failed attempts and distinguish valid empty pages.
3. Uninterrupted and resumed text, offsets, OCR provenance and cleanup diagnostics agree through the actual CT worker path.
4. Measure retained checkpoint bytes and bounded native/fake-backend runtime. A real OCR resume requires the user to lift the pause.


## Notes

**2026-11-13T19:05:14Z**

Implementation started in codex/reading-selection-checkpoints-20261113: opt-in durable page records reuse installed spicy-docs selected-page extraction and existing rendition cleanup. Fresh-process late-exit proof skips the completed page; source-order text, offsets and scripted OCR provenance match a fresh run. Corruption/metadata/storage faults remain pending rather than becoming source failures. Native hearing-cover and blank-page controls pass. This is same-policy restart; cross-policy page repair and real Vision resume remain unqualified while OCR is paused. Combined focused run: 79 passed, partial lane; peak process-tree RSS 0.685 GiB. Usage/evidence: docs/body-text-selection-checkpoints.md.

**2026-11-13T21:16:53Z**

Offline extension prepared: exact decoded-source SHA/page overrides reuse matched unchanged pages, retain prior default and replacement checkpoints separately, and preserve the complete override plan in attempt records. Leaf replacements inherit the reader and require reproducible identities. A real supervised parser fixture exits twice on page two, then reuses page one and writes only a scripted replacement page; no partial body completes. Source mismatch, policy drift, out-of-range pages, missing pages and damaged retained data have explicit controls. Source input/intermediate/final fixtures and direct review observations are in .cache/archive-release/ocr-recovery-20261113/repairs/pdf-offline-20261113/. This proves routing, resume, ordering, byte offsets and failure handling with native/scripted data; real OCR recovery and source-quality acceptance are still paused. No frozen recovery checkpoint was modified.
