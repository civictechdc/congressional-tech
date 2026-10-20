---
id: ct-gziq
status: open
deps: [ct-eipa, ct-dmca]
links: []
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Support R2-backed incremental joins and summaries

Evaluate one existing congressional dependency/count consumer against DocSpec incremental refresh (`src/engine/incremental.rs`, `src/engine/aggregation.rs`, `src/engine/join.rs`). Current remote backend refuses this operation via `require_local()`. Keep congressional grouping policy and coherent application selection outside native storage.

## Acceptance Criteria

- Extend `docspec-rs` incremental join/aggregate refresh to support configured remote object storage via the unified `Engine` remote capability boundary, retaining original occurrence locators on joins and bounded hot-group memory/spill (`ct-vt7i`) on aggregates.
- Qualify locally and on an isolated R2 provider prefix with exact append, correction, delete, duplicate, null, and old/new dependency tests.
- Prove unrelated partition/target files are reused without re-upload and measure the complete end-to-end refresh path; make no claim of arbitrary incremental SQL.

## Notes

**2026-10-20T18:35:21Z**

User explicitly authorized extending DocSpec-rs itself for R2 support on2026-10-20. Implement in isolated native worktrees, qualify locally before isolated provider tests, preserve production data and mappings. Backend refusal is a dependency to solve, not grounds for closing this ticket as deferred.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit linked `ct-gziq` to `ct-dmca` (unified remote capability boundary) and `ct-vt7i` (hot-group aggregate resource qualification).
