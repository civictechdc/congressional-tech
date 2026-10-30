---
id: ct-u01c
status: closed
deps: []
links: []
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
external-ref: ss-vhi2
parent: ct-77zb
tags: [phase2, external, spicy-regs, track7]
---
# T7.1 (spicy-regs): Preserve archive-pinned generations, backfill pre-119th nominations/amendments, and publish historical rosters

External repository task in spicy-stack (ss-vhi2, docs/plans/phase-2-annex-20261028.md §4.1-4.2):
- Update spicy-regs retention to preserve every generation listed in s3://congressional-tech-raw/viewer-publications/pins/spicy-generations.json.
- Backfill pre-119th Congress nominations and amendments.
- Publish historical committee rosters.

## Acceptance Criteria

spicy-regs retention preserves all generations pinned in spicy-generations.json, pre-119th Congress nominations/amendments are backfilled, and historical committee rosters are published (ss-vhi2 closed).


## Notes

**2026-10-30T16:17:54Z**

Completed and verified ss-vhi2 across spicy-docs and spicy-regs after 3 independent reviews:
- spicy-docs (/Users/mikewolfd/Work/spicy-stack-review-work/reconciliation-20261029/provider/checkout, branch codex/reconcile-spicy-docs-20261029): commit db381c112367b57b61ce4e71132686ca36db3e26
- spicy-regs (/Users/mikewolfd/Work/spicy-stack-review-work/reconciliation-20261029/application/checkout, branch codex/reconcile-spicy-regs-20261029): commit 45903e87c15219bb469d5892d4eaceea4e5cac55 (vendored wheel SHA-256: d17b4fe99193d8eb1e42dd65962759a3f76b64c9d6d7cf46d0e1556b89fcc71d).
