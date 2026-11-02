---
id: ct-bxqa
status: open
deps: []
links: [ct-c6b0, ct-kunv]
created: 2026-11-02T04:01:45Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [captures, eligibility, phase2]
---
# Non-200 raw record.status rows map to stored and count as good fetches

review-d-jobs measured 1,807 rows with raw record.status 404, 202, 503, 429 or 403 that map to stored, complete, http_status NULL, then pass archive_url_state.py:45 good_lines. Include in the batched parser version move.

## Acceptance Criteria

Per-status fixtures, and those URLs are not good.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): plan-e1 raw read: 3,159 body entries state 404/202/429/503/403 under a status key the mapping never reads; 2,997 pass good_lines today (ticket's 1,807 is the record-level subset). Cause 72d03498 plus the mapping's 'no status with a body => stored' rule. Fix: one document rule in receipt_metadata.py (2xx except 202, non-empty body, per-item final state) used by captures, receipt_writer, archive_url_state and the scheduler. Reading status also admits 51,979 stated-200 rows (3,721 new bodies, mostly m3u8); decision: adopt, with HLS and other non-document media classified non-document. Implementing: impl-e1, branch r1b-e1.

**2026-11-02T13:54:36Z**

2026-11-02 (lead): impl-e1 r1b-e1 (4 commits): status is read from 6 owner shapes; origin 72d03498; 13 deep 404 rows stay a residual. Staged before/after on 40,881 of 40,883 lines (2 lines over 36 MB not staged: youtube/api :1, documents :50170): 0 violations, 7,379 stored to failed, 18 to retry_later, 0 stored non-documents, good fetches -232/+30,178. APPROVED_MAPPING is now 9bb28646. Under red/green review.
