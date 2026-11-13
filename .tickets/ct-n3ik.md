---
id: ct-n3ik
status: open
deps: []
links: [ct-a73a, ct-kfsd, ct-hz8y, ct-t4p3, ct-55qo, ct-aitp]
created: 2026-11-11T15:40:45Z
type: feature
priority: 2
assignee: mikewolfd
tags: [ocr, pdf_text, readings, tesseract]
---
# Qualify selective PDF backend routing and measure the typeset/scanned split

Preserve the owner's decisions: measure the hybrid split first and use Tesseract fast as the default candidate. Earlier bounded comparisons favored Tesseract fast for missing/garbled typeset layers and Vision for scans; they do not authorize corpus-wide OCR. OCR remains paused. Reprocess only independently identified bad PDFs/pages after policy and cost qualification.

## Design

The retained all-PDF census reads text, offsets and OCR page lists, not source raster/font/vector features. It ranks review candidates but cannot count typeset versus scanned pages. Reuse spicy-docs NativeOrOcr, FullPage, NativeWithRegions and per-page overrides; qualify composition order and overlaps before adopting region extraction. Upstream commits 5e298abe and 6792cb44 already implement Tesseract model/build identity: coordinate one wheel with ct-cbkz rather than rebuilding backend support in CT. ct-hz8y owns incomplete native-layer detection, ct-yy07 geometry recovery, ct-t4p3 crash settings, ct-aitp page persistence, ct-55qo accepted body selection.

## Acceptance Criteria

1. Obtain source-qualified features for the selected sample and independently measure classifier precision, including mixed pages, vector lettering, sidebars, short and blank controls; name unassessed records.
2. Measure accuracy, omissions, numeric values, runtime and memory for the affected cohort and bring the reread cost to the owner before OCR resumes.
3. Pin backend/model/render/routing identities; demonstrate that unchanged pages are reused and only qualified bad pages are replaced, with original evidence retained.
4. Complex pages may enter an explicit LLM/VLM comparison only when ordinary maintained paths are inadequate; retain source alignment, uncertainty, provider/model identity and cost. No LLM result is accepted from plausible prose alone.

## Notes

**2026-11-13T15:00:26Z**

2026-11-13: The full body-text run (body-text-full-20261110, PID 55948, resumed 2026-11-12 21:32Z after the publish yield) finished 2026-11-13T07:44Z at chunk-0173 with status pending: the work list is exhausted except 411 bodies blocked on missing copy metadata. The 2026-11-13 OCR recovery (codex/ocr-recovery-20261113 @ 56421715, .cache/archive-release/ocr-recovery-20261113, separate recovery catalogs) is retrying all 2,632 leftover bodies; at 14:37Z 2,164 had committed outcomes (1,058 completed, 1,083 parser errors, 23 unreadable) and all 411 missing-pin bodies completed. The typeset/scanned page count can now run over the complete OCR set.

**2026-11-13T17:46:16Z**

2026-11-13 plan reconciliation: the all-PDF feature pass is complete; reuse it and incrementally add recovery results rather than repeat the census. Native coverage/routing is ct-hz8y; page-local crash recovery is ct-t4p3. Retain this ticket's measured typeset/scanned split, fast Tesseract policy and owner cost/adoption decision. Add held-out source checks for garbled S143/S149 forms: accurate names, dates and checked choices matter even when completion and Unicode checks pass. Distinguish missing source/native text, cleanup loss and recognition errors. S138's missing prose bullets are now attributed to cleanup; generic engine replacement is not its fix.

**2026-11-13T18:48:44Z**

Rewritten from the independent ETL/greybeard/evolutionary audit. Prior notes and evidence remain below; old running-job and automatic reread assumptions are superseded. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T21:16:53Z**

Selective page policy/checkpoint composition is prepared; source review still governs backend choice and accepted selection. Direct reviewer /root/ocr_ticket_completion/pdf_recovery viewed S149 page1 and read sources/S149.native.txt plus texts/S149.txt under investigations/text-quantity-review-20261113. Native output is empty. Retained OCR keeps Ashli Watts/title/entity but corrupts question4, loses its visible No/X, and emits date ': 5 | 28/24' where the handwritten source reads5/28/26. This does not qualify any new backend. Q007 missing chart/table content and page125 alternate-setting failures remain cause-specific controls. Parent's C015 review found missing handwriting/date-order limits, so that page is only a cleanup-equivalence control. Tesseract/model/cost/classifier precision and any LLM comparison still require source-qualified output; no recognition/provider calls ran while paused.
