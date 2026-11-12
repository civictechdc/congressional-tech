---
id: ct-twfj
status: closed
deps: []
links: [ct-x00f]
created: 2026-11-10T17:12:34Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine, managed-jobs, storage]
---
# Engine: a managed job's workspace records must not grow with the square of the step count

Stage 1 of the staged move to managed jobs (owner decision 2026-11-10, MANAGED-JOBS.md option B). In the 2026-11-07 trial the workspace's lifecycle catalog made 798 commits and wrote 247 MiB, because each commit writes a new metadata file that contains everything before it (874 bytes at the first commit, 623,034 at the last): bytes written grow with the square of the number of commits. The model has 278 steps, 46 outputs and 27 queries and would make about 2,900 commits; extrapolated, about 3 GiB of metadata per fresh run (the extrapolation is ours and unverified; the 798-commit figure was read from one retained run by a researcher and has not been re-measured). Find where the per-commit cost comes from (snapshot log, metadata log, or the records themselves), and bound it: bytes written per commit must not grow with the number of earlier commits in the same job, or the retained history must be trimmed by the engine's own retirement. Links ct-x00f.

## Acceptance Criteria

First a measurement, not a fix: a synthetic managed job of 3,000 small steps, bytes written per commit against commit number, on the integration branch as it is (this confirms or refutes the extrapolation). Then a test that fails first on that growth, the fix, and the same measurement after: total metadata written for 3,000 commits under a stated bound. Retirement removes what a finished job no longer needs (test). Independent review; the engine's check green.


## Notes

**2026-11-11T14:30:07Z**

validated 2026-11-11, left open: not started. dx/managed-records sits at ae12bbd (the pin candidate) with no commits of its own, and dx/one-line (8db7ebb) has no change to the workspace catalog's per-commit metadata; the first step (the 3,000-step measurement) has not been run.

**2026-11-12T16:00:00Z**

Closed with Pin 2 (`docspec-rs` `e3d9092a6393e654efe221d662a76daf8fd56ca5`, hosted CI run `43238636122` 7/7 green). Durable benchmark scripts and reports are archived under `.cache/archive-release/release-20261112-pin2/benchmarks/` (`run_stage1c_bench.py`, `stage1c_bench_report.json`).
- Before-fix empirical measurement (`run_stage1c_bench.py`, 1,500-step synthetic managed job = **3,010 lifecycle commits** / `3,011` `.metadata.json` files, matching the 3,000-commit scale in the AC): baseline `ae12bbd` exhibited quadratic $O(C^2)$ Iceberg metadata growth (`workspace_bytes = 4,893,372,126` = `4.56 GiB` across `13,552` files, including `3,011` `.metadata.json` files totaling `3.55 GiB`, `elapsed_s = 124.222`) caused by unbounded snapshot/manifest/metadata-log accumulation in the workspace lifecycle catalog.
- Engine fix (`docspec-rs` commits `2200945`, `2dab794`, `c27f267`, `d10d838` in `src/engine/managed_job.rs`, `src/engine/managed_job/retention.rs`, `src/engine/retention/recovery.rs`, `src/engine/retention/retirement.rs`, and `src/engine/managed_job/tests/lifecycle_compaction.rs`): auto-compacts the workspace Iceberg lifecycle baseline every 100 snapshot commits via `compact_baseline_with_records` + batched `commit_job_records`, bounding retained `.metadata.json` history and per-commit metadata size to $O(1)$ regardless of step count, and updates retirement validation (`d10d838`) so post-compaction retirement cleans up superseded snapshots while accepting pruned whole-job protection rows.
- After-fix empirical measurement on identical 1,500-step / 3,010-commit benchmark (`stage1c_bench_report.json`): `final_workspace_bytes = 5,974,385` (**`5.70 MiB`** across `1,551` files, `10` `.metadata.json` files at `final_max_metadata_seq = 3,010`; `peak_workspace_bytes = 10,177,226` = **`9.71 MiB`**, `peak_metadata_json_files = 101`; `elapsed_s = 75.372`) — an **`819.1x`** reduction in workspace bytes (`481x` peak reduction). Mid-run `SIGKILL` after ~750 commits (`rc = -9`, `10.42 MiB`) resumed cleanly to completion (`rc = 0`, `final_max_metadata_seq = 4,517`, `10.47 MiB`, `17` `.metadata.json` files).
