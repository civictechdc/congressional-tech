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
