---
id: ct-twfj
status: open
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

