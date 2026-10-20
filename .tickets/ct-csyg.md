---
id: ct-csyg
status: open
deps: [ct-xl0y, ct-clvr, ct-cpio]
links: []
created: 2026-10-20T19:23:00Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, storage-review]
---
# Qualify native predicate pruning before adding scan concurrency

For an existing selective caller, assess maintained Iceberg DataFusion provider reuse or a narrow inexact filter adapter. Current native scans ignore filters and are serial; occurrence positions forbid blind row pruning.

## Acceptance Criteria

Name the actual caller and inspect its plan. Measure requested bytes and candidate files, keep residual predicates, field-ID behavior and bounded buffers. Preserve occurrence reads until row positions are qualified. Add bounded concurrency only if scan latency remains the measured bottleneck; otherwise retain the scoped conclusion.


## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: F6. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.
