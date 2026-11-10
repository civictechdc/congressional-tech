---
id: ct-qxfc
status: in_progress
deps: []
links: [ct-i5u3]
created: 2026-11-10T15:46:33Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine, planner, model]
---
# Engine: step row counts and step names reach the plan (RetainedScan)

From the docspec-rs feedback root-cause analysis (cause B). docspec-rs computes exact rows for every retained step (src/job/materialized.rs ReservedTable::statistics) but its scan returns a StreamingTableExec that reports no statistics, and DataFusion 53.1 join selection reads only the plan's partition_statistics. So every hash join builds on the left input as written: the AGENTS.md join rule, hand-nested RIGHT JOINs, the outer-build lint and its allow-list (ct-i5u3), and the base_normalized failure (ct-n5ec) all follow. Change: a pass-through plan node in materialized.rs that forwards statistics and prints the step name. Branch dx/retained-scan in docspec-rs, cut from fix/nested-slice-bytes. Links ct-i5u3, ct-w564.

## Acceptance Criteria

big LEFT JOIN small over two retained steps builds on the small step; the scan leaf names the step; engine check green; measured on real evidence tables before and after. Outward, not part of this ticket's build: binaries, pin move, lanes on the pin, one full-size build that reproduces the release id. Only after those: delete OUTER_BUILD_TRACKED and its estimator, and the AGENTS.md join rule.


## Notes

**2026-11-10T16:39:20Z**

2026-11-10: owner decision relayed by the coordinator: the pipeline's next engine is the one line with the memory fix (ct-x00f); no new engine change starts on the pinned line. This change continues where it is until its current step is reviewed, then lands on our integration branch dx/one-line by merge. Checked for the other lines: still needed for plain jobs everywhere (the one line's ReservedTable is unchanged; DataFusion 55.2's streaming scan reports no statistics); moot for managed jobs, whose steps are reopened as Parquet scans. A trial merge with the one line conflicts only in src/budget.rs, which comes from the memory-fix base. Builder's finding: the retained byte count is accurate (1.00 to 1.01 times Arrow's own on 14 real step tables); only rows are published, because a step total split by column count misprices join keys. Five pipeline test files match the text StreamingTableExec in plans and need a new string when the pin moves.
