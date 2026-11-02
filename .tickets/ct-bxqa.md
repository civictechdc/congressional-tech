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

