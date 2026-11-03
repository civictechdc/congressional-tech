---
id: ct-kunv
status: closed
deps: []
links: [ct-itcg, ct-v8y0, ct-bxqa, ct-3l1c, ct-9gmr, ct-uupp]
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

**2026-11-02T17:13:22Z**

2026-11-02 spec-run: the real captures rebuild (D1) passed the backfill guard on candidate-r1b 9faf86df, peaking at 6.93 GiB under the 14 GiB pool (staging batch cap). compare_generations against v21 refuses until an expected-change-class file exists: about 59k outcome and 65k good_fetch changes. impl-e1 is building the class file, and an independent raw judge is verifying every changed row; unexplained rows are defects. Size-bound registry rule committed (r1b-det 3a3d2560): only c90e782a is recomputed.

**2026-11-02T17:21:55Z**

2026-11-02 impl-e1/spec-run: the D1 captures rebuild vs v21 is ACCEPTED by compare_generations with the expected-change-class file (r1b-captures-causes cabfffb9, off candidate-r1b). 4,147,132 rows on both sides, 0 rows on one side only, 0 unexpected changes. An independent raw judge read the receipt lines (status, body size, content_range) of all 111,324 changed rows and left none unexplained. Result: .cache/archive-release/r1b-run/compare/generations-expected.json. Limit: like the backfill guard, this sees changed rows only; an unchanged value that is wrong but in-domain is not covered here (gate 1 and the raw value comparison cover that).

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
