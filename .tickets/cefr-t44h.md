---
id: cefr-t44h
status: closed
deps: []
links: []
created: 2026-10-29T03:34:29Z
type: bug
priority: 0
assignee: raw
---
# D1: spillable multiset proof and preserved-generation resume

Replace wide EXCEPT proof joins with shared tagged grouping; compare immutable preserved cohort generations and continue fresh cohorts without rebuilding.

## Acceptance Criteria

Duplicate and differing-row fixtures; compare-only identity guards; light focused runners; one code review; detached guarded continuation with START/END.


## Notes

**2026-10-29T03:39:59Z**

Fixture e5e01ee9 two multiplicity cases RED with EXCEPT; implementation e939c939 exact multiset grouping and preserved-generation resume.45 focused PASS42.399s/257461464B physical under3.5GiB; prior1CPU harness caused existing partition-plan assertion failure, corrected2CPU without assertion change. Native EXPLAIN fixture asserts aggregation/no HashJoin/no WindowAgg. Commitbody wc typo correction: proof184->245; comparator367->376. ONECODE review active; freshv4 control81pins, downstream88pins; preserved01-03 both guarded builds verified metadata, no corpus launched.

**2026-10-29T03:42:23Z**

ONECODE APPROVE/no confirmed concerns. Detached same-pattern approved resume launched77663; compare-only01/02/03 all equivalent on original immutablepins:12759/324/808680rows,all0/0excess;03 13.718s sampled1577454760B physical. Chain advanced04 freshbuild. Same profiles/admission, stop failure, START/END mail. Full remains lead-only after6; D2 unchanged. Original failure proof reports/statuses/pins preserved.

**2026-10-30T14:32:57Z**

Completed D1 spillable multiset proof and preserved-generation resume and merged to main.
