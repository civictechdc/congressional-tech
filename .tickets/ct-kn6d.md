---
id: ct-kn6d
status: open
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
