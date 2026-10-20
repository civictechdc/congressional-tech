---
id: ct-cpio
status: open
deps: [ct-xl0y]
links: []
created: 2026-10-20T19:23:00Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, storage-review]
---
# Separate native Parquet layout from reader batch sizing

Native row-group rows and target file bytes reuse transient reader limits. Compare independent row-group encoded-byte targets with a defensive row cap, using the pinned Parquet APIs.

## Acceptance Criteria

Hold batch memory fixed; measure group/file distribution, footer bytes, compression, read/update cost, peak memory and retained bytes. Preserve exact values and occurrence identity. Adopt only a measured improvement; no blanket large-file default change.


## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: F5. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.
