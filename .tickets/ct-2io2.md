---
id: ct-2io2
status: closed
deps: []
links: [ct-uov2]
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

**2026-10-19T19:22:05Z**

External test-relocation commits 6016ca1 and d0386c7 integrated with PR132. Inventories preserve 335 Python test files, 644 moved test functions and 1433 assertions. Full local run: 9457 passed, 38 subtests, 50 excluded; two relocation failures repaired and targeted checks passed. Review also fixed moved notes and historical fixture ownership. Exact receipts: docs/experiments/efficiency-debt/test-relocation-evidence.json. Worktree refresh remains pending.

**2026-10-19T19:25:05Z**

PR133 merged 3757f55ed33ea390895c20a2007cb08eb39ce519. Primary and all three implementation worktrees refreshed to that revision; owned drafts preserved. Independent relocation, archive and workflow reviews approved. Integration complete.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch standalone).
- Grades: proposal 74 → 74, work 78 → 78.
- Problem: The merged tree (with test-relocation commits 6016ca1/d0386c7) never had a green full run.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/standalone/standalone-verdicts.md:24
- Covered by: WS12 (ct-uov2): the gate is `scripts/dev.py test` on the merged revision.
- See docs/reviews/2026-10-24-ticket-audit/README.md
