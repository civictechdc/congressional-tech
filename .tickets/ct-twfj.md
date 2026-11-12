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

Closed with Pin 2 (`docspec-rs` `e3d9092a6393e654efe221d662a76daf8fd56ca5`, hosted CI run `43238636122` 7/7 green).
- Before-fix empirical measurement (`run_stage1c_bench.py`, 1,500-step synthetic managed job = 3,002 lifecycle commits): baseline `ae12bbd` exhibited quadratic $O(C^2)$ Iceberg metadata growth (`commit #1 = 874 B`, `commit #3,002 = 2,366,439 B`, cumulative workspace metadata written = `3.55 GiB`) caused by unbounded `snapshot-log`, `metadata-log`, `snapshots`, and manifest accumulation in the workspace lifecycle catalog.
- Engine fix (`src/engine/managed_job/`, `dr-cbwt`): replaced per-step Iceberg catalog commits with an $O(1)$-per-event append-only framed CRC32-verified WAL (`job_events.wal`) + atomic checkpoint compaction and post-completion retirement cleanup, with crash/truncation recovery tests and quadratic-growth regression guard.
- After-fix empirical measurement on identical 1,500-step / 3,002-commit benchmark (`27e304b` / `e3d9092`): per-event record size is constant (`~210 B`), total lifecycle bytes written across all 3,002 events dropped from `3.55 GiB` to **`0.63 MiB`** (`5,770x` reduction), and retirement removes transient WAL/step artifacts cleanly.
