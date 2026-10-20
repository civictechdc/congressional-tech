---
id: ct-xl0y
status: in_progress
deps: []
links: []
created: 2026-10-20T18:35:20Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, rust, efficiency]
---
# Remove avoidable work inside DocSpec native Update

The current Update measurement is a baseline, not a verdict on native capability. Trace source scans, changed-file writes, temporary key tables, lifecycle commits and application selection coupling. Fix measured avoidable native work without weakening retained changes, concurrency or stale-base guards.

## Acceptance Criteria

Controlled before/after native fixture with equivalent exact changes/old pins/recovery guarantees. Local gates and independent Rust review. Explicitly distinguish a safe engine fix from any separate prepare/select API change. Preserve pinned production binary and state.


## Notes

**2026-10-20T18:47:14Z**

CS300 review distinguishes a constant saved catalog registration from algorithmic work: current replace_keys probes every source file and executes prepared-key scans F+C times (F files,C changed files). Measure file-count growth and DataFusion scan bytes before deciding whether a further native change is justified. Unchanged-file reuse does not mean zero scans.

**2026-10-20T19:00:10Z**

Fresh Parquet/Iceberg advisor verified Iceberg0.10.1/DataFusion53.1.0/Parquet58.4.0. NativeProvider ignores filters; occurrence reads preserve whole-file ordinals, so do not enable row filtering blindly. After scale measurement, consider public TableScanBuilder.with_filter for conservative possible-match file paths, then unchanged full-file reads. Unknown metrics/null/default/type/truncation cases must retain scan. Private evaluator and IN>200 fallback constrain implementation. Advice: output/docspec-reuse-20261020/parquet-iceberg-advice.md.
