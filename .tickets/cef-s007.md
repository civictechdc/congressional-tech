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

**2026-10-27T06:05:27Z**

Engine binding committed: bb02e08 shared writer/layout admission and guarded append; 90c1fa0 scoped probe. Full locked/offline test:385 lib,348 integration,15 process,2 layout,10 probe passed;17 ignored live/qualification tests. fmt/clippy, bin/example build, native contracts and safe --plan pass. Independent source reviews approve probe6a36797b and storagea93198f3; reports retained in scratch. Basin remains owner-gated; protocol156a8b1d; no format/cap choice.

**2026-10-27T08:19:53Z**

Release-profile contract97b86f6 and bindingdf52da3 pass full locked offline engine suite385lib/348integration/15process/2layout/11probe;17ignored. Independent source approval61c924d4. Owner recipef576fc23 requires --release. No Basin calls or verdict.
