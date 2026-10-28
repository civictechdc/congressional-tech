---
id: crb-u0f7
status: closed
deps: []
links: []
created: 2026-10-28T02:37:15Z
type: task
priority: 0
assignee: mikewolfd
---
# Release old-writer privacy repair and B0 cleanup command

## Acceptance Criteria

Standalone origin/main release tests legacy capture and recovery privacy plus cleanup backup, conditional rewrite, recovery and final scan; owner steps reflect completed B3 integration


## Notes

**2026-10-28T02:52:11Z**

Standalone source passes 52 focused privacy, cleanup, recovery import and preservation checks. Contracts precede port; review durability concern reproduced and fixed in 35914df5, bounded review APPROVE. Live deployment, writer drain, cleanup and locks are owner actions in the checklist.
