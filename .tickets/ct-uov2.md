---
id: ct-uov2
status: closed
deps: []
links: [ct-bzl9, ct-sbdp, ct-elhm, ct-syem, ct-8kl2, ct-mi03, ct-3180, ct-ccy4, ct-2io2, ct-f7p8, ct-oc2g]
created: 2026-10-24T18:15:54Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-98sm
---
# WS12: ticket process

The audit found tickets written after the work, acceptance criteria that restate the implementation, evidence in the gitignored `output/`, retirements that grew code, and closing notes citing commits that don't exist.

First move: adopt the eight points below and add the one cheap check: commit SHAs cited in a closed ticket must resolve (`git cat-file -e`).

## Acceptance Criteria

1. A ticket exists before its first code commit; an epic closes only after its children close.
2. Acceptance criteria name an observable behavior and the test or measurement that shows it; performance work records a real-data baseline and a decision rule before code.
3. Evidence is committed under `docs/` or in the ticket, never only in `output/`.
4. A retirement ticket closes only when the old path is gone, with before and after `wc -l`.
5. An invariant named in a ticket becomes a test named in its acceptance criteria.
6. No self-assigned grades or size metrics as goals (parameter counts, docstring percentages, "<120 LOC").
7. A check fails when a closed ticket cites a commit SHA that does not resolve.
8. Every reviewer brief names the project runners (`scripts/dev.py`, `scripts/check`).


## Notes

**2026-10-30T16:49:25Z**

Verified adopted in docs/plans/simplification-plan-20261024.md §3 (Constraints and Rules) and enforced across the engine-first simplification and Phase-2 execution.
