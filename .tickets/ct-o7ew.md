---
id: ct-o7ew
status: closed
deps: []
links: [ct-pqi5, ct-hbj1, ct-knzb]
created: 2026-11-24T14:55:07Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-o7j0
tags: [docmeta, v7, ocr]
---
# DocMeta V7.3b prep: rescue ~554 vector-outlined & low-text big PDFs with fast-ocr

Rescue the bounded ~554 problematic big PDFs (>=300 KB, 0.17% of archive) before the full 328K V7.3b sweep using /Users/mikewolfd/Work/fast-silicon/packages/fast-ocr AutoOCRPipeline (pages 1-5) with the fixed FPDF_PAGEOBJ_PATH (>=200 vector path) native router (~5-10 min locally on Apple Silicon, $0 API cost). Exact measured scope: (1) 314 >=300KB ocr_unreadable PDFs + 4 blank-head GPO Distiller PDFs (e.g., Nomination_Hearing_GPO.pdf / CHRG-116shrg38674), and (2) 240 >=300KB <400-char llm_queue PDFs (image-flattened slide decks like HMKP-116-JU00-20191211-SD1306 and 3-column scans like HHRG-114-IF03-20151007-SD022).

## Acceptance Criteria

Pages 1-5 recovered via fast-ocr for ~554 flagged PDFs; before/after counts of <400-char big PDFs and blank-head pages recorded; 10-doc spot check including SD022, SD1306, and Nomination_Hearing_GPO passes; optional manual re-evaluation of deadlocked cases #5/#7.


## Notes

**2026-11-24T16:09:54Z**

Validated & completed 2026-11-24: ran scripts/measure/docmeta_v7_ocr_rescue.py over 559 unique PDF SHAs (315 ocr_unreadable>=300KB + 240 llm_queue<400>=300KB + 8 sentinels) via FastOCR(apple-vision, dpi=200, pages 1-5) at zsh API cost (peak 7.57 GiB RSS, 507s total). Results (.cache/archive-release/docmeta-v7-ocr-rescue/rescued_p15.parquet sha256=ea2179a0f47cac4ba7dd000944fc0131f1cab5ca90f022d53fecffa39543f688): 508/559 ok (90.88%; 508/531 = 95.67% of R2-fetchable PDFs), 498/559 >=100 chars (89.09%), 454/559 p12>=200 chars (81.22%), 366/559 >=400 chars (65.47%), median=2671 chars, p90=8368 chars; ocr_unreadable cohort: 274/315 ok (271 >=100 chars = 86.03%, 267 >=400 chars = 84.76%, median=4229 chars, 208 vector-outlined); llm_queue_lt400 cohort: 230/240 ok (223 >=100 chars = 92.92%, 184 p12>=200 chars = 76.67%, 95 >=400 chars = 39.58%); sentinels: 8/8 ok & >=400 chars (Nomination_Hearing_GPO 0->3444, LOC_Modernization_Oversight 0->3197, Testimony_Cole 0->11239, Official Hearing Transcript_9.21.2023 0->3687, WM03-20150715 p3 rescued 954 chars, SD022 27342 chars, SD1306 557 chars, frpp chart 1140 chars). Non-ok accounting (0 sha_mismatch, 0 temp leaks): 28 R2 http_404, 17 empty_ocr, 6 corrupt_pdf.
