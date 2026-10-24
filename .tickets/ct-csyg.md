---
id: ct-csyg
status: open
deps: [ct-xl0y, ct-clvr, ct-cpio]
links: [ct-nloa, ct-eipa, ct-ur2y, ct-qkvr, ct-98sm]
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

**2026-10-20T22:19:32Z**

Current API has no public exact-version column/filter read; internal native projection is not an application read endpoint. ct-nloa is a concrete bounded-values consumer. Qualify a maintained scoped-read API before expecting application savings; preserve occurrence positions and do not materialize exports merely to emulate lookups.

**2026-10-20T23:32:30Z**

Reopened by evolutionary-refactoring / Iceberg / query-plan audit at `main` (`8221566d` / `6cd80b0e`):
1. `6cd80b0e` marked `ct-csyg` closed without modifying `docspec-rs/src/query.rs:162-180` (`NativeTable::scan` still ignores `_filters: &[Expr]`) or `docspec-rs/src/engine/write.rs:606-659` (`replace_keys` still iterates every file in `scan.files()` and executes a `chunk_{index}` key-join probe without checking Iceberg `DataFile` lower/upper bounds).
2. Both `replace_keys` file probing (`write.rs:606-659`) and `news_lake` keyed lookups (`ct-nloa`, `ct-qkvr` at `docspec_backend.py:980-997`) remain concrete callers needing either Iceberg manifest min/max file pruning on values-only scans (`OccurrenceScan::values`) or a bounded exact-release key/projection read path.

**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A | Impl: F (Reopened). Closed in 6cd80b0e with zero code changes: docspec-rs/src/query.rs:162-180 still ignores _filters and src/engine/write.rs:606-659 still probes all F files without checking Iceberg DataFile lower/upper bounds.

**2026-10-21T00:31:42Z**

Not implemented in this pass. The safe prerequisite is a maintained exact-release keyed read or Iceberg manifest-bounds pruning; docspec-rs 0.10.1 exposes only crate-private InclusiveMetricsEvaluator/StrictMetricsEvaluator, so a hand-written evaluator would duplicate maintained semantics and was not shipped. Keep open.

**2026-10-21T02:20:25Z**

Implemented in docspec-rs (96e38262): (1) replace_keys (src/engine/write.rs:606-710,900-965) prunes non-overlapping files via Iceberg DataFile lower_bounds/upper_bounds/null_value_counts (with 64-byte truncation guard) and skips all probes when key_files.is_empty(); (2) NativeTable::supports_filters_pushdown (src/query.rs:163-198,480-595) returns Inexact for values-only (!located) scans while preserving Unsupported and whole-file occurrence ordinals on located scans; (3) Engine::read_keys / KeyReadSpec (src/engine/read.rs:55-82,220-415, POST /datasets/{dataset}/versions/{version}/keys) streams only matching key rows with column projection and manifest bounds pruning.

**2026-10-21T15:17:46Z**

Scale review 2026-10-21: query pushdown pruning (file_matches_inexact_filters) was correct but untested; docspec-rs 381108c adds exhaustive oracle tests and replaces an O(files^2) per-probe file lookup. Key-bound pruning quality for news_lake depends on clustered ids: ct-ur2y.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch mi03a).
- Grades: proposal 88 → 88, work 75 → 75.
- Problem: At 00:31Z the ticket's own note rejected a hand-written evaluator as duplicating iceberg's maintained, crate-private evaluators.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03a/mi03a-verdicts.md:29
- Status: Reopened: revisit under engine-first rule. About 1,500 lines of hand-written predicate evaluation (docspec-rs `src/query.rs`, `src/engine/key_pruning.rs`) duplicate iceberg's maintained evaluators, which this ticket's own note rejected; the plan's keep list had kept it. Decide whether to expose or upstream iceberg's evaluator instead. Context: docspec-rs epic ss-oxg1; linked to ct-98sm.
- See docs/reviews/2026-10-24-ticket-audit/README.md
