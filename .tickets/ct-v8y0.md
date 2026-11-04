---
id: ct-v8y0
status: closed
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

**2026-11-02T04:01:45Z**

Code on worktree-agent-a5550c04138214670 @ b3c4aa3c (0043edfe). Review verdict: merge and close once merged. Correction: 16 values on 9 lines, all mapping true, not 13 lines.

**2026-11-04T00:09:09Z**

Resolved and verified live in release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (2026-11-03): merged into release-train, validated by full production-offline lane (10,968 passed), Basin import, and live publication.
