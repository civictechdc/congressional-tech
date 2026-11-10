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

