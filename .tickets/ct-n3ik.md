---
id: ct-n3ik
status: in_progress
deps: []
links: [ct-a73a, ct-kfsd, ct-hz8y, ct-t4p3, ct-55qo, ct-aitp, ct-f6hr, ct-fb7k, ct-0a35, ct-en4n, ct-cbkz]
created: 2026-11-11T15:40:45Z
type: feature
priority: 2
assignee: mikewolfd
tags: [ocr, pdf_text, readings, tesseract]
---
# Cheaply find failed or substantially incomplete text extraction for FTS

The user clarified on 14 November that the primary purpose is full-text search (FTS). Find failed, empty, badly garbled or substantially incomplete OCR/extraction cheaply across the retained corpus. Perfect transcription, exact form-field fidelity and reading every document with an LLM are not required. Minor mistakes can coexist with useful searchable text. Targeted OCR/refetch is separately authorized as of 14 November; this assessment command does not dispatch either job.

## Design

Use existing reading status, output metadata and PDF page features first. Flag missing/error outputs, unexpected near-empty text, substantial page gaps, repeated headers with little body text, severe corruption and known error-response structures. Treat legitimate short amendments, blank/photo pages, forms, tables and metadata/feed containers according to their purpose; short text alone is not extraction failure. Keep missing measurements distinct from observed defects.

Produce practical review bands with reasons and body/page locators: known failed, suspicious, no obvious failure detected, and unassessed. These are triage results, not probabilities or automatic repair/selection decisions. Preserve runtime failures separately from text-quality suspicions. Use bounded native-to-final comparison where the intermediate already exists to identify substantial lost passages. Reuse spicy-docs and CT's maintained response-role reader; do not import Keeplist's web acceptance threshold.

Reuse the retained page features and completed 376-case Keeplist applicability study. The frozen batch-205 feature generation is reused unchanged, and a separate four-row delta now brings coverage to 296,690 PDF bodies / 8,143,043 recorded page slots. The independently reviewed checkpoint builder now produces a final-markup queue of 45,106 candidate/control rows, including 1,182 priority 0–2 rows; these are not defect counts. Do not reread the entire baseline text merely to repeat existing measurements. Additional cheap text signals may use bounded samples or a justified incremental pass. Use a small independent raw/intermediate/output spot check, including ordinary no-trigger and legitimate short/blank controls, to catch obvious bad rules. A 200-body calibration study and word-perfect source qualification are not prerequisites for this FTS triage.

ct-hz8y owns native/vector repair, ct-kfsd cleanup exposure/publication, ct-cbkz/ct-f6hr markup reparse, ct-en4n source roles and ct-z4w5 reviewed refetch. ct-55qo owns selected readings and ct-aitp page persistence. Earlier Tesseract-fast candidate preferences remain available for later selective repair; backend comparison, provider execution and publication are separate from completing the cheap screen.

## Current exception queue and remaining work

The metadata-only checkpoint queue combines existing PDF feature rankings, actual reparse/recovery outcomes and bounded response-role observations from ct-fb7k/ct-en4n. The final markup refresh is complete without another whole-corpus payload scan. Broader non-PDF garbling and source-role coverage remain explicit gaps. Join exact source/reading/output identities; expose selected-document effects with a named release, retaining unknown or stale exposure explicitly. The 400 response examples are annotations on existing bodies, not additional corpus counts.

For each candidate record the reason, observation basis, FTS impact, priority, page or text locator, least-cost remedy, required evidence and owning ticket. Use the existing review bands, with missing evidence separate from observed defects. Prioritize search-visible missing content and substantial omissions ahead of low-impact formatting. Keep ordinary short/blank/photo/metadata/feed controls usable according to their role.

Route cleanup to ct-kfsd, native/vector recovery to ct-hz8y, geometry to ct-yy07, markup failures to ct-f6hr, crash recognition to ct-t4p3 and unresolved sources to ct-z4w5. Reuse known repair evidence and checkpoints; separate coordinators execute the authorized targeted work. ct-0a35 verifies accepted changes through the actual search consumer.

## Acceptance Criteria

1. Give the frozen retained population explicit dispositions using exact actual reading identities. Preserve unsupported, pending, refused and missing-evidence states, and state any generation coverage gaps.
2. Run transparent, cheap checks for unsuccessful or substantially incomplete extraction and retain actionable reasons/locators. A low quantity or harmless formatting change alone must not declare a document bad.
3. Check known major failures and legitimate controls, then directly spot-check a small independent sample of suspicious and ordinary outputs against retained originals/intermediates. Report obvious missed failures and false alarms; do not claim exhaustive or word-perfect accuracy.
4. Report elapsed time, peak memory, inputs reused and any payload bytes newly read so the screen can run economically across the corpus. No LLM-per-document review or original-PDF scan is required.
5. Leave one deduplicated selective repair/reparse queue with explicit reasons, search exposure, cheapest next action, owning ticket and unknown evidence. Account for all included input keys and generation gaps; a source-response finding is not an extraction-runtime failure.
6. Rank the next bounded repair batch by search impact and demonstrated cause. Keep accepted readings unchanged and perform no OCR/refetch dispatch in the assessment command. Missing source fidelity and a mandatory 200-body calibration study must not block useful priorities.

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

**2026-11-14T10:33:06Z**

2026-11-14 source-quality focus resumed. The Keeplist applicability study is complete; the implemented text_assessment adapter only routes supplied facts and does not detect defects. Corpus accounting and stored-output integrity are prerequisites already completed at their stated frozen scope, not source-quality acceptance. Active owners: corpus_current_reconciliation implements CT-specific measurement/ranking over retained page features and bounded native/final comparisons; regs_local_boundary_review checks maintained Keeplist reuse; shared_reader_ci_finish performs independent direct raw/intermediate/output review without new ranking labels. A small first held-out tranche starts the planned evaluation; the 200-body calibration criterion stays open. Reuse the existing PDF feature generation, keep four late batch207 outputs explicitly outside it, and retain OCR paused/refetch deferred. Do not close this ticket from proposal output or bookkeeping.

