---
id: ct-7e7q
status: closed
deps: [ct-upte]
links: [ct-7uit]
created: 2026-10-20T08:27:12Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Skip absent observation roots during initial source qualification

The final 4/40 unrelated-record measurement reads the same alias leaf 111/903 times during setup. SourceObservationStorage.affected alternates a known absent before-root with the new after-root, clearing the bounded membership cache on each absent lookup. The exact catalog-copy adoption path avoids this loop, but required source qualification enters it.

## Design

Skip lookups for provably absent before/after roots in the existing source-observation owner. Reuse the exact-pin bounded cache; do not widen cache budgets or add another owner.

## Acceptance Criteria

Demonstrate red/green read counts for initial qualification and deletions, preserve exact affected sources and old/new membership, and repeat only the retained local 4/40 setup measurement affected by the fix. Independently review. No provider, corpus or browser qualification repeat.


## Notes

**2026-10-20T08:33:50Z**

Independently reviewed edde5519 integrated as82fae7f2. Five root regressions and11 owner checks passed. Exact same4/40 local fixtures reduce initial native reads116/908 to8/8 and logical read bytes1,350,183/90,695,052 to46,407/385,452. All phase native submissions and exact preservation assertions unchanged. No cache budget increase. Evidence:end-to-end/absent-root/comparison.json and review-merge/root-observation-absent-review.md. These are local logical counts, not cloud throughput.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch czsd).
- Grades: proposal 91 → 91, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
