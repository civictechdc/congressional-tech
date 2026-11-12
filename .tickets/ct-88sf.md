---
id: ct-88sf
status: closed
deps: []
links: [ct-w564]
created: 2026-11-10T16:19:14Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine, observability, memory]
---
# Engine evidence: name the failing statement, refuse a missing input by name, then state limits and real memory per statement

From the docspec-rs feedback root-cause analysis (causes E and D; .cache/archive-release/investigations/docspec-feedback-20261110/root-cause/PLAN.md, X2). Two phases on branch dx/engine-evidence in docspec-rs, cut from fix/nested-slice-bytes. Phase 1 (no metric event needed): the error the CLI reports names the failing step, output or query; a missing or empty Parquet input is refused before planning, naming the input and its path (today it surfaces as a SQL schema error); the three remaining error sites in src/job/json_lines.rs keep their cause; the CLI raises its soft open-file limit at start. Phase 2 (after the other session's branch reaches its final tip, because src/job/metrics.rs is held until then): a start event with the limits in force and the derived pool, shared-admission and retention-ceiling bytes; process peak memory on step, output and query events; the pool peak on output events; the shared half's lowest available per statement, beside the count of refused compaction copies; a last event naming the failed statement; after ct-qxfc, a per-step join summary. Links ct-w564, ct-64t4, ct-xnn6.

## Acceptance Criteria

Phase 1: a failing step, output and query are each named with the code unchanged; a missing input is refused naming the path while a zero-row file still works; the open-file limit rises under a low soft limit; no pipeline caller that matches engine error text breaks; engine check green; independent review. Phase 2: each new field checked against a different instrument in the prefix run (process peak against the watchdog timeline; shared low-water against the debug log; start event against the limits file). Outward: binaries, pin move.


## Notes

**2026-11-10T16:39:20Z**

2026-11-10: re-homed with the same owner decision (ct-x00f): phase 1 continues on the pinned line until reviewed, then lands on dx/one-line by merge. Expect conflicts there in the four files the one line also changed: src/job/spec.rs, src/job.rs, src/main.rs, src/job/json_lines.rs (predicted from both lines having changed them; to be measured by a trial merge). Phase 2 (everything written through src/job/metrics.rs: start line, real memory, the shared half's lowest available per statement beside the count of refused copies) is built on dx/one-line after the memory fix's final tip is merged there.

**2026-11-11T00:45:17Z**

2026-11-11 (W3 builder, for the second manager): one pipeline test matches an engine error line whole: packages/congress_api/tests/test_provenance_job.py:58 asserts that the first line is 'query: Execution error: absent line 1: source open failed' (added by b1121f14, W1's tests, now on main; line and commit checked here). The one line already changes that text (it adds the path and the OS error), and X2 adds the failing statement's name ('query 1 "q": '), so the pin move to the one line must update that assertion: the acceptance's 'no pipeline caller that matches engine error text breaks' holds only with that update. Managed jobs and job-plan run their own statement loops, so X2 phase 1 leaves their errors unnamed. (The engine-side statements are the manager's reading of the two lines, not re-read here.)

**2026-11-11T11:14:11Z**

2026-11-11: X2 phase 1 landed on dx/one-line as c51130a (merge, 01:37Z per PLAN.md) and is in the pin candidate ae12bbd (git merge-base, checked). The CLI's error now names the failing step, output or query ('query 1 "q": ...'), a missing input is refused by name, job-path errors keep their cause, and the soft open-file limit is raised at start. Managed jobs and prepare-job run their own statement loops and stay unnamed (851fa18 says so in the engine's doc; also in ae12bbd). The CT assertions that matched the old error text whole hold on both engines since dd1bdd37 (claude/dx-engine-text-tests, on main), which settles the update the 2026-11-11T00:45Z note asked for. Phase 2 (everything written through src/job/metrics.rs) has not started.

**2026-11-11T12:47:00Z**

2026-11-11: for readers of engine errors, docs/development.md (One engine query, no job file) now says a memory refusal is told by its text, not its code, on both b0342a7 and ae12bbd: DataFusion's pool refuses with code query ('Resources exhausted: Failed to allocate'), the engine's budget with capacity ('shared memory budget exhausted', 'allocation exceeds admission granularity'), and capacity also names the blocking-I/O limit. X2 phase 1 names the statement but keeps these codes.

**2026-11-12T16:00:00Z**

Closed with Pin 2 (`docspec-rs` `e3d9092a6393e654efe221d662a76daf8fd56ca5`, hosted CI run `43238636122` 7/7 green).
- Phase 2 engine metrics (`docspec-rs` commits `c436f1a` and `edf364e` in `src/job/metrics.rs`, `src/job/materialized.rs`, `src/job/query_result.rs`, `src/job/prepare.rs`, `src/job/spec.rs`, `src/job/plan.rs`, `src/job.rs`, `src/budget.rs`, `src/budget/metadata_cache.rs`, `src/engine/managed_job/execution.rs`, and `src/job/evidence_tests.rs`): emits `[docspec-metric]` `start` event (`limits.{batch_rows, compute_threads, max_batch_bytes, max_metadata_bytes, memory_bytes, scratch_bytes}`, `pool_bytes`, `shared_admission_bytes`, `retention_ceiling_bytes`, `open_files_soft`, `open_files_hard`, `target_partitions`, `scratch`), `process_peak_rss_bytes` and `pool_reserved_peak` on `step` events (covering materialized steps and job queries as `name: "query:<name>"`) and `output` events, per-statement `shared_available_min` alongside `compaction_copied_batches` and `compaction_refused_copies`, a terminal `failed` event naming the failed statement kind/index/name/code, and physical `joins` summaries (`join_type`, `partition_mode`, `build_rows`, `build_step`).
- Cross-instrument verification (`.cache/archive-release/release-20261112-pin2/candidate-build.watchdog.json`, `benchmarks/pin2-full-build-steps.jsonl`, and `benchmarks/ct88sf_debug_cross_check.json`; `release_id = 06cd8374d1609d0e6c2d34b48824c89b65b4519de0317212f38af71768aa755e`):
  1. `start` event vs `limits.json`: exact match (`start.limits.memory_bytes = 25,769,803,776` = 24 GiB, `pool_bytes = 12,884,901,888` = 12 GiB, `shared_admission_bytes = 12,884,901,888` = 12 GiB, `retention_ceiling_bytes = 3,221,225,472` = 3 GiB, `open_files_soft = 1,048,575`).
  2. `process_peak_rss_bytes` vs `archive_watchdog.py`: engine max `8,602,451,968` bytes (`8.012 GiB`) vs process-group `peak_rss_gb = 8.070 GiB` (the `59 MiB` delta is the Python `archive_model_job` parent RSS).
  3. `shared_available_min` vs `RUST_LOG=docspec=debug` `"shared admission request"` (`benchmarks/ct88sf_debug_cross_check.json`): exact byte-for-byte agreement between `[docspec-metric]` `shared_available_min` and `min(available - bytes)` across every statement (`s1 = 33,324,315 B == 33,324,315 B`, `query:q1 = 33,528,945 B == 33,528,945 B`). On the full production build (`benchmarks/pin2-full-build-steps.jsonl`): whole-build floor `12,331,117,710` bytes (`11.484 GiB` = `95.7%` of the `12 GiB` shared budget) on `document_metadata`, total `compaction_copied_batches = 29,760` (`27,281` steps + `2,215` queries + `264` outputs), `compaction_refused_copies = 0`.
