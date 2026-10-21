---
id: ct-vt7i
status: closed
deps: []
links: [ct-gf8i, ct-csjp, ct-gziq, ct-n6lj, ct-jo8n]
created: 2026-10-20T19:23:00Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, storage-review]
---
# Qualify resource use for exact distinct aggregates

Commit `715a8c2` on `docspec-rs` `main` (`298053b`) added exact `AggregateFunction::CountDistinct`, `Date32` grouping keys, incremental aggregate refresh (`src/engine/incremental.rs`, `src/engine/aggregation.rs`), and an EXPLAIN physical-plan verification test (`aggregation_date32_count_distinct_explain_plan_verifies_pushdown_and_hash_aggregate`). However, its small correctness fixture does not establish memory/spill behavior for one large group with many distinct values.

## Acceptance Criteria

- Add a bounded representative hot-group qualification test in `docspec-rs` (`src/engine/aggregation.rs` or `tests/`) with high-cardinality distinct values inside a single `Date32`/scalar group under tight `Limits.memory_bytes` / `scratch_bytes`.
- Measure memory reservation, DataFusion spill/refusal behavior, and complete affected-group incremental refresh work (`process_aggregation`).
- Prove exact null/duplicate `COUNT(DISTINCT ...)` results and safe deterministic refusal/recovery when configured memory/scratch limits are exceeded.
- Reuse DataFusion's maintained exact aggregation operators; do not introduce approximate sketches (`HyperLogLog`) or unbounded in-memory hash sets.

## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: distinct_overlay. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit verified that `CountDistinct` + `Date32` + EXPLAIN plan verification (`HashAggregateExec` + projected `ParquetSource`) are committed on `docspec-rs` `main` (`715a8c2`), but hot-group memory/spill qualification under tight `Limits` remains open. Upgraded priority to 2.
