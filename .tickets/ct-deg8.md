---
id: ct-deg8
status: closed
deps: []
links: [ct-r8jd, ct-wsu7, ct-7t5p]
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

**2026-11-02T15:12:34Z**

2026-11-02 (lead): the production runtime is stripped (owner direction). The linux-amd64 artifact is uploaded and verified byte-identical: key runtime/docspec/5dae6119ccd4874156a291fd3c45865d937cfefb/linux-amd64/2a41926de83893e3eacb846d63e719502fc15d85cca59ce6bfb446672038209c/docspec, 196,653,664 bytes, Actions run 41464746969 (5dae611 = 5a3121c plus the strip step and a <1 GiB check). darwin-arm64 stripped: 372e7ce9285a6579c5217e83ae1b61708ef1939d62bbd547a0d8c996014a6edf (focused lane 4,641 passed). Descriptor: .cache/runtime-5a3121c/runtime-artifact.json. The rollback variable is saved. The pin file (source_revision 5dae611, both shas) and the DOCSPEC_RUNTIME_ARTIFACT variable change together at the merge to main. Uploaded via r4-r2-session (515e14a5: R2 session-token support).

**2026-11-02T15:53:12Z**

2026-11-02 spec-run: the full html compatible-version proof that eb40c54 refused at a 14 GiB pool (HashJoinInput) passed on 5a3121c, comparing all 124,651 kept rows with 0 differences, in 1,024 s at a peak of 5.79 GiB. The engine fix holds on real data.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
