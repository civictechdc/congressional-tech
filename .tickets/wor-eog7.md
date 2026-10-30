---
id: wor-eog7
status: closed
deps: []
links: [dec-eog7]
created: 2026-10-29T15:00:00Z
type: task
priority: 1
assignee: mikewolfd
---
# Cap named-step retention allowance and report per-step allocated bytes in StepResult

## Summary
In docspec 0cbad87 (`src/job/materialized.rs`), `retain()` charges each batch of a materialized named step against the shared FairSpillPool (`limits.memory_bytes / 2`) via `reservation.try_grow()`. Because spilling to scratch occurs reactively only after the entire pool is exhausted, retained tables greedily consume the shared pool to ~100%, starving subsequent query operators (e.g. GroupedHashAggregateStream, HashJoinExec) of working memory. Furthermore, `StepResult` returns only `{name, storage}`, omitting byte counts, row counts, and duration metrics.

## Proposed Native Changes (docspec-rs / dec-eog7)
1. **Retention Cap / Threshold Spilling:** Introduce a dedicated retention budget ceiling (e.g., at most 50% of FairSpillPool capacity) or an explicit `materialize: "scratch"` directive so retained tables do not saturate pool headroom required by active execution operators.
2. **StepResult Telemetry:** Extend `StepResult` to include `allocated_bytes: u64`, `row_count: usize`, and `duration_ms: u64` for transparent attribution and monitoring.

## Notes

**2026-10-30T16:49:24Z**

Verified superseded and resolved by wor-il4d (commit 59d4eea4): packages/viewer_publication/src/viewer_publication/archive_model.py calls step.release_after() -> job.release(name) after every intermediate relation's final native reader, releasing intermediate allocations so the full 19-file Phase-2 release (a06e2a636d3c765f81be13712f496aa25a0dec50d7055ea8a1dbb18f0ebf1e25) completes within memory bounds while preserving the JobResult determinism invariant (no clock or process identity enters StepResult).
