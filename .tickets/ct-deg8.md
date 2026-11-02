---
id: ct-deg8
status: open
deps: []
links: []
created: 2026-11-01T23:41:45Z
type: task
priority: 2
assignee: mikewolfd
external-ref: ss-oxg1
parent: ct-77zb
tags: [engine, memory, docspec]
---
# Report engine gap: ordered array_agg of named_struct with regexp CASE exceeds the memory pool

Measured by impl-c-explorer 2026-11-01: an ordered array_agg over named_struct containing a regexp CASE reached 20.4 GiB RSS on 3,000 synthetic rows at a 1 GiB pool. 300 rows, no ORDER BY, and the pre-projected form all finish fast. The pool setting does not bound process RSS for this shape, and a similar docspec process at 31.9 GiB appears in the 2026-11-01 18:16 out-of-memory crash report, though that link is unproven. Reproduction: scripts/measure/engine_gap_ordered_array_agg.py on branch worktree-agent-a704015cc138b456b.

## Acceptance Criteria

The reproduction and evidence are reported under docspec-rs ss-oxg1. Either the engine bounds this allocation, or a recorded rule says pool settings do not bound RSS and jobs need an external guard.


## Notes

**2026-11-02T04:01:45Z**

Corrected trigger: a computed CASE branch in an ordered array_agg, not a regexp. Evidence in explorer-native-comparison-20261101.md on worktree-agent-a704015cc138b456b @ da425206. Still to report under ss-oxg1; engine unfixed.

**2026-11-02T10:24:10Z**

Owner decision 2026-11-02: file under docspec-rs ss-oxg1 and fix it in the engine too; commit, merge and push the engine fix and re-pin the runtime.

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): Cause found (plan-engine): ordered array_agg keeps a per-row copy of a shared string-view buffer (DataFusion 53.1 scalar/mod.rs:4439); merging states makes N^2 references and the spill IPC encoder writes N^3 bytes outside the pool (row_hash.rs:1176). A DataFusion 55.2 bump and the upstream #21934 patch both failed when measured. Fix: a generic docspec planner rule casting view arguments to plain strings for ordered or distinct array_agg/string_agg (3k-30k rows: 0.12-0.14 s, at most 173 MiB). impl-engine is implementing, filing the ss ticket under ss-oxg1, and building both binaries; the lead uploads and re-pins.

**2026-11-02T12:43:18Z**

2026-11-02 (lead): second engine memory gap from impl-e2's in-situ profile. Aggregate output leaves as slices of one array and the pool charges each slice for the whole array (5.3 GB charged for 118 MB; hash-join build 5.77 GB; quadratic in groups per partition). This shape (aggregate feeds a hash-join build) is in 39 model steps; query-by-query fixes only move the failure (1dbd70ea fixed url_state_intervals, identical output 1,165,986 rows; step 139 url_state_fetched_keys then failed with HashJoinInput). Fix in docspec-rs with the ct-deg8 rule, one re-pin: compact or charge the build input by referenced size, as CompactViews does before SortExec. impl-engine to file a separate ss ticket.

**2026-11-02T13:14:11Z**

2026-11-02 (lead): both engine fixes are on docspec-rs main 939c14b: 3f274ad (ct-deg8, ss-x71z) and 84745f0 (the aggregate-slice over-charge, ss-ud8y), plus a GitHub Actions workflow for the native linux-amd64 build. scripts/check passed. The darwin and Actions builds of 939c14b are the release build for the runtime re-pin.

**2026-11-02T14:42:47Z**

2026-11-02 (lead): the engine release is docspec-rs 5a3121c: ss-x71z (3f274ad, closed), ss-ud8y (84745f0, the slice and hash-join over-charge: 200k-key build 195 MB for 9.5 MB of data, now under 4x), ss-ezin (425e346, one 8 MiB S3 part size), the Actions linux workflow (939c14b), and 5a3121c (the DISTINCT ORDER BY planning follow-up that failed 46 lane tests). ct-deg8 shapes at 3,000 rows: 0.12-0.14 s, 0.09 GiB (the guard used to kill them at 14.6-17.3 GiB). congressional-tech production-offline on the darwin binary: 10,795 passed, 0 failed. Lesson: the engine's 54-test Linux qualification passed the DISTINCT regression because it runs no model SQL; the release gate for an engine build is this repo's production-offline lane. Local config switched; the repo pin and DOCSPEC_RUNTIME_ARTIFACT move together at the merge to main.
