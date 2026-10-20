---
id: ct-3li2
status: open
deps: []
links: []
created: 2026-10-20T19:17:09Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, parquet, review]
---
# Sanitize nested export schemas before enabling List and Struct output

The uncommitted native export draft allows List/Struct but rebuilds only root fields. Cloned child fields can retain source documentation or arbitrary metadata in Arrow footer metadata and ExportField.data_type. Footer admission also counts roots instead of primitive leaves.

## Acceptance Criteria

Recursively preserve authorized field IDs/types while stripping descendant metadata; reject unsupported descendant types. Charge footer growth by primitive leaf columns. Prove nested private metadata absent from the artifact and public descriptor, exact values/nulls preserved, and wide nested footer limits enforced. Review before merging the unrelated draft.


## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: F1. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.
