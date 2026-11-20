---
id: ct-hz8y
status: closed
deps: []
links: [ct-kfsd, ct-n3ik, ct-a73a, ct-yy07, ct-55qo, ct-aitp, ct-m704]
created: 2026-11-13T17:46:16Z
type: bug
priority: 1
assignee: mikewolfd
tags: [body_text, pdf, ocr, routing]
---
# Finish selective PDF omission recovery using shared SpicyDocs backends

## Implementation update — 17 November 2026

CT now imports the maintained SpicyDocs Tesseract implementation through a narrow qualified backport, removing 220 duplicate implementation lines. The final wheel is built from source commit `bfd3c53993e7d988e616dee3c07eb52738642748`, SHA `ec4ebb122a7b8eb0075747f121a2e7c78a41260c3c35dcf129ad0b518f790e44`. Existing default reading IDs remain unchanged under the documented bounded equivalence decision; new opt-in Tesseract checkpoint identity records the backend implementation.

Terra-medium raw/intermediate/output review found that report pages 450, 772 and 1129 are sparse, redacted or short, without substantial visible prose loss at those sampled positions. This does not clear prior known omissions or unread pages. The f1 partial candidate reuses 43 successful page results exactly; pages 7–8 remain materially omitted/garbled after bounded Vision and Tesseract comparisons, so it remains held. No whole-corpus OCR was run.

Remaining: source-confirmed omissions, named handwriting/VFW/source-loss holds, and rotated-source fidelity. This ticket also takes the remaining generic adaptive/rotation raster consolidation from closed ct-yy07; that adapter remains local to CT, and any refactor must demonstrate a concrete simplification without changing default behavior. Evidence: `<main checkout>/.cache/archive-release/ticket-fixes-20261117/pdf/`.

## Audit baseline — 17 November 2026

Earlier native/regional and named-page repairs remain selected. v12 adds a selective Tesseract repair of the 1,208-page report `251ea1a6d6819b6f01e471cf4d22e924beea8e831c38ae1a4313c6bdd79b01cf`; direct review confirms substantial prose restored on sampled pages. Its staging comparison tests ten positions and inherits 1,198 other positions from older Vision output. Preserve partial-repair limits until a cheap screen and targeted review address remaining substantive omissions. This is not a requirement to manually read or OCR every page again.

The newer CT `pdf_opt_in.py` duplicates the Tesseract C API loader, trained-data pins, handle and recognition wrapper already in SpicyDocs `extraction/ocr.py`. CT's pinned backport wheel lacks that newer backend; use a qualified shared dependency update/backport, not an import to a missing API. Native-first Apple Vision remains the default policy.

## Scope and ownership

Own content-based fallback selection, recognition/composition qualification and reuse of the shared Tesseract backend. ct-yy07 owns rendering/geometry bounds; ct-a73a owns resource/source outcome accounting. Keep exact page policy, reading versions and acceptance in CT. Reuse regional/page APIs, completed checkpoints and existing source reviews. Character count, vector ink and output length alone do not prove completeness.

## Acceptance Criteria

1. Reconcile the existing Q005/Q007/Q009/Q010 and S167/S188 criteria against already selected repairs; retain named VFW page 105, handwriting, table/script and source-loss holds without reopening accepted work. Useful searchable prose is the target, not perfect structured transcription.
2. Record exactly which long-report positions changed and which remain inherited. Use cheap existing measurements to nominate remaining losses, then read bounded raw -> actual intermediate -> final examples. Substantial invented or omitted prose fails; ordinary spelling, order or numeric limitations stay explicit.
3. Replace the duplicate CT Tesseract implementation with the qualified shared backend. Preserve effective trained-data/library/configuration identity and compare actual consumer outputs before keeping or deliberately changing declared versions. Coordinate the shared-reader pin with ct-yy07.
4. Preserve legitimate blank/short pages, covers, repeated amendments, roll-call forms, redacted grids, rotated tables, sidebars and non-Latin content. A planted substantive omission must be caught; source evidence must justify page selection and composition order.
5. Apply only qualified changed keys through ct-m704, retaining partial-output limitations and old refusal history. Bulk manual PDF/page reviews use gpt-6.1-terra at medium reasoning. Do not change the default OCR engine or replay the corpus as a side effect.

## Audit evidence

17 November manual audit: `<main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md`; PDF sample: the sibling `pdf-manual-review.md`. New v12 files: `<main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/body-text-ssot-20261116/`. These evidence files retain the exact inputs, identities and sampled/unread scope. Historical notes below are dated evidence; the current scope and criteria above supersede their unfinished-work summaries.

## Notes

**2026-11-13T17:46:16Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.

