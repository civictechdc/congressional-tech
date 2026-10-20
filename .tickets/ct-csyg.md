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

Native table scans (`docspec-rs/src/query.rs:161-179,260-277,369-384`) push column projections (`read_projected_file`) but ignore query filters (`supports_filters_pushdown` is unimplemented / `Unsupported`), expose a single DataFusion partition, and serialize file reads. Occurrence scans (`src/storage/occurrences.rs:187-193`) deliberately disable row pruning to preserve physical file row ordinals.

## Acceptance Criteria

- Name an actual selective caller (such as `replace_keys` file probing in `src/engine/write.rs:606-625` or selective incremental refresh) and inspect its physical plan (`EXPLAIN`).
- Assess maintained `iceberg-datafusion 0.10.1` predicate translation or a narrow `TableProvider::supports_filters_pushdown` returning `TableProviderFilterPushDown::Inexact` for values-only (`OccurrenceScan::values`) scans so DataFusion retains residual predicates while skipping provably non-matching files via `TableScanBuilder::with_filter`.
- Preserve whole-file occurrence ordinal positions on occurrence-bearing reads; never enable blind row filtering on occurrence scans, and fall back to scanning on missing/null/truncated metrics or `IN` lists exceeding Iceberg's 200-item evaluator threshold.
- Measure candidate files and scanned bytes before/after; add bounded file-read concurrency (multiplying buffer admission accordingly) only if scan latency remains the measured bottleneck.

## Notes

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: F6. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit confirmed that `715a8c2` on `docspec-rs` `main` added projection pushdown verification (`ParquetSource` projected columns in `src/engine/aggregation.rs`), while `src/query.rs` native table provider filter pushdown remains unimplemented. Keep sequenced behind `ct-xl0y`, `ct-clvr`, and `ct-cpio`.
