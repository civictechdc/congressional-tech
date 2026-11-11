---
id: ct-nild
status: open
deps: []
links: [ct-x00f]
created: 2026-11-10T17:12:34Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine, managed-jobs, performance]
---
# Engine: the managed job's copy of a lake snapshot uses large requests and several files at once

Stage 1 of the staged move to managed jobs (owner decision 2026-11-10, MANAGED-JOBS.md option B). At f803ee6 a snapshot input's read closure is copied one member at a time in 64 KiB range requests (src/storage.rs:105 SNAPSHOT_MEMBER_CHUNK_BYTES; src/engine/managed_job/snapshots.rs:846-872; the same constant at src/storage/remote/objects.rs:197), and custody is reused only for the identical snapshot (input_custody.rs:200), so every night copies again. Measured from the file times of the 2026-11-07 trial (refactor/managed-jobs/mj_custody_timeline.out): 756 members, 488 MiB, 952 s, 0.51 MiB/s; the large members ran at about 0.7 MiB/s, one round trip per 64 KiB. Today's repeated remote reads cost 545 s per model build and today's lake has about 2,063 data files, so as built the copy is slower than what it replaces. Wanted: requests sized to the member (bounded by the budget), several members at once, memory charged to the budget for every buffer in flight, and reuse of members already held from an earlier snapshot of the same table (data files are immutable). Links ct-x00f.

## Acceptance Criteria

A test that fails first on request count: a member of N MiB is fetched in at most a stated number of requests. A measurement on a local object store with a fixed delay per request (so it needs no remote read): the trial's shape (756 members, 488 MiB) before and after, seconds and peak memory, with the budget never exceeded. Members already in custody from an earlier snapshot are not fetched again (test). A timing on the real lake is the coordinator's run. Independent review; the engine's check green.


## Notes

**2026-11-11T14:30:06Z**

validated 2026-11-11, left open: not started. On the engine's integration branch dx/one-line (8db7ebb, worktree docspec-dx-one-line) SNAPSHOT_MEMBER_CHUNK_BYTES is still 64 << 10 (src/storage.rs:105); no dx/ branch carries this work. Waits on the managed-jobs stage 1 slot after the one-line pin (ct-x00f).
