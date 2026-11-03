---
id: ct-kn6d
status: closed
deps: []
links: []
created: 2026-11-01T22:37:26Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [daily, lake, phase2]
---
# Make the daily D4 step run on the real corpus at qualified limits

Reported by plan-d-jobs 2026-11-01, not independently reproduced: produce_daily's D4 step fails on the real corpus at the qualified limits. meeting_records.stage stops with 'SQL result exceeds metadata allowance' on 198,931 inline refs. The fix means editing _record_producer.py, which is hashed into every D4 parser version, so it moves those pins. ct-9gmr routes around this, but the live daily path stays broken.

## Acceptance Criteria

produce_daily completes D4 on the real corpus at the qualified limits, with the parser-version move and any backfill recorded, or the daily path has an owner-approved replacement.


## Notes

**2026-11-01T23:33:23Z**

Root cause, proven by impl-d-jobs 2026-11-01: all 198,931 refs go through queries, 35,554,784 bytes of JSON against a 35,127,296 limit, so query shape rather than batching. Raising the cap only exposes the next fault: 180,785 superseded lines stay missing on every run. v21's rule, latest per URL by (updateDate, witness count), reproduces its 18,146 rows exactly. Proposed, unbuilt: parquet_output for refs, then that selection. Editing _record_producer.py changes every D4 source version (about 90K rows) and needs publish-model.json and publish.json repinned.

**2026-11-02T04:01:45Z**

Code on worktree-agent-a5550c04138214670 @ b3c4aa3c (6a08fac4). Review: merge, stay open. The rule matches v21 both ways at 18,146. Acceptance unmet: appearance work 6,131 exceeds max_work_items 5,000; meetings 639. Witness-count and tie-break mutants survive, so add tests. produce_daily not run on the real corpus.

**2026-11-02T12:28:28Z**

Round 1b 2026-11-02 (lead): Cause measured on v21: the 639 meeting and 6,131 appearance extras are House XML of the wrong root type (amendments, floor schedules); the model routes by root type and the producer doesn't. Fix: one shared root-type definition. impl-e2.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