**2026-11-13T18:48:44Z**

The audit visually rechecked S167 page 1 and Q007 page 6. Count >=50 is not a coverage test. Reuse upstream region/override APIs, but qualify reading order (unanchored regions append). ct-aitp owns page persistence; ct-55qo owns final selection. The 18,777-body triage inventory is a candidate inventory, not 18,777 confirmed failures. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T21:16:53Z**

Exact-source/page candidate routing is now implemented with PageRule.page_overrides around maintained spicy-docs strategies. No generic density/image threshold was substituted for source qualification and no production override was adopted. Direct content review by /root/ocr_ticket_completion/pdf_recovery: Q007 page6 original contains the European debt table (Belgium96.20, Germany83.20, Greece144.90) and G10 stacked chart/legend; retained native and final text contain only Figure3/Figure4 captions. Chain: .cache/archive-release/investigations/text-quantity-review-20261113/quality-expansion/{sources/Q007.pdf,renders/Q007-p0006.png,renders/Q007-p0006.native.txt,renders/Q007-p0006.retained.txt}. No new recovered output exists while OCR is paused; named-page recovery/held-out accuracy remain open. Parent review also found C015 preserves printed fields but omits the visible handwritten signature and moves its printed date; it is a cleanup/selection-equivalence control, not a fully transcribed form.

**2026-11-14T12:31:10Z**

Five-step follow-through: ct-n3ik owns queue priority and cause-to-owner routing; ct-0a35 owns source-to-search verification. Prioritize search-visible substantial omissions and reuse retained native/page evidence for the next bounded diagnosis. Native-only inspection and safe composition can continue, but actual OCR/provider recognition remains paused. Preserve per-page causes and unresolved evidence; do not restart or re-OCR the entire PDF corpus for this plan.

**2026-11-14T16:48:30Z**

New direct source/intermediate/output evidence is accepted-text-adoption-20261114/seven-manual-review/review.md, SHA cc8ed9bf76156aed4330925993cf14e31901dd935f58c8e081f3c263f6022215. ee7ad6da has 217 stored slots, 216 newline bytes and no useful output; only 1/109/217 were read, so whole-body repair is a candidate scope, not 217 reviewed pages. For 228ddad5 feature run 102–110 has direct omission at 105; for 3a21a04f run 134–149 has direct omission at 140. Do not infer all flagged pages contain prose. Existing partial text remains useful for FTS. No new OCR was performed by this review; user has separately authorized targeted OCR/refetch.

**2026-11-14T17:16:28Z**

The fresh no-OCR native probe is accepted-text-adoption-20261114/seven-manual-review/current-native-route/summary.json. Five source-confirmed omitted pages have native_nonspace=0, image_count=0 and would_recognize=false; four useful neighboring controls report images and route to recognition. This is current routing evidence, not the historical intermediary or proof of vector content. S002 body 131d34ba7fa4baec9299358bedb4576101957d794fb407d57a85063033a2ffd4 is a prior directly reviewed one-page biography omission and remains selected at the baseline version. Authorized candidate generation is restricted to these six pages. New interpretations require their own actual identity and independent Terra medium raw/intermediary/output review.

**2026-11-14T18:47:49Z**

Groq Qwen was tested once on the difficult 228ddad5 page105 with the recovered six-key JSON schema and exact minimal fidelity prompt. Schema-valid qwen/qwen3.8-27b output invented sections and substantive testimony and omitted real source sections, so Terra rejected it. Both 200/400-DPI Vision candidates also remain rejected for major omissions; confidence did not predict usable text. Baseline-six source and four-candidate reviews are accepted-text-adoption-20261114/baseline-empty-manual-review-20261114/{report-02.md,repair-review.md}; source custody, actual raster/detections and final text are pinned. No model output is relabeled as a Vision checkpoint. All four new one-page candidates and page 140 are now appended with exact readback. V3 preserves the other 150 pages of 3a21a04f unchanged. The cheap-screen followup also directly confirmed broken native word boundaries on f6d8df26 page 1, before cleanup; a separate 5e3f6444 page 1602 is mostly searchable with one letter-spaced line. Evidence: ocr-checkpoint-resume-20261114/quality-screen-20261114/manual-review/. Do not infer all 1,301 flagged f6 slots have been source-reviewed.

**2026-11-14T18:51:48Z**

Next bounded repair target: f6d8df26 page 1 loses normal whole-word search because its native output splits FOREIGN OPERATIONS and other words into letters before CT cleanup. Compare maintained alternate native extraction on that exact retained page before considering recognition; qualify unchanged ordinary text and the localized letter-spacing case on 5e3f6444 page 1602 as controls. The 1,301 flagged f6 slots nominate broader evaluation but do not establish a source-reviewed whole-body replacement.

