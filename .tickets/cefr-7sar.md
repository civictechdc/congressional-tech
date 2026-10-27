---
id: cefr-7sar
status: in_progress
deps: []
links: []
created: 2026-10-27T17:09:26Z
type: task
priority: 2
assignee: raw
---
# D1: rebuild captures from every receipt shape through native jobs

Owner reassigned D1 to raw in run2. Follow current DM6.1; message engine before changing a column or rule.

## Acceptance Criteria

Native receipt mapping covers all shapes and status/time/completeness; rebuild-equivalence passes; pinned old-index comparison has written transformations and lists owner-only rows; local append races covered; live lake writes owner-gated.


## Notes

**2026-10-27T23:27:54Z**

Typed physical slice fdb9242c follows contracts5ad1e036/aebd627c/d154a16d. All68 affected checks plus1 edge passed; independent CODE5checks passed13.85s and both CODE/ARCH APPROVE without blockers or concerns. Paired131072-row fixture outputs byte-identical; runner87.33 to43.40seconds, reported maxRSS1680293888 to1039368192bytes, bounded shared-Mac evidence only. Full counter retry began23:25:15Z on0c5545a with cap00:10:15Z; no accepted population or old-index comparison yet. Ticket remains in progress; live lake writes remain owner-gated.
