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
