---
id: ct-clvr
status: open
deps: []
links: []
created: 2026-10-20T19:23:00Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, storage-review]
---
# Reuse admitted snapshot planning for occurrence reads

Occurrence capture walks retained snapshot manifests and separately replans current files. Share exact current-file descriptors and tasks within the existing admitted scan context; retain full object closure at creation and retention boundaries.

## Acceptance Criteria

Measure manifest opens/decodes with fixed current files and growing retained history. Preserve membership, field IDs/defaults, unsupported-delete refusal, old readers and bounded memory. Reuse the maintained planner; no global cache or custom manifest parser.


## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: F3. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.
