---
id: ct-kfsd
status: closed
deps: [ct-55qo, ct-m704]
links: [ct-a73a, ct-n3ik, ct-hz8y, ct-0a35, ct-m704]
created: 2026-11-13T17:46:15Z
type: task
priority: 1
assignee: mikewolfd
tags: [body_text, pdf, ocr, publication]
---
# Finish historical PDF cleanup exposure and corrected-text delivery

## Implementation update — 17 November 2026

Actual full-export readback passed for all 32 identified corrected/control bodies: eight earlier corrections, six unchanged controls and eighteen later cleanup repairs. Exact selected text hashes survived; the current-release handoff preserves the same export and source-review limits. Evidence: `<main checkout>/.cache/archive-release/ticket-fixes-20261117/text-handoff/cleanup-readback/result.json` and `final-report.md`.

Remaining: the broader historical affected-set/exposure reconciliation. These 32 verified bodies do not establish that all historical cleanup losses have been discovered. Reuse their completed correction and delivery evidence; do not re-OCR them. Any later public readback belongs to the same ct-m704 delivery path.

## Audit baseline — 17 November 2026

Eight earlier source-qualified GPO-corrected pairs and 18 additional v12 cleanup repairs are selected locally. The complete v12 export exists and includes corrected text; the old v4/no-export summary is superseded. Prior 14-body/281-page source qualification, six unchanged controls, actual keys and the newly qualified archive-file composition cohort remain reusable evidence.

Remaining work is the historical affected-set reconciliation and readback of corrected rows at the intended delivery boundary. The export targets release `55c14dcda87a`; ct-m704 owns its reconciliation with the newer release, quality associations, authoritative catalogs and combined handoff. This ticket owns the cleanup-specific exposure and restored-passage checks, not a second publisher or text export.

## Acceptance Criteria

1. Reconcile the retained cleanup queue with current selected keys and release exposure. Name affected and unassessed records; do not globally restamp old outputs or assume a short-text sample is a complete predicate.
2. Credit existing S017 tail and S055/S150/S138 bullet qualifications where identities match. For any additional affected set, prefer retained-text renormalization; reread or OCR only when source evidence requires it. Preserve real printing footers, legitimate blank/short pages, numbered prose and intentional ambiguous labels.
3. Verify restored substantive passages, text hashes, offsets, OCR provenance and one selected version through ct-m704's actual delivered export. Record local versus public readback explicitly. Retain source-confirmed composed archive-file evidence where claimed, prior readings and diagnostics-size measurements.
4. Retain a bounded direct raw -> intermediate -> final review and planted-omission rejection for changed cases; use gpt-6.1-terra at medium reasoning for bulk PDF review. Route geometry, recognition, missing sources and search behavior to their existing owners. No broad PDF OCR replay.

## Audit evidence

17 November manual audit: `<main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md`; PDF sample: the sibling `pdf-manual-review.md`. New v12 files: `<main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/body-text-ssot-20261116/`. These evidence files retain the exact inputs, identities and sampled/unread scope. Historical notes below are dated evidence; the current scope and criteria above supersede their unfinished-work summaries.

## Notes

**2026-11-13T17:46:15Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.

**2026-11-13T18:48:44Z**

Use ct-55qo for one qualified actual reading key per body/parser, including unaffected baseline and recovery results. Use ct-aitp only when new page work is necessary. Prefer reassembling qualified retained pre-cleanup pages to OCR; existing diagnostic logs are not automatically reusable checkpoints. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T21:31:52Z**

Bounded qualification now also exercises real accepted-key composition:14 source-backed PDFs/281pages,8 changed GPO corrections+6 byte-identical actual-version carry-forwards,0 pending PDF work,6 unselected newer attempts. Local export84d893dcff17b58741b903a7481e6cbf7174b2b53becc6ad26fd085d28d0c86c;14 diagnostic files total8,308,326bytes. Direct reviewer /root/ocr_ticket_completion read S055/S150 bullet chains and S017 physicalpage57 tail through raw image,native text,extraction/cleanup diagnostics,corrected text and actual export row; root independently confirmed S055. C015 unchanged control retains printed fields but omits visible handwriting, so equality does not prove complete source quality. Durable exact paths/hashes/limits: repairs/selection-offline-20261113/{data-review.md,direct-review-artifact-hashes.json,exposure.json,result.json}. The whole historical affected-body predicate, composed-WARC cohort, full release gates, production adoption and published readback remain unfulfilled; no closure or production selection change. This work reused retained page outputs and ran no OCR/refetch.

**2026-11-14T12:31:10Z**

Added the first selective-repair batch: prioritize source-confirmed, search-visible cleanup losses from ct-n3ik; reuse exact retained intermediates and reviewed consumer outputs before native rereading. Preserve before/after identity, direct raw/intermediate/output review and accepted-selection readback. ct-0a35 verifies restored passages through search. OCR remains paused; unrelated native/geometry/recognition/source causes stay with their existing owners.

**2026-11-14T14:33:16Z**

Current metadata independently confirms that all14 privately qualified correction/control bodies each have one unhidden document association in release 4b9a7bd126cc17e39dfbe7f8fabafbdb7251dcd32576277f308916f469c9bab1. This does not establish publication of the eight corrected readings. Reuse the existing direct 14-body/281-page qualification and actual reading keys instead of repeating PDF/OCR work.

