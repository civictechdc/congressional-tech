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

**2026-11-10T17:00:46Z**

2026-11-10: fix committed on dx/retained-scan (7637a57 tests, f74664b the RetainedScan node, d33404e, 94f9995). STOP RULE: three tests of the memory-fix branch fail once steps report row counts, because their fixtures rely on a 100,000 or 200,000-row step being the hash-join build beside 2,000- and 1-row steps, and with counts the planner builds on the small side: job::slice_charge_tests::join_builds_charge_sliced_join_output_once, refused_compaction_keeps_the_batch_and_the_rows, outer_join_shapes_keep_their_rows_and_charge_once (1 passed, 3 failed; log refactor/retained-scan/t3a-slice-charge.log). Nothing of theirs was edited. Agreed with the coordinator: the tests' owner refits the fixtures so the build side is the smaller of two large inputs (holds with and without statistics); no switch that hides row counts. The planner's exact rule is written out in refactor/retained-scan/swap-rule.md (strict left > right on rows when no byte sizes; equal counts do not swap; single-partition build under 131,072 rows). X1 merges onto the integration branch last, and rides in the first one-line pin only if the full identity build with it gives the same release id and the shared-budget floor is no worse.

**2026-11-10T18:04:58Z**

2026-11-10: reviewed and SPLIT (approved by the coordinator). Review: no finding on the node (it delegates to the same streaming scan; reservation, scratch read-back and charges unchanged); the gain is unproven and predicted small on the model's own SQL, since most join inputs are filters over steps, which tie at DataFusion's default 20 percent guess, and sides derived from JSON-lines inputs have no estimate. X1a, to land on dx/one-line and ride in the first one-line pin: the scan prints the step's name and row count in plans and hands the planner NO statistics, so plans are identical to today's and nothing of the memory fix needs refitting. X1b, parked on its own local branch: row counts to the planner (as estimates, not exact, so small steps keep their round-robin repartition); decided on a measurement of the real model's shape after ct-07wr; if it lands, the memory fix's fixtures are refit (eight hash shapes with a probe of at least the big step's rows and a hash-join consumer against a large non-matching step; seven nested-loop and cross-join cases as hand-built physical plans), and note that DataFusion compares byte sizes before row counts, so if steps ever report bytes a build side is forced by bytes, not rows. No switch that hides counts.
