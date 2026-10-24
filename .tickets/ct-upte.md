---
id: ct-upte
status: closed
deps: [ct-l5q1]
links: [ct-7uit]
created: 2026-10-20T07:43:10Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Reuse validated membership leaves during one update

The integrated4/40 fixture rereads the same shared membership leaf repeatedly: source-observation append performs84 native reads and48,566 logical rows at40 unrelated documents. Finite shared-leaf cost is expected; repeated reads of the same exact immutable leaf are avoidable.

## Design

Reuse a strictly bounded, exact-pin validated leaf within the maintained CatalogMemberships owner. Prefer one retained leaf or an existing bounded primitive. Preserve alias validation, duplicate checks, selected counts, update isolation and immutable old pins; do not change partition/resource limits.

## Acceptance Criteria

Red/green tests prove repeated alias queries sharing a leaf decode it once, changed pins or metadata revalidate, and eviction stays bounded. Re-run the retained4/40 integrated cases after the code change, report all counters and remaining shared-leaf amplification, prove exact values/IDs/publication hashes, and independently review.


## Notes

**2026-10-20T07:58:31Z**

Implemented and independently reviewed bounded two-entry immutable membership reuse; combined retained Arrow bytes stay within the existing leaf budget. Local integration11tests pass; agent62focused tests pass. Identical4/40 fixture checks reduce append native reads105→21 while preserving values,IDs,old pins,old publication hashes and all write counters. Evidence: output/incremental-updates-20261019/end-to-end/cache-pair/receipt.md and review-merge/root-membership-cache-review.md. Remaining shared-leaf amplification is documented; ct-2ukk stays open.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch czsd).
- Grades: proposal 87 → 87, work 83 → 83.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