**2026-11-14T10:52:02Z**

Owner clarification supersedes the earlier 200-body calibration requirement: the goal is cheap screening for FTS usefulness, not perfect transcription. Prioritize failed/empty/severely garbled/substantially incomplete outputs with existing metadata and page statistics, plus a small direct spot check. Do not require per-document LLM review, exact form-field fidelity or corpus source certification. Lead/design/acceptance and the assessment plan were rewritten accordingly; prior evidence is retained. First all-format quantity summary covered 607,584 baseline bodies in 0.538 seconds at 0.11 GiB peak RSS with no source/text payload opened; 4,039 empty outputs are review signals, not confirmed failures. OCR remains paused and publisher refetch deferred.

**2026-11-14T10:59:49Z**

First cheap FTS screen is implemented at b6d2865f (documentation at 003244f5). Reused 296,686 PDF feature rows / 8,141,096 recorded slots in 9 seconds at 0.83 GiB peak RSS, reading no PDF or text payloads: 543 review_first, 38,583 review_later, 257,560 no_obvious_failure_detected. These are heuristic review bands, not defect counts; most weak signals are possibly legitimate blanks. All-format baseline quantity summary covered 607,584 bodies in 0.538 seconds at 0.11 GiB. The independent eight-body / fourteen-page FTS spot check found useful search text in every sampled body, while exposing chart and OCR-bullet omissions these cheap checks miss. Existing reviewed repair findings remain valid regardless of a no-trigger result. Focused tests: 35 passed in two files (partial production-offline lane); independent frozen-code review and direct source/planted-control probes passed. Durable evidence and ranked queue: repairs/corpus-assessment-20261113/source-quality-pilot-20261114/. Non-PDF roles/garbling are not comprehensively screened; four late batch207 outputs remain outside the PDF feature generation. Further format-specific triage and selective repair remain open, without a mandatory 200-body calibration gate. OCR stays paused and refetch deferred.

**2026-11-14T11:59:01Z**

Added the 400 recovered markup bodies as reusable examples in the existing inventory lineage at repairs/corpus-assessment-20261113/response-examples-20261114/. They are annotations on existing body keys, not 400 new corpus bodies. Expected source-role labels are 384 error-template examples, two bounded ordinary metadata/landing controls and 14 unknown; completed extraction is a separate field. Raw/archive, actual reading and historical/current text identities are retained. The independent direct M002/M004/M005 review found only whitespace changes and preserved source roles; it does not qualify all changed outputs. Use this development/regression collection to improve cheap response detection, preserving template-family grouping and unknown labels. No broad LLM review, OCR, refetch or selected-text change occurred; broader non-PDF screening remains open.

**2026-11-14T12:31:10Z**

Specified the next concrete deliverable as one exact-key exception queue with reason, evidence basis, search exposure, priority, locator, cheapest remedy and owning ticket. It combines retained PDF features and current markup/recovery outcomes, including ct-fb7k/ct-en4n observations, without another baseline payload scan. Existing case memberships are not added to corpus counts. OCR/refetch remain paused/deferred; perfect transcription and a 200-body study are not gates.

**2026-11-14T14:33:16Z**

The independently reviewed metadata-only exception queue is retained at repairs/corpus-assessment-20261113/exception-queue-20261114/checkpoint-v2/: 45,102 unique candidate/control keys, including 1,166 priority 0–2 rows. All 2,632 recovery targets, all 400 response examples and the four late PDF outputs are represented; no selection or dispatch follows. Build: 1.432 seconds / 0.889 GiB, no source or text payload read. Independent review: exception-queue-20261114/independent-review-v2.md.

The missing four PDF feature rows are now added under the unchanged feature definition in late-batch207-features-20261114/: 4,394,643 retained text bytes, 0.301 seconds / 0.116 GiB, no PDF or OCR. Combined coverage is 296,690 bodies / 8,143,043 recorded slots. All four receive only weak possible-blank signals. Older generation receipts remain intact.

publication-state-20261114/ binds a separate association overlay to release 4b9a7bd126cc17e39dfbe7f8fabafbdb7251dcd32576277f308916f469c9bab1: 823 priority0–2 keys have unhidden document references; all400 examples have none. The exact detail SHA is bed19d968ef2aeb083e87fc012b2298396f8fae99620a5bc9b6a88f1c4197c87. Independent review approves association claims only. Final markup reconciliation and broader non-PDF signals remain open. Any bulk manual PDF/page audit uses gpt-6.1-terra with medium reasoning. OCR paused; refetch deferred.

**2026-11-14T15:08:53Z**

Final metadata-only refresh reuses the approved unchanged v2 builder plus final markup outcomes and four additive old-recovery PDF feature rows: 45,106 candidate/control rows, 1,182 priority0–2, 1.515 seconds / 0.91 GiB RSS, no source or text-payload scan. Reused PDF coverage is 296,690 bodies / 8,143,043 recorded slots. Exact current release association overlay finds 834 unhidden priority0–2 bodies; all400 examples have no associations. Neither priority nor association is a proven defect or accepted search coverage. Evidence: repairs/corpus-assessment-20261113/exception-queue-20261114/final/ and publication-state-final-20261114/. Inherited paused/deferred labels describe the frozen old recovery snapshot; the user now separately authorizes targeted OCR/refetch. Final35 cause decisions are retained separately pending queue enrichment.
