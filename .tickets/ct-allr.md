---
id: ct-allr
status: closed
deps: []
links: [ct-v967]
created: 2026-10-24T18:46:38Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-syx8
tags: [audit-20261024, efficiency]
---
# Check whether a body is stored by its key, not an index lookup

Efficiency pass E2. raw_sync.py:443 calls body_info (raw_storage.py:600-609), which reads a whole index leaf per body with a one-leaf cache: about 31M rows on a 3,520-body day. Bodies are content-addressed, so existence is a HEAD or a create-only PUT (412 means present).

## Acceptance Criteria

- Capture decides body presence by HEAD or create-only PUT on the content-addressed key, plus an in-run set.
- No index-leaf read per body on the capture path; a counting test proves it.
- R-check 1-3 pass.


## Notes

**2026-10-30T16:49:25Z**

Verified completed in docs/plans/simplification-plan-20261024.md §6.2.3-6.2.5 (B3-B5, cefr-81oe commit 9a3674cd, cef-s4vp, cef-u7wj): packages/congress_api/src/congress_api/retention/body_store.py (BodyStore) checks body existence directly by content-addressed key (HEAD on 412 / lost-ack) without index-leaf lookups. Verified by uv run pytest -q packages/congress_api/tests/test_body_store_contract.py.
