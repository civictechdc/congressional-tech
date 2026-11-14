---
id: ct-n3ik
status: in_progress
deps: []
links: [ct-a73a, ct-kfsd, ct-hz8y, ct-t4p3, ct-55qo, ct-aitp]
created: 2026-11-11T15:40:45Z
type: feature
priority: 2
assignee: mikewolfd
tags: [ocr, pdf_text, readings, tesseract]
---
# Assess retained text quality and qualify selective PDF repair

Preserve the owner's decisions: measure the hybrid split first and use Tesseract fast as the default candidate. Earlier bounded comparisons favored Tesseract fast for missing/garbled typeset layers and Vision for scans; they do not authorize corpus-wide OCR. OCR remains paused. Reprocess only independently identified bad PDFs/pages after policy and cost qualification.

Assess the entire retained population using existing metadata/page features, then inspect source and intermediate contents for omissions despite successful extraction. The user estimates about 2.7 billion tokens; the frozen census has 607,584 completed bodies, 295,770 PDF bodies and 7,764,694 recorded PDF page slots. Logical document rows, body identities, recorded pages and tokens have different denominators. See docs/plans/corpus-text-assessment-20261113.md for counts, multi-stage assessment, Keeplist reuse, held-out calibration and measured-cost boundaries.

## Design

Keep coverage, recognition, cleanup loss, response role and missing evidence separate. Priority scores rank review and never become acceptance probabilities. A thin offline assessor consumes identity-bound observations and emits keep/reparse/renormalize/native-reread/selective-OCR/manual/deferred-refetch recommendations; it never reads source content, changes selection, or dispatches recognition/acquisition. Reuse the existing complete PDF page-feature pass and the 376-case Keeplist applicability study, adding only changed reading keys and genuinely missing measurements. ct-hz8y owns native/vector repair, ct-kfsd cleanup exposure/publication, ct-cbkz/ct-f6hr markup reparse/compatibility, and ct-en4n/ct-z4w5 source roles/deferred acquisition; this ticket coordinates assessment without duplicating their acceptance.

The retained all-PDF census reads text, offsets and OCR page lists, not source raster/font/vector features. It ranks review candidates but cannot count typeset versus scanned pages. Reuse spicy-docs NativeOrOcr, FullPage, NativeWithRegions and per-page overrides; qualify composition order and overlaps before adopting region extraction. Upstream commits 5e298abe and 6792cb44 already implement Tesseract model/build identity: coordinate one wheel with ct-cbkz rather than rebuilding backend support in CT. ct-hz8y owns incomplete native-layer detection, ct-yy07 geometry recovery, ct-t4p3 crash settings, ct-aitp page persistence, ct-55qo accepted body selection.

## Acceptance Criteria

1. Reconcile every frozen body/reading into an assessed, missing-evidence, unsupported, pending or refused state with exact source/output/version identity; do not add snapshot counts without deduplication. Preserve page scope and alternative attempts.
2. Independently calibrate review priorities and action proposals on source-disjoint held-out originals, including long/completed/no-trigger false-negative controls, legitimate short/empty/container/feed controls and planted omissions/wrong values. Record per-stratum precision, missed defects, unknowns and review scope; no corpus accuracy claim from the current exploratory sample.
3. Measure representative and largest eligible source/input costs separately from already-measured text-feature costs. Freeze token/render/provider costs and bounded budgets only for selectively escalated reviewed pages; preserve the OCR pause and refetch deferral. Proposal-only output cannot close source qualification or publication criteria.

4. Obtain source-qualified features for the selected sample and independently measure classifier precision, including mixed pages, vector lettering, sidebars, short and blank controls; name unassessed records.
5. Measure accuracy, omissions, numeric values, runtime and memory for the affected cohort and bring the reread cost to the owner before OCR resumes.
6. Pin backend/model/render/routing identities; demonstrate that unchanged pages are reused and only qualified bad pages are replaced, with original evidence retained.
7. Complex pages may enter an explicit LLM/VLM comparison only when ordinary maintained paths are inadequate; retain source alignment, uncertainty, provider/model identity and cost. No LLM result is accepted from plausible prose alone.

