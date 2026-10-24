---
id: ct-xl0y
status: closed
deps: []
links: [ct-eipa, ct-wmtx, ct-cpio, ct-csyg, ct-oxg6, ct-3li2, ct-2wsw]
created: 2026-10-20T18:35:20Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, rust, efficiency]
---
# Remove avoidable work inside DocSpec native Update

The initial Update measurement was a 16-row baseline, not a verdict on native capability. Trace source scans, changed-file writes, temporary key tables, lifecycle commits and application selection coupling. Fix measured avoidable native work without weakening retained changes, concurrency or stale-base guards.

## Acceptance Criteria

- Remove the unused prepared-key Iceberg catalog registration and metadata JSON write in `docspec-rs/src/engine/write.rs:550-601` (completed and merged to `docspec-rs` `main` as `a0df449` / `82b32df`) while preserving the bounded Parquet key writer and protected attempt path.
- Qualify scale behavior across 10,000 and 100,000 rows (`docs/experiments/docspec-reuse/native-update-scale.md` in `codex/docspec-keyed-updates`), demonstrating the crossover where unchanged-file sharing makes `Update` beat full `Build` (100k rows: `Update` 0.783s–1.027s vs `Build` 2.095s–2.309s; 8.4 KB–1.48 MB written vs 11.9 MB).
- Evaluate reducing the remaining $O(R_{\text{keys}} + (F+C)K)$ prepared-key re-execution across $F$ file probes and $C$ rewrites (`src/engine/write.rs:606-680`, storage review finding F2) by comparing a single key-and-file discovery semi-join or admitted reusable key relation against current per-file probing.
- Explicitly distinguish safe native engine improvements from any separate application prepare/select API change (`stale_base` / native `latest` advancement remains tracked in `ct-eipa`).

## Notes

**2026-10-20T18:47:14Z**

CS300 review distinguishes a constant saved catalog registration from algorithmic work: current replace_keys probes every source file and executes prepared-key scans F+C times (F files,C changed files). Measure file-count growth and DataFusion scan bytes before deciding whether a further native change is justified. Unchanged-file reuse does not mean zero scans.

**2026-10-20T19:00:10Z**

Fresh Parquet/Iceberg advisor verified Iceberg0.10.1/DataFusion53.1.0/Parquet58.4.0. NativeProvider ignores filters; occurrence reads preserve whole-file ordinals, so do not enable row filtering blindly. After scale measurement, consider public TableScanBuilder.with_filter for conservative possible-match file paths, then unchanged full-file reads. Unknown metrics/null/default/type/truncation cases must retain scan. Private evaluator and IN>200 fallback constrain implementation. Advice: output/docspec-reuse-20261020/parquet-iceberg-advice.md.

**2026-10-20T19:23:00Z**

Fresh read-only review2026-10-20: F2. Evidence: output/docspec-reuse-20261020/parquet-iceberg-review-v2/review.md and evidence.md. Expected performance gains remain unmeasured; preserve the exact inspected state in receipt.json.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit validated commits `a0df449` and `82b32df` on `docspec-rs` `main` (`298053b`) and the 129-case scale qualification in `codex/docspec-keyed-updates` (`71128ece`, `docs/experiments/docspec-reuse/native-update-scale.md`). Grade: B+. Integrate the `codex/docspec-keyed-updates` evidence docs/tests into `docspec-reuse-integration`; any further $(F+C)K$ discovery join change must prove a measured reduction on multi-file fixtures without loosening `stale_base` or occurrence ordinal invariants.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch mi03b).
- Grades: proposal 93 → 93, work 84 → 84.
- Problem: AC3 (compare a single discovery semi-join against per-file probing) was not done at closure.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03b/mi03b-verdicts.md:35
- Covered by: WS11 (ct-2wsw); engine performance work is frozen.
- See docs/reviews/2026-10-24-ticket-audit/README.md
