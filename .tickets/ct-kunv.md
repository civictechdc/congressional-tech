---
id: ct-kunv
status: open
deps: []
links: [ct-itcg, ct-v8y0]
created: 2026-11-02T00:36:42Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [captures, lake, phase2]
---
# Rebuild captures from receipts at the approved mapping

Owner decision 2026-11-01: the v21 inputs are committed to Basin as they are, and captures are rebuilt in parallel. v21 captures came from an unrecorded pyarrow writer and disagree with raw receipts on at least 12,409 rows. Full raw comparison is in progress under impl-d-jobs.

## Acceptance Criteria

Rebuilt captures replace the committed v21 captures through a recorded commit; every difference from v21 is classified by raw value; 3 receipts/pipeline-data/2026-10-28/* receipts missing locally are read or named. The guard and all model invariant suites pass.

