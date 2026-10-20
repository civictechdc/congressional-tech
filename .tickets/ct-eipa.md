---
id: ct-eipa
status: in_progress
deps: [ct-xl0y]
links: []
created: 2026-10-20T18:24:28Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Use native keyed updates where they reduce partition work

Measure existing immutable partition Builds against DocSpec Update for a supported raw-state/capture consumer. Preserve complete replacement/deletion semantics, old pins, source order and application selector. Adopt only where measured work is reduced.

## Acceptance Criteria

Before/after identical append/correction/delete/no-op measurements including native reads/writes and actual elapsed time. Prove old pins and unrelated data unchanged, replay safe and stale-base refused. If Update loses on actual workload, retain simpler path and record the measured decision rather than claim an improvement.


## Notes

**2026-10-20T18:35:20Z**

User requested investigating fixes in DocSpec-rs before deciding on Build versus Update. Existing48-case receipt and ownership regression are baseline evidence. Decision remains open pending native optimization and remeasurement; no runtime path switched.
