---
id: ct-knzb
status: open
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