**2026-11-15T04:46:39Z**

Direct Terra medium review read all 45 unresolved one-page PDF originals and their actual empty outputs: 26 omitted visible writing, 18 contained images without prose and one was blank. Thirty-two tiny XML files were directly read as ASX media playlists. The 26 PDF candidates reused maintained SpicyDocs NativeOrOcr (25 OCR calls, one native-only result); one map required maintained NativeWithRegions to restore the full legend including 'Not Destroyed'. Actual new intermediaries and final outputs were read directly. The 26 actual pairs (36,529 UTF-8 bytes) are adopted and selected in accepted-set-v4; independent review edc9fa09fc686eea5ac1bcab88183ff8952ef7d8b4f7de6170eaa7a02a4fed8e checks all 52 native files and preserves checkbox/table/column/map qualifications. Evidence: corpus-assessment-20261113/triage-current-20261114/{empty77,empty26-candidates,map-legend-region-20261115}. Separately, ocr-checkpoint-resume-20261114/native-word-spacing-probe-20261114 compares maintained native readers on f6d8df26 pages 1/739/1476 and a 5e3f6444 control. Both native readers fragment words; exact-page OCR repairs page 1 usefully, but both three-band and one-band page739 candidates omit real passages in recognition itself. Neither partial page739 candidate is a complete repair or adopted whole-body replacement.

**2026-11-15T07:05:12Z**

Accepted-set-v5 independently passes: seven final repairs selected from eight actual appended pairs; the font intermediate remains history-only. Six PDF finals recover 14 formerly unsearchable pages plus 52 font-corrupt pages. Evidence: repairs/accepted-text-adoption-20261114/accepted-set-v5-independent-review/handoff.json SHA 6db4eeaea8f06f29e2d7326fcf48198c183b86a2d45524fe14987065d61c4826. New named-coverage work separately staged ten Q005/Q007/Q009/Q010 pages and four S167/S188 pages, with direct raw/candidate/output reading and explicit partial FTS limits. Q009p37 has a useful reviewed Groq Qwen candidate, held outside composition because provider provenance is unsupported by the current helper. S167 remaining seven pages are in targeted review. These stages are not adopted.

**2026-11-15T07:55:50Z**

Accepted-set-v7 independently passed after eight actual PDF pairs were appended: six compositions/22 replacement pages and two retained-native one-page replays. Result repairs/accepted-text-adoption-20261114/accepted-set-v7-independent-review/result.json SHA15865e8b2d59ccbc30f1a1f36d8a8e46aae9ea077f45c4a61451f856f6aeea2c; selection SHA22756dbf6e8db2702532c26362bbbc1ba302e9841176f05aa1ee2f742f03677c. All1199 prior overrides/26exclusions/321 dispositions preserved; final1207 overrides,311716 selected texts,8142224 slots,2727045 OCR markers,57 valid empties and274 selected errors. Actual16 native rows match all fields; old eight reading controls suppressed and planted wrong digest rejected. Useful partial FTS limits remain explicit; no full export or SereneDB claim. Native replay versions truthfully preserve original refusals; no default policy restamp. Twenty-two source pages were previously directly reviewed; inherited pages were not newly audited.

**2026-11-15T07:55:50Z**

Acceptance wording now follows the user's practical FTS requirement: useful searchable prose and labels, with named numeric/table/script/signature limits. It does not require perfect structured transcription. Substantial missing or invented passages still fail review; the prior rejected map negation and Groq invention evidence remains.

**2026-11-15T10:52:31Z**

f6 evidence: repairs/ocr-checkpoint-resume-20261114/native-spacing-repair-20261115/. Actual candidate version 829114fe1f30609a05353467fd62ae9132cf0262923602303f6b17727bb63aa1, text SHA 9928a8d507330201b1f86f986e052b230f156531aba61aa9eb2ea4600df0e7de, 4,206,117 UTF-8 bytes. Run: 49 seconds / 0.665 GiB peak RSS. Independent review/pins cover nineteen exact source/intermediary/final pages; seven newly reviewed empties are visibly blank, with p1476 already source-proven blank. The no-final-GPO policy produces 419 non-whitespace final differences: 169 are strict additions and 250 include punctuation/format substitutions. All 1,476 prior NFKC letters/digits sequences remain subsequences of actual candidate pages, with zero exceptions; this is preservation evidence, not source accuracy or word-boundary certification. Useful sampled prose retains minor source-layer spelling, TABLE OFC ENTS, date and table-order defects. Shared option PR32 remains separate from CT candidate adoption.

