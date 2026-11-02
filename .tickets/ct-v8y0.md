---
id: ct-v8y0
status: open
deps: []
links: [ct-itcg, ct-d0o0, ct-kunv]
created: 2026-11-01T22:50:29Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [captures, eligibility, phase2]
---
# Read previous_receipt.body_complete in the capture mapping

Reported by impl-d-jobs 2026-11-01. At receipts/documents/2026-09-29/assemble-20260930 line 122845, record.previous_receipt.body_complete is true and the 200 body is attempt 1, but HEAD maps that attempt to complete=None. From reading the code, source_plan has no path for this field, so the recorded value goes unread and the body counts as ineligible. Corpus impact is unmeasured.

## Design

Measure first: count receipt lines with previous_receipt.body_complete, and how many of their bodies are ineligible today. Fixing the mapper edits byte-hashed captures.py, which moves the captures version, so decide this together with the v21 captures disagreement on ct-itcg and batch any needed backfill.

## Acceptance Criteria

Corpus count recorded. Either the recorded value is read, with version move and backfill recorded, or the owner accepts the measured loss. ct-d0o0's strict expected failure on this line then passes or is removed.


## Notes

**2026-11-01T23:03:05Z**

Measured by impl-d-jobs in the local receipt mirror: previous_receipt.body_complete has 16 values on 13 of 2,596,054 lines, all true. Lowered to P3: the unread field is real but small, so fix it only if captures.py moves for another reason.
