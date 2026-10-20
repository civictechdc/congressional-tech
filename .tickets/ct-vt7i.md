---
id: ct-vt7i
status: open
deps: []
links: []
created: 2026-10-20T19:23:00Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, storage-review]
---
# Qualify resource use for exact distinct aggregates

The uncommitted native aggregation draft adds exact COUNT(DISTINCT) and Date32 keys. Its small correctness fixture does not establish behavior for one large group with many distinct values.

## Acceptance Criteria

Use a bounded representative hot-group case to measure memory/spill and complete affected-group work. Prove exact null/duplicate results and safe refusal/recovery at configured limits. Keep this draft qualification separate from released capabilities; reuse DataFusion exact aggregation.


## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: distinct_overlay. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.