**2026-11-15T12:11:18Z**

Accepted-set-v10 selection SHA eb8473ab6163d3ab4b16f4fa56754a5b72b9391065aeedf3138db02eaaf3b111; native snapshots body_text 4383126096555098411 and readings 6734786965736914418. Independent result SHA 016d5932ef5a62d09a706974da210c7adb37e026efc19b8a833529f8568cd9d0 verifies all 388 new native pairs, append ancestry, all 1,217 prior choices, 339 prior disposition lines, preserved dbaa and rejection of a planted wrong digest. The new delta contains 234,583,311 UTF-8 bytes / 114,416 slots / 80,443 OCR markers. Source review covers 94 of those slots; 114,322 remain source-unread with exact limits retained. The shared native_inhibit_spaces option merged in SpicyDocs PR32 at b51b338fef18806b8c0db7759ebf793b4adebb2a with CI passing. F6 actual version 829114fe… selects 4,206,117B/1,476slots/11OCR; prior normalized alphanumeric sequences survive on every page, which is preservation evidence rather than source accuracy. 4f6 final version abbffbd3… selects 968,281B/443slots/387OCR. A full-page one-band result omitted caption/headers; the Groq response repeated the table until its token limit and failed schema validation, with invented prose also observed. Both remain rejected. The regional result passed direct Terra source/crop/raw-observation/final review; 169 GtC is misread as 169 GHC and table/citation associations remain imperfect. Final-page composition preserved 442 inherited slices byte-for-byte. Evidence: strong193-4f6-p223-regions-20261115 and strong193-4f6-composition-20261115.

**2026-11-15T13:34:45Z**

The large-report pilot used the intentionally frozen pre-PR31 merger; replaying the maintained fix restores two readable boundary lines and one garbled fragment but does not repair larger Vision omissions. 300-DPI/one-band Vision has no uniform advantage. Direct Terra review of Tesseract pages 7/302/604/906/1208 supports a bounded fallback investigation: useful substantive passages, with a lost sender title and email/timezone errors on the control plus minor word/citation defects. Shared SpicyDocs already implements Tesseract fast/eng/PSM3; its actual consumer output must be checked because it estimates resolution whereas the diagnostic CLI specified 300 DPI. No corpus-wide engine change or whole-report acceptance occurred.

**2026-11-17T09:17:02Z**

Manual audit credits v12 selective Tesseract improvements and prior named/regional repairs. Rewritten to retain limits on the 1,198 inherited long-report positions, existing named holds, and a qualified shared Tesseract backend adoption. CT currently duplicates upstream code because its pinned backport wheel lacks that backend; a qualified pin/backport is required. No default engine switch or corpus-wide OCR is implied. Audit evidence: <main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md.

**2026-11-17T10:28:52Z**

Implemented selected 80/20 scope via subagents. The current implementation update above records completed work, exact evidence and remaining acceptance. Full evidence is under <main checkout>/.cache/archive-release/ticket-fixes-20261117/. Historical notes are preserved.

**2026-11-20T23:26:57Z**

2026-11-20 closure. Verified Explorer 0e7084cde775 and v13 body_text 7aea7925da32. Exact released bytes preserve 22 reviewed substitutions in Q005, Q007, Q009, Q010, S167 and S188. Q009 page 37 is the later qualified Groq/Qwen composition and page 47 retains Vision provenance. Table values, chart associations, the Cherokee sidebar, handwriting and the missing VFW page 105 remain explicit limits. No new selection keys were qualified.

All 1,208 report slices were compared by UTF-8 byte offsets and hashes. Pages 7, 302, 604, 801 and 906 changed. The other 1,203 are byte-identical to the pilot, including five comparison controls and 1,198 positions outside the staging comparison. Bounded source/intermediate/final review confirms substantive recovery on 7, a missing testing passage on 151, a heading and strike-through error on 740, and legitimate redaction on 772.

The pinned SpicyDocs Tesseract backend already owned OCR. CT now delegates PDF rendering, both allocation guards and raster encoding to that same wheel, retaining the opt-in adaptive DPI and rotation settings. Sixteen prior/current source-backed raster pairs and both Tesseract strategy outputs matched. The planted omission triggered the existing selective review signal while clean and reflowed controls passed. Default native-first Apple Vision, reading IDs and the v13 selection are preserved. Doctor passed with zero drift warnings.

Evidence: /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/long-tail-20261120/pdf-ocr/ct-hz8y-251ea1a6-positions.json and ct-hz8y-reconciliation.json in the same directory. Tests and published outcomes are summarized in ct-a73a-summary.md. No corpus replay or remote mutation.
