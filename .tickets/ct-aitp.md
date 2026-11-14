---
id: ct-aitp
status: closed
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

**2026-11-13T21:20:54Z**

Final exact-commit checks:124 passed,1 Vision declaration test deselected across six focused files (partial lane). Actual supervised fresh and resumed outputs match text, offsets, scripted recognition provenance and GPO cleanup diagnostics; source/policy corruption, absent last page and out-of-range override controls pass. Direct input/intermediary/output author review is retained at repairs/pdf-offline-20261113/data-review.md with artifact-hashes.json; parent has the exact chains for independent review. Final process-tree measurement:0.75 GiB RSS/0.78 GiB physical. No real recognition or recovery ran.

**2026-11-13T21:52:35Z**

Offline acceptance complete on the composed candidate. An author-independent reviewer read the source fixture page, full checkpoint and worker-failure records, and actual fresh/resumed output: page one survives two page-two exits, only the exact scripted replacement runs, offsets remain 0/86, and no partial document completes. Retained checkpoint storage is 6,044 bytes. See repairs/pdf-offline-20261113/checkpoint-independent-review.md and its hash inventory. The final composed run passed the producer/checkpoint cases; a follow-up 26-test worker/daily run also passed after correcting a test harness method name. These are focused partial-lane results, not a full-lane claim. Real recognition, missing-source content and corpus quality remain in ct-hz8y/ct-yy07/ct-t4p3/ct-n3ik/ct-kfsd. OCR remains paused and all five frozen recovery source hashes still match.

**2026-11-14T15:08:53Z**

The newly authorized targeted recovery lane is exercising the merged page-checkpoint implementation on a real1158-page retained PDF; checkpoints are being written before whole-body completion. Exact policy/source/tool pins and durable path are in repairs/ocr-checkpoint-resume-20261114/manifest.json and pilot-launch.json. This operational reuse does not reopen the already reviewed checkpoint mechanism or claim semantic acceptance of the new body. The old frozen worker lacks checkpoints and remains stopped.