## Notes

**2026-11-13T15:00:26Z**

2026-11-13: The full body-text run (body-text-full-20261110, PID 55948, resumed 2026-11-12 21:32Z after the publish yield) finished 2026-11-13T07:44Z at chunk-0173 with status pending: the work list is exhausted except 411 bodies blocked on missing copy metadata. The 2026-11-13 OCR recovery (codex/ocr-recovery-20261113 @ 56421715, .cache/archive-release/ocr-recovery-20261113, separate recovery catalogs) is retrying all 2,632 leftover bodies; at 14:37Z 2,164 had committed outcomes (1,058 completed, 1,083 parser errors, 23 unreadable) and all 411 missing-pin bodies completed. The typeset/scanned page count can now run over the complete OCR set.

**2026-11-13T17:46:16Z**

2026-11-13 plan reconciliation: the all-PDF feature pass is complete; reuse it and incrementally add recovery results rather than repeat the census. Native coverage/routing is ct-hz8y; page-local crash recovery is ct-t4p3. Retain this ticket's measured typeset/scanned split, fast Tesseract policy and owner cost/adoption decision. Add held-out source checks for garbled S143/S149 forms: accurate names, dates and checked choices matter even when completion and Unicode checks pass. Distinguish missing source/native text, cleanup loss and recognition errors. S138's missing prose bullets are now attributed to cleanup; generic engine replacement is not its fix.

**2026-11-13T18:48:44Z**

Rewritten from the independent ETL/greybeard/evolutionary audit. Prior notes and evidence remain below; old running-job and automatic reread assumptions are superseded. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T21:16:53Z**

Selective page policy/checkpoint composition is prepared; source review still governs backend choice and accepted selection. Direct reviewer /root/ocr_ticket_completion/pdf_recovery viewed S149 page1 and read sources/S149.native.txt plus texts/S149.txt under investigations/text-quantity-review-20261113. Native output is empty. Retained OCR keeps Ashli Watts/title/entity but corrupts question4, loses its visible No/X, and emits date ': 5 | 28/24' where the handwritten source reads5/28/26. This does not qualify any new backend. Q007 missing chart/table content and page125 alternate-setting failures remain cause-specific controls. Parent's C015 review found missing handwriting/date-order limits, so that page is only a cleanup-equivalence control. Tesseract/model/cost/classifier precision and any LLM comparison still require source-qualified output; no recognition/provider calls ran while paused.

**2026-11-13T21:49:06Z**

2026-11-13 assessment scope consolidated here after the user requested corpus-wide scoring and Keeplist inspiration. Reused the existing all-PDF feature pass (295,770 bodies / 7,764,694 recorded pages, 169.5 seconds remaining pass, 1.12 GiB peak RSS) and prior 376-case Keeplist comparison at current Keeplist commit fb1245c2. Two corrupted forms and S150 missing bullets passed that scorer, while 10/18 legitimate short originals failed: no web threshold is adopted. New plan docs/plans/corpus-text-assessment-20261113.md defines per-body/page provenance, explicit missing evidence, review priority separate from confidence, source-disjoint independent calibration, source/intermediary/output comparisons, selective repair routes and token/cost limits. Durable verified counts and plan: repairs/corpus-assessment-20261113/. User estimate is about 2.7 billion tokens; no full corpus run, OCR/provider recognition, publisher refetch or selection/publication change occurred.

**2026-11-13T22:02:11Z**