Native adoption planning now pins the separate920 completed recovery PDF keys and existing8 correction overrides/14 selected identities in repairs/markup-reparse-20261114/adoption-planning-20261114/{pdf-adoption-inputs.json,recovery-pdf-actual-keys.jsonl,README.md}. The eight overrides do not overlap those920 bodies. Keep old baseline PDF keys at their actual versions; do not restamp them to the current declared parser. The observed public manifest has no text index and the checked body-text pointer returns404, so production adoption/export/search readback remain pending ct-m704/ct-0a35. Bulk manual PDF/page audits, if any new scope needs them, use gpt-6.1-terra medium.

**2026-11-14T16:48:30Z**

Eight actual 4d045589 correction pairs adopted with field/hash parity at text snapshot 4606969079641435643 and reading snapshot7411791213520479856. Root initial accepted set under accepted-text-adoption-20261114/accepted-set-v1/ pins baseline 2980a4db plus 944 exact exceptions and 11 source exclusions; native validation and full-delivery admission are underway. Existing 14-body source qualification remains unchanged. The new retained-index adapter passes ordinary/repaired/excluded real MCP proof but has not yet been published or applied to these eight cases.

**2026-11-14T18:47:50Z**

Accepted-set-v3 preserves all eight actual 4d045589 corrections and the six baseline controls, and reuses their source-qualified and payload-validated identities. Additional final-page repairs use distinct composition identities rather than restamping GPO or historical parser versions. Public search acceptance is not implied by local table consistency.

**2026-11-15T04:46:39Z**

The current selection is accepted-text-adoption-20261114/accepted-set-v4/selection.json, SHA 0f5bfec953b7c0e0f85d92b437da3e8e4c6245e7f4c5542efac8391deb10479d. The independent delta review proves all 956 earlier overrides unchanged and all earlier native manifest references retained. Do not repeat the GPO control reviews solely because 26 unrelated empty-output repairs were appended. ct-n3ik is completing the exact-current-key corruption screen/exposure queue before selecting another bounded historical cleanup batch.

**2026-11-17T09:17:02Z**

Manual audit credits eight earlier corrected pairs, 18 additional v12 cleanup repairs and the complete local export. Narrowed to remaining historical exposure and cleanup-specific corrected-text readback through ct-m704 delivery. Added that delivery dependency instead of retaining a separate implicit publishing path. Existing source/printing-label controls and source-review limits remain reusable. Audit evidence: <main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md.

**2026-11-17T10:28:52Z**

Implemented selected 80/20 scope via subagents. The current implementation update above records completed work, exact evidence and remaining acceptance. Full evidence is under <main checkout>/.cache/archive-release/ticket-fixes-20261117/. Historical notes are preserved.

**2026-11-20T23:30:12Z**

Completed published cleanup readback against Explorer release 0e7084cde775d0064646c56b2200a14e1f13d8b512f1a61a6fe815d597faf4d3 and body-text v13 7aea7925da324273d16c04e7dd7d53b2a7d3a0ade895f9343063015458d88688, selection bbeb4e1c94e195ac8ec5085578331543b2b2f709e77d2c83e523474e07bbe10b. The R2 pointer binds the exact detail digest and body_text snapshot 8592324397432329908. The release contains one unhidden saved document for each of the 32 PDFs. All eight early corrections, six unchanged baseline controls and 18 later corrections match their qualified text in full, with the same UTF-8 page boundaries. The six controls are C005, C006, C007, C009, C014 and C015. C015 preserves the printed fields and the known handwriting omission. The restored pages for S055, S150, S138 and S017 (physical page 57) match their reviewed page files exactly. These four are the entire named ct-kfsd historical exception queue.

All 8,505 composed WARC/ARC bodies have current Explorer associations and v13 text. Each published digest and page map matches its qualified composed output. Read full published text for the 24 source-reviewed archive samples as well as all 32 cleanup/control PDFs. All 8,537 selected parser/version keys, text digests, page maps, OCR page lists and build fields agree with the pinned native text snapshot. The published pointer reports zero truncated rows. The full 326,929-row object supplied only its metadata columns, plus text from the 37 row groups containing the 56 targeted SHAs. The 14 earlier diagnostic files total 8,308,326 bytes. Direct source review and planted-omission evidence remain pinned to the original qualifications.

The ledger names all public link keys, saved SHAs, character and byte counts, selection sources, versions, review limits and recovery associations. The separate historical scope table names 298,684 other PDF bodies, of which 297,936 have v13 text. These bodies have no cleanup-fidelity certification from this reconciliation. The scope unites the frozen PDF screen and exception queue with current selected PDF readings and current saved PDFs. No OCR or publisher refetch ran.

Evidence is under /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/long-tail-20261120/pdf-source/ in ct-kfsd-reconciliation.json, ct-kfsd-summary.md, ct-kfsd-unassessed.parquet and v13-readback.json. The local runtime doctor passed. The production-offline targeted file passed 21 tests (one of 601 lane files). Tests reject a planted missing bullet, a lost substantive tail after a printing footer, an incorrect UTF-8 offset and wrong or repeated selected versions. Hosted search remains with ct-0a35.

**2026-11-20T23:33:09Z**

Final verification checks that each of all 8,537 bodies has exactly one unhidden document with the same saved SHA. The 298,684 unassessed hashes have zero overlap with the full assessed set. The final targeted production-offline run passed 23 tests, including rejection of a hidden record and a different saved-body SHA. Doctor passed.
