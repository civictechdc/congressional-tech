---
id: ct-55qo
status: in_progress
deps: []
links: [ct-a73a, ct-n3ik, ct-hz8y, ct-yy07]
created: 2026-11-13T18:46:40Z
type: task
priority: 1
assignee: mikewolfd
tags: [body_text, quality, recovery]
---
# Select qualified body-text readings consistently across planning and publication

The audit found that exact-current-version filters cannot compose unchanged baseline text, resource recovery and selective corrected readings. A new parser version can enqueue all PDFs or hide completed recovery text. One explicit accepted actual key per body/parser must serve planning, export and refusal accounting; newer failures must not replace accepted text.

## Design

CT owns an evidence-pinned selection manifest and shared selection logic over retained actual keys. Keep baseline version pins plus per-body qualified overrides; validate unique keys, expected status and text digest, and fail closed on missing or conflicting selections. Never restamp historical rows or infer acceptance from recency. Preserve prior text and refusals. No production selection changes or OCR runs during implementation.

## Acceptance Criteria

1. Native consumer proves unchanged baseline, recovered, corrected and rejected replacement cases with exactly one selected key per body/parser.
2. A markup-only version move queues zero PDFs when the accepted PDF baseline is unchanged.
3. Planner, export and refusal coverage agree; missing, duplicate, stale or digest-mismatched entries fail explicitly.
4. Record manifest identity, selected text hashes, pending work and retained refusal history; qualify real cohort before production publication.


## Notes

**2026-11-13T19:05:14Z**

Implementation started in codex/reading-selection-checkpoints-20261113: shared manifest selection now serves native planning, export CLI and refusal coverage. Baseline plus qualified actual-key overrides preserve prior accepted text; failed replacements stay unselected. Current attempts awaiting qualification are counted separately and do not loop into extraction. Focused native tests cover mixed versions, invalid/missing/duplicate selections, changed report/text hashes and markup-only changes. No production selection manifest or historical publication was changed; keep in progress for retained-cohort qualification. Usage and exact limits: docs/body-text-selection-checkpoints.md.
