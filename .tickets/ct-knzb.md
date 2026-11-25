---
id: ct-knzb
status: closed
deps: []
links: [ct-o7ew, ct-hbj1]
created: 2026-11-24T18:21:46Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-o7j0
tags: [docmeta, v7, ocr, polish]
---
# DocMeta V7 optional tail: recover 28 R2-404 PDFs & adjudicate 2 remaining V7.3a.1 deadlocks

Optional non-blocking polish tail: (1) check private R2 or local archive snapshots for the 28 http_404 SHAs from ct-o7ew (~0.008% of archive) and re-run scripts/measure/docmeta_v7_ocr_rescue.py run-ocr --resume + package-and-validate if recovered; (2) optionally adjudicate the 2 remaining V7.3a.1 deadlocks (2c4ec309eab7 HMKP-116-JU00-20191211-SD1306.pdf and 04932d9232ed frpp_facility_assets_chart_2017_data_for_roundtable_1.pdf, both already cleanly OCRd in rescued_p15.parquet).

## Acceptance Criteria

Optional: >=1 of 28 R2-404 PDFs recovered or confirmed permanently unavailable; 2 remaining deadlocks resolved or explicitly left out of V7.3a.1 training split.

## Notes

**2026-11-25T20:58:00Z**

Closed after PR #250 (commit on main) + blind swarm verification (`verifier-2`):
1. Fixed `scripts/measure/docmeta_v7_ocr_rescue.py` (`saved_suffix == ""` uncompressed PDFs at `bodies/sha256/<aa>/<sha>` without `.gz`) + 2 regression tests (`66` v7/ocr_rescue tests passing); recovered and OCR'd all 28/28 `http_404` PDFs into `.cache/archive-release/docmeta-v7-ocr-rescue/rescued_p15.parquet` (`sha256=77be1ece...`, `536/559` ok = `95.89%`, `fetch_error: 28 -> 0`, median rescued chars `3,486`).
2. Audited both remaining V7.3a.1 deadlocks (`2c4ec309eab7`, `04932d9232ed`) against OCRd text and CheckEval/teacher votes and documented their explicit exclusion from the V7.3a.1 training split per `text_is_sole_source_of_truth` (evidence in `.cache/archive-release/investigations/ct-knzb-tail-audit-20261125/`).

