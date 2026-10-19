---
id: ct-2io2
status: in_progress
deps: []
links: []
created: 2026-10-19T18:51:10Z
type: task
priority: 1
assignee: mikewolfd
tags: [efficiency-debt, integration]
---
# Qualify and integrate the script package refactor

Integrate local Grok/Cursor commits through 5150f34 with merged evidence at 9400073. Repair independent review findings before publishing a shared baseline for all remaining efficiency/debt tickets.

## Acceptance Criteria

Preserve both sets of ticket notes and priorities. Fix confirmed moved-path, classifier, bounded-admission and runtime-selection regressions. Independent cross-review passes on exact final changes; affected local tests and production-offline suite pass. Merge preserving the existing local commit history, then update active worktrees without losing drafts.


## Notes

**2026-10-19T18:59:16Z**

Independent repair cross-reviews approved. Local production-offline passed 9459 tests and 38 subtests (50 excluded), exact code1478865. Evidence in docs/experiments/efficiency-debt/integration.md. Merge and worktree refresh remain pending.
