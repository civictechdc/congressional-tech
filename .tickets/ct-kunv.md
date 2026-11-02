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

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): Captures gain per-row mapping_version (Utf8, field 41, = APPROVED_MAPPING; guard refuses NULL, non-hex or >1 per receipt) for publish gate 5, and relative original_path (field 42; 415,134 relative values, absolute ones dropped, see ct-f9hw). Reading status adds m3u8 tracks to 2,389 Senate recordings (1,359 to 3,746 with any track); accepted because annex §2 defines playlist bodies as tracks; MP2T segments become role media, never tracks. Custody verify of v21 captures against independent counts (2,292 receipts, 4,147,132 rows): validated, 0 violations (counts and domain only).

**2026-11-02T12:39:55Z**

Ordering constraint 2026-11-02 (lead): v21 is the first snapshot of the canonical archive.captures (ct-itcg). The daily producer must not run against it before this rebuild replaces captures as a full overwrite snapshot; otherwise its receipt anti-join treats v21's roughly 51k wrong rows as present. Daily stays owner-gated (archive-targets.json) until then. Lasting fix: the anti-join treats rows at a non-current mapping_version as not present (impl-e2).

**2026-11-02T14:20:30Z**

2026-11-02 impl-e2: daily refuses with backfill_required when rows are at a non-current or NULL mapping_version, naming each stale mapping with its receipt and row counts; the selective backfill rebuilds them (085f35bd on r1b-e2-map, which needs e1's column; merge after e1). prove_unchanged fix: 8240567c on r1b-e2.
