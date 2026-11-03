---
id: ct-3l1c
status: open
deps: []
links: [ct-kunv]
created: 2026-11-02T04:01:45Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [captures, eligibility, phase2]
---
# Decide whether an empty 2xx body is a good fetch

review-d-jobs measured 281 eligible rows with zero bytes.

## Acceptance Criteria

The owner decides; good_fetches follows, with a fixture.


## Notes

**2026-11-02T10:24:10Z**

Owner decision 2026-11-02: an empty 2xx body is not a document or caption track. Record the attempt, list nothing, recheck on schedule. Read all 281 raw receipts in full before applying; same rule as ct-fh62.

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): All 281 zero-byte eligible rows read raw: the writer recorded empty_response on 137 and empty on 40, 51 have no outcome, 50 already fail at HEAD; 231 drop out under the new rule. impl-e1, r1b-e1.

**2026-11-02T13:54:36Z**

2026-11-02 (lead): 227 eligible empty rows staged out.
