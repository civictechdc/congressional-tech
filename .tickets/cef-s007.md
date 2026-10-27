---
id: cef-s007
status: in_progress
deps: []
links: []
created: 2026-10-27T04:36:19Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, M1]
---
# M1: measure Basin guarded appends, maintenance growth and remote caps

## Acceptance Criteria

A scratch-only engine probe implements all three PLAN M1 experiments and records rows, codecs, file/manifest growth, pruning, scan time, purge residuals and cap comparison. Owner runs ten maintenance cycles; commit measured decision under docs before selecting Iceberg or dated Parquet.


## Notes

**2026-10-27T05:50:38Z**

Preregistered M1 workload and decision method under docs/measurements/engine-first-20261027/m1.md before any remote measurement. Native targeted tests pass; engine full gate identified metadata-accounting regression being corrected. Basin ten-cycle, projected-volume, cap comparison and purge evidence remain owner-gated; no format choice made.
