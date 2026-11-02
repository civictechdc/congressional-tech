---
id: ct-kunv
status: open
deps: []
links: [ct-itcg, ct-v8y0, ct-bxqa, ct-3l1c]
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


## Notes

**2026-11-02T01:52:54Z**

Full comparison by impl-d-jobs 2026-11-01 (not independently rechecked): 2,598,311 raw lines from 2,292 receipts, 3 from the public origin; HEAD and v21 both have 4,147,132 rows with no key-only rows; 51,301 rows differ on 38,919 lines, all read raw. HEAD is right on all classes except 6 HTTP 202 rows, where neither is right on outcome (ct-c6b0): 34,584 v21 failed vs HEAD reference (200, no body, MODS); 12,386 v21 stored vs HEAD failed (raw error); 2,031 stored vs unchanged; 2,270 failed vs saved-record; 17 stored vs failed (202); 1 fetch_outcome only; 6 stored vs failed (excluded_media, original_not_in_package). Rows where both sides agree were not judged. Cause inferred as an unrecorded pyarrow writer; 8772d83b accepts Parquet inputs pinned by digest only, so publish admission should require producer provenance.

**2026-11-02T04:01:45Z**

Raw pass complete on the fixed mapping (0043edfe): 2,598,311 lines, 4,147,132 rows, 153,443,884 v21 column values, 174,072 differ. Direct raw vs HEAD disagreements: 171,894 ZIP members, 30 retry_later (inferred explanation). Review: not-judged classes do hide risk; 2,615,617 rows have no raw complete key, 1,383,874 eligible. Risks filed as ct-bxqa and ct-3l1c. Rebuild itself not run.
