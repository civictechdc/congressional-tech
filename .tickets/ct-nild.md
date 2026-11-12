---
id: ct-nild
status: closed
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

**2026-11-12T16:00:00Z**

Closed with Pin 2 (`docspec-rs` `e3d9092a6393e654efe221d662a76daf8fd56ca5`, hosted CI run `43238636122` 7/7 green).
- Engine fix (`src/storage.rs`, `src/engine/managed_job/snapshots.rs`, `src/engine/managed_job/input_custody.rs`, `dr-3y1p`): raised snapshot custody transfer chunking from `64 KiB` to budget-admitted `8 MiB` range windows (`SNAPSHOT_MEMBER_CHUNK_BYTES`), added bounded concurrent multi-member fetching (`buffer_unordered(8)`) with every in-flight buffer explicitly reserved against `Budget` shared memory before allocation, and added content-addressed/immutable member reuse across successive snapshots of the same table (`table_uuid`) so already-held Parquet data files are hard-linked/reused without re-fetching.
- Verification (`tests/managed_jobs.rs` + delayed local object-store benchmark matching the 756-member, 488 MiB trial shape): request count per N MiB member dropped `128x` (`1` request per `<= 8 MiB` member vs `16` per MiB), simulated 756-member / 488 MiB transfer with per-request latency dropped from sequential `64 KiB` round-trips to concurrent `8 MiB` reads within budget ceiling, and second-snapshot overlap test verified `0` duplicate fetches for members retained from the prior snapshot.
