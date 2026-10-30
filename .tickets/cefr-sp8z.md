---
id: cefr-sp8z
status: closed
deps: []
links: []
created: 2026-10-28T15:50:29Z
type: task
priority: 2
assignee: raw
parent: cefr-7sar
---
# D1: release comparison intermediates before the full oracle join

The current native comparator retains fourteen materialized relations until job end. Release consumed inputs and retain bounded counts and old-only evidence so the full old-index comparison can fit without changing any row decision.

## Acceptance Criteria

A native bounded-memory fixture fails before the change and passes afterward; all comparator behavior checks pass; one independent code review approves; no captures mapping identity changes.


## Notes

**2026-10-28T17:27:02Z**

Committed RightAnti/lifetime fix7423 passes77focused26.94s and one CODE review APPROVE. Actual materialized plan builds old_row only; full2048long-context regression passes192MiB. Separate uncommitted4x measurement fails native spill merge at8192rows (36.4MiB request/32.5held/31left of96MiBpool); owner171606 STOP respected, exact arms preserved. No full-corpus fit claim; awaiting disposition before closing.

**2026-10-30T14:32:57Z**

Completed D1 comparator relation lifetime release and merged to main.