Implemented the bounded offline facts-to-proposal adapter in lake/text_assessment.py and cli/text_assessment.py; usage and limits are in docs/retained-text-assessment.md. It requires explicit source/actual-reading/output/page identities and named raw/intermediary/output review references, preserves unknown evidence and ordinal priority separately from calibration, and never opens evidence, selects text or dispatches work. Source-confirmed S055/S150 cleanup loss proposes renormalize from retained native intermediates; legitimate short S046 stays keep; S301 error response stays manual capture-history reconciliation. Independent coordinator directly read these four chains and confirmed the meanings. Their conflicting-output identity probe found and fixed a CLI duplicate-key defect; actual reading/page is now unique regardless of output hash. Missing intermediate OCR text does not imply native recovery; native_reread_supported/source_requires_recognition evidence is required to choose that stage, and OCR proposals need exact pages and remain paused. Tests:54 passed across three focused assessor/import/boundary files, followed by16 assessor tests after identity fixes (partial lanes, not a full-lane result). Durable evidence: repairs/corpus-assessment-20261113/. This adapter does not discover defects or establish corpus-wide accuracy; generation reconciliation and independent held-out calibration remain open.

**2026-11-13T23:17:11Z**

User clarified the scale as roughly 2.7 billion tokens across 7.7 million pages. The frozen census independently records 7,764,694 PDF page-offset slots; source-confirmed physical page counts and the token estimate remain distinct. No tokenizer/input scope has been pinned for the 2.7 billion estimate. The assessment plan now states both units explicitly and retains the Keeplist-inspired separate quality axes, direct source checks and held-out calibration requirement.

The bounded offline fact-to-action assessor merged through PR157 into PR156 and main. It emits proposals without dispatching OCR, fetching sources, selecting readings or claiming corpus-wide qualification. Current-generation reconciliation, missing-feature assessment and the held-out 200-body evaluation remain open. OCR stays paused and publisher refetch deferred.

**2026-11-14T05:42:24Z**

The frozen census and paused recovery now reconcile to 610,216 distinct bodies: 608,900 completed extraction states, 1,083 errors, 23 unreadable decisions and 210 held targets. The completed sets are disjoint (607,584 baseline + 1,316 recovery). The 612,137-row index retains actual historical reading/version keys and refusals; it does not restamp versions or turn document associations into accepted text selection. Association evidence remains bound to release 55c14dcda87a, not a later release's selected-text manifest.

Three additive packets close the named frozen-run evidence gaps without replacing original receipts: integrity for the final 66 outputs, native enumeration of exactly 2,399 recovery reading / 1,316 text keys, and unchanged-version PDF features for 916 new PDF bodies. The combined feature manifest reuses all baseline files and covers 296,686 PDF bodies / 8,141,096 stored page-offset slots. The delta inspected 806,874,296 retained text bytes in 32.3 seconds plus a reused 1.8-second pilot, with peak RSS 0.420 GiB; it performed no recognition, source-PDF scan or full baseline text rescan. No tokenizer count was made.

Independent reviewer /root/shared_reader_ci_finish approved core accounting and all three additive packets: 198 checks, seven directly read original-to-final metadata chains and one bounded actual retained payload; planted identity, completion, unsupported qualification and feature defects were rejected. Evidence: repairs/corpus-assessment-20261113/{current-reconciliation,tail-integrity-20261114,native-membership-20261114,pdf-feature-delta-20261114}/; report current-reconciliation/reviewer-shared-reader/independent-review.md. The plan now records the corrected population and units. Source quality, held-out calibration, source-qualified repair findings, current-version compatibility and accepted selection remain open. OCR stays paused and publisher refetch deferred.

**2026-11-14T05:52:05Z**

The four previously reviewed examples now join to frozen metadata by exact identities: S046/S055/S150 match their historical pdf_text keys, text hashes and page-1 feature records; S301's reviewed html_text intermediate matches while its response_roles/ct-response-roles-v1 observation remains private candidate-only. Independent reviewer approved 103 checks and rejected five planted wrong claims; source scopes, qualified=false and dispatch_allowed=false remain unchanged. Evidence: repairs/corpus-assessment-20261113/review-links-20261114/ (manifest 0ea4dab46c7ae43e1af268478006ce999aa418076e849f39865ef76677d0f3b5). This reuses existing direct semantic reviews, not fresh held-out data.
