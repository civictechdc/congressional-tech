---
id: ct-en4n
status: in_progress
deps: [ct-fb7k, ct-qmh5]
links: [ct-chc4, ct-z4w5, ct-f6hr, ct-0a35, ct-n3ik, ct-m704, ct-qmh5]
created: 2026-11-13T17:46:16Z
type: task
priority: 1
assignee: mikewolfd
tags: [body_text, quality, captures, html, xml]
---
# Reconcile source roles, capture history and newly excluded error responses

## Implementation update — 17 November 2026

The successor inventory preserves all prior records, adds the four Natural Resources error bodies (five document targets), and links the two archive wrappers without duplicate recovery requests. It contains 455 known-source records and 454 open exact-original obligations. Existing capture/detail history resolves targets for 267 records; 188 historical error hashes still lack a requested URL. Three directly reviewed selected alternatives provide scoped search coverage while preserving revision limits.

November 17 manifest: `<main checkout>/.cache/archive-release/ticket-fixes-20261117/inventory/post-capture-append/manifest.json`, SHA `33af1264b175251d5544e1d44f44c2df861633e4816b7a6545217dcf5af444e9`. Every predecessor field remains preserved; two records gain native receipt-integration facts. The final text handoff pins this generation.

Remaining: resolve the named historical URL/role gaps where evidence becomes available, preserve per-target eligibility and distinguish unsupported/unassociated sources from failed document extraction. Actual requests, source replacement and native recovery remain ct-z4w5.

## Audit baseline — 17 November 2026

Shared detection and explicit selected-text exclusions are implemented. v12 records 416 exclusions (390 newly added) and retained verification reports no excluded body leaked into its export. Valid feeds, statute viewers, resolved challenges and useful metadata remain distinct from invalid publisher sources. The 400 example bodies are template examples with explicit review limits, not 400 individually reviewed documents or 400 fetch requests.

The durable invalid-source inventory still records 451 sources / 450 open recovery records. Four newly excluded Natural Resources error bodies are missing: `0df2d0da7fa6…` (Westerman amendment), `3192a4c231de…` (Whipps testimony), `34c58155d0ed…` (Nau résumé), `5d1f51c93c7f…` (Bakst testimony). v12 selection/review pins hold the full digests. Two excluded archive bodies, `6eea94ddc3e7…` and `b6aaf0d8fdba…`, wrap already-known error payloads and need association with existing records, not duplicate requests.

## Scope and ownership

Own source-role qualification, capture-history reconciliation and the canonical invalid-source inventory, including these four additions and two wrapper links. ct-z4w5 owns eligible acquisition attempts and their outcomes. ct-m704 consumes the pinned inventory with selected text/quality state; ct-0a35 checks the actual search consumer. Reuse SpicyDocs observations and qualified House detector evidence rather than build another detector. Completed extraction remains historical evidence even when prose selection excludes its source.

## Acceptance Criteria

1. Add the four exact error-body records with URLs, evidence and source role; link the two archive wrappers to known payload failures. Reconcile existing captures/recoveries before choosing retry status. Do not blindly increase unresolved counts, duplicate requests or classify valid wrappers/feeds as invalid.
2. Finish requested-URL/history review for the existing 394 error-response records and remaining landing-source obligations, reusing resolved viewer/PDF associations. Distinguish recordings/playlists, documents, metadata, valid empties and unresolved source roles; a successful transfer alone does not resolve source quality.
3. Preserve source/version identity, refusal history, review limits and explicit unresolved reasons. Check false-positive/missed-error controls using legitimate documents quoting error phrases, short/empty documents, feeds/manifests and accepted alternative coverage.
4. Apply the reviewed roles through existing exact-body selection/exclusion policy and verify intended-release exposure. Deliver a deduplicated inventory and per-source capture eligibility to ct-z4w5 and ct-m704. Classification alone does not start a fetch; already qualified targets do not wait for unrelated history reviews.

## Current disposition — 20 November 2026, after independent review

Inventory classification, capture-history resolution, the consumer handoff and the 94 legitimate-source controls are complete. The canonical manifest at `docs/plans/ocr-source-recovery-inventory.json` pins all 455 per-source decisions for ct-z4w5 and ct-m704. It preserves the 26 closed and 429 open exact-original recovery decisions. All 188 reconstructed records now give their listing address, receipt basis, role, refetch decision and document-fetch eligibility. None identifies a missing document. The two State archive wrappers share their payloads' recovery records.

The native query covered all 382 zero-page addresses. For CHRG-118shrg53785 the ledger links the October 5 capped transfer, the October 6 successful capture and Explorer PDF `1e68f460bf1cd70f`. All 57 public valid-empty readings retain their visible associations and empty text. The 15 published quotation controls retain their reviewed text digests.

Criterion 4 remains open on Explorer release `0e7084cde775`. All 398 inventory error bodies and both linked State archive wrappers have explicit text exclusions. Explorer lists 26 affected records by default and offers unqualified downloads on 31 detail pages, including five hidden Natural Resources records. The reconciler writes each link key, saved hash and both exposure results before returning exit 1. Release defect ct-qmh5 owns suppression and verification on a successor release and blocks closure of this ticket. The counts and closure recorded in the earlier notes below describe the first pass.

## Audit evidence

17 November manual audit: `<main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md`; PDF sample: the sibling `pdf-manual-review.md`. New v12 files: `<main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/body-text-ssot-20261116/`. These evidence files retain the exact inputs, identities and sampled/unread scope. Historical notes below are dated evidence; the current scope and criteria above supersede their unfinished-work summaries.

## Notes

**2026-11-13T17:46:16Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.

**2026-11-13T17:46:56Z**

Retained-input triage also owns classification of the 345 select-at-least-one-distinct-page errors; do not turn a zero-page parser view into valid-empty text. Raw specimen 04a74549a18e2de5103e79c99714af3ad9b9ccea7cc0d6c62ddc419af5abbe30 is 1,553 bytes while its PDF linearization header declares 43,652 bytes / 4 pages; pdfinfo reports a missing/null top-level pages object. Distinguish damaged/truncated sources from legitimate containers and inspect the remaining members before assigning one cause to the whole bucket. Evidence: .cache/archive-release/ocr-recovery-20261113/raw-review/inspection.json.

**2026-11-13T18:48:44Z**

The 345 zero-page failures require classification; they are not all proven corrupt sources. Ordinary WARC exclusion is intentional (ct-0hay): no envelope was selected as saved_body. Qualify source role and saved-body reachability before restoring any WARC processing/publication. Broad phrase matches are review candidates, not error verdicts. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T19:48:19Z**

Add the complete House BillsThisWeek-RSS.xml Atom feed as a positive feed/container control. Exact body c90e782a00651261a9ac21ae8d30df88757b3b66ae99a5ff794f0dc8ca65336e has 2,226 entries, publication/update times, weekly page links and embedded bill-document links. Current source inspection found no dedicated consumer in CT, spicy-docs or spicy-regs. CT generic XML can read hrefs; news_lake has an offline feedparser-based Atom adapter. Spicy-docs currently supports RSS 2.0 through its shared feed helper; Atom/source-specific support is an explicit extension. Recommend a shared spicy-docs reader and structured schedule/discovery consumers in CT or spicy-regs, after existing-link/freshness comparison. Scheduled consideration is distinct from votes or completed actions. Keep raw feed and historical readings. Findings and measurements: repairs/ct-f6hr-event-limit-20261113/. No recurring acquisition or publisher refetch was started.

**2026-11-13T19:50:10Z**

Additional current-code limit: ordinary lake/readings.py uses PAGE_PARSE_MAX_BYTES = 24 << 20 and explicitly names c90e782a as an over-bound XML case. Generic href-reading capability does not establish that this 38.9 MB feed has contributed links. Dedicated entry-level routing and a retained-table comparison are required before claiming active feed use.

**2026-11-13T19:51:47Z**

Retained feed shape: 2,226 unique Atom entry IDs point to 198 distinct weekly-page links, with up to 40 entries for one link. Preserve entry identity/update/content versions; URL-only deduplication would discard observations. These are retained-snapshot counts, not complete historical coverage or current freshness. The latest retained entry is dated 2026-09-15. Evidence: repairs/ct-f6hr-event-limit-20261113/feed-shape.json.

**2026-11-13T21:49:42Z**

Implemented the shared spicy-docs House floor Atom reader and explicit offline CT/Regs consumers. Final retained source replay (SHA c90e782a00651261a9ac21ae8d30df88757b3b66ae99a5ff794f0dc8ca65336e) keeps2,226 entries and65,511 link occurrences; actual CT model resolves all65,511. Entry revisions remain distinct. Original malformed '/https://' href remains recorded, with a separate repair only when the exact target is explicitly stated elsewhere in the same feed. Direct raw/intermediate/final reviews cover entries0/1/1047/1048/2225; independent review caught both planted wrong-target and wrong-bill-version controls. Measurements: CT14s/0.67GiB RSS; Regs8s/0.59GiB. Durable evidence: repairs/house-floor-feed-20261113/{ct-replay-final,regs-final,independent-data-review-ocr-completion.md}. This is a bounded local replay, not freshness, complete historical coverage or public adoption. Daily feed acquisition is not enabled.

The bounded retained response-role API/CLI now preserves separate error, wait, empty and unassessed outcomes. Independent review caught heading-evidence amplification and mixed-content/namespaced XML false positives; fixes retain explicit limits and unassessed source evidence. All11 retained real observations are unchanged, and five independent mechanism probes were re-read after repair. See repairs/response-roles-offline-20261113/. Broader real document/error-quote, portfolio/empty/whole-hearing controls,345 zero-page classifications and complete unresolved-source history remain open. OCR stays paused; publisher refetch stays deferred. The per-ticket named-review matrix is coordination/ocr-offline-ticket-matrix-20261113.md.

**2026-11-13T22:24:49Z**

Bounded native repair review of exact retained bodies 04a74549a18e2de5103e79c99714af3ad9b9ccea7cc0d6c62ddc419af5abbe30 and ed0298387f8c87d6c6bc70241e4510e490fe8e2b4668e2595cbc7f0220d156b8 completed without OCR/refetch. Whole-file hashes match full decompression of retained stored objects and capture metadata; these are not inspection previews. The first has only 1,553 bytes versus a declared 43,652-byte/four-page PDF and ends inside its first page dictionary. PyMuPDF already attempts repair and exposes zero pages; saving refuses and qpdf reconstruction fails. Preserve explicit incomplete-source status, never valid-empty text.

The one-MiB Walling retained import contains a complete earlier nine-page testimony revision followed by a truncated fourteen-page update. Literal source bytes establish both revisions (including CR-separated updated dictionaries), and native inspection recovers five testimony pages hidden by the broken updated tree. Exact original prefix [0:336711], SHA30bedf44e3393fd77166126963beb8c2c52682f15224af4c1ffe5e024e4229b9, opens as the earlier nine-page revision without repair or warnings. It excludes later resume/disclosure additions and is an inspection-only earlier revision, not a complete replacement. A generic qpdf rewrite drops those five testimony pages and blanks a partially readable form, yet subsequent qpdf --check succeeds. Direct author and independent image reviews reject this rewrite; no complete reading, checkpoint reuse or selection follows from structural validity. The original retained_import complete=true flag does not prove publisher-transfer completeness or locate the cause of truncation.

Evidence and exact input/intermediate/output identities: <main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/native-pdf-repair-20261113/{data-review.md,custody-verification.json,literal-revisions.json,earlier-revision-report.json,artifact-hashes.json}. Remaining gate: reconcile complete retained alternatives and intended revision/attachment scope; preserve missing updated image bytes for deferred source recovery. No conclusion is extended to all 345 zero-page failures. OCR remains paused and publisher refetch deferred.

**2026-11-13T22:48:50Z**

Three additional geometry-cohort originals now have exact captured-archive custody and direct page reviews. Two (d128b929c3b1… and924eb1c45958…) end inside declared streams, lack the final PDF trailer/EOF, and need native repair that substitutes missing font data; their rendered and native text is garbled or incomplete. Verified archive identity does not identify the cause of truncation or prove publisher-transfer completeness. The third (15611eacbdfb…) renders coherently but has an invisible native span and omitted graphic-header text. All remain unqualified; no recognition, publisher fetch or selection occurred. Exact identities, full native/output chains and review limits are in repairs/geometry-reconciliation-20261113/archive-native-sample/{data-review.md,classification-delta.jsonl,artifact-hashes.json} under the main recovery evidence root. ct-yy07 owns the numerical geometry reconciliation; this adds source-quality evidence without claiming all zero-page or capture-history cases resolved.

**2026-11-14T05:52:05Z**

Shared feed wiring is now merged across all three repositories: CT PR156, spicy-docs PR27 (f9584d8bbc6d14c7707fbf53d3487e024b0455b8) and spicy-regs PR194 (04be0854af544f2e1af0ae3619d2b8b325c3ed17). Regs passed all four test partitions, lint/dictionary/join checks and live integration at f859398e0ead8d27c330e9e6c22e769427b618dc. Independent retained raw/intermediary/final reviews and exact output comparisons preserve 1 feed / 2,226 entries / 65,511 link occurrences, including per-capture entry/link identity. House feed tables remain explicit local-partial candidates outside hosted query registration; no daily acquisition, current-freshness claim or feed publication follows from this merge.

The reviewed response-role example S301 now links to its exact historical html_text intermediate while its response_roles output remains private and absent from the merged lake index. Independent linkage review: repairs/corpus-assessment-20261113/review-links-20261114/reviewer-shared-reader/independent-review.md. The broader source-role controls, zero-page cause classification and unresolved capture-history acceptance remain open. Publisher refetch stays deferred.

**2026-11-14T11:58:30Z**

The user requested that the 400 previously held HTML/XML bodies serve as inventory examples. Added exact-key annotations under repairs/corpus-assessment-20261113/response-examples-20261114/{examples.jsonl,examples.csv,summary.json,input-manifest.json,README.md}. All 400 already belong to the frozen 18,777-body inventory; no corpus bodies were added or original rows overwritten. Labels preserve 197 NoSuchKey, 173 meeting-not-found and 14 file-not-found template examples. Of the 16 unmatched records, earlier direct reviews supply one ordinary structured-metadata control (M003) and one meeting-landing control (M005); 14 remain unassessed. Reused five original source-role reviews without claiming all template siblings were individually source-reviewed. Every example links its retained-copy descriptor, actual current reading/version and text hash, historical output and frozen selection scope. All 400 separately reparsed successfully in 14 seconds at 0.509 GiB peak; extraction completion remains distinct from source quality. Use these as development/regression data grouped by template family, not a held-out accuracy benchmark. Assembly took 0.34 seconds with no new source retrieval or model calls. OCR remains paused, publisher refetch deferred, selection unchanged. Broader ticket acceptance stays open.

**2026-11-14T12:31:10Z**

Five-step FTS follow-through is now ticketed. New child ct-fb7k owns the missing House meeting/file response detector; this parent retains broader role and capture-history qualification. Linked ct-n3ik for cheap triage and ct-0a35 for actual source-to-search acceptance. Existing raw/review history remains intact; OCR stays paused and refetch deferred.

**2026-11-14T14:33:16Z**

Current release metadata, independently reviewed in repairs/corpus-assessment-20261113/publication-state-20261114/independent-review/review.md, confirms all400 examples have zero document associations. Two other previously source-reviewed error bodies do each have one unhidden document: T001 359e3b8b6b844d69fa29bd39c40f970af1586af0500dcda1f98a302721eafe1d and T002 82867326cf8750a2cb2de9b3cd5f25b447269fcd870440390f7512f8e08d1d5e. The release is 4b9a7bd126cc17e39dfbe7f8fabafbdb7251dcd32576277f308916f469c9bab1, published 2026-11-14T05:25:35Z. These are document associations, not accepted reading or search claims.

Implementation gap: body_text_selection currently records actual keys without a source-role exclusion decision, while body_text_export filters saved bodies only. Preserve completed error-page extraction evidence and add explicit reviewed search eligibility; do not encode exclusion by fabricating failed reading status. Focused House detector PR165 is independently approved after real quotation/duplicate-attribute controls; broader history, zero-page classification and actual search eligibility remain here. OCR paused and refetch deferred.

**2026-11-14T15:08:53Z**

Implemented explicit reviewed publication exclusions in selection manifest v2 at fcab04f08b8891f08a1f1beba12a2fd7bfbd7701. Only error_response/wait_response/feed are eligible roles; reasons and qualification report are pinned. Actual selected-key validation still runs, original reading status and total saved-body coverage remain visible, and planner pending work is unchanged. Independent native review approved; 26 focused tests passed (partial lane). /root directly read T001/T002 originals, actual shared parse events, CT cleanup and full output; native private export removes both real error responses and preserves ordinary M005 text byte-for-byte. Exact current public associations are used separately from a synthetic three-row control. Evidence: repairs/corpus-assessment-20261113/source-eligibility-20261114/. No hosted index or production selection changed. House error detection PR165 is merged; broader source-role adoption remains open.

**2026-11-14T15:57:37Z**

PR #167 merged at 7cbb9f3b51bef7621c8516da31c01e8965d727d4 after CI and independent exact-input review. Selection manifest v2 permits hash-qualified exact-body error_response/wait_response/feed exclusions while retaining accepted-key validation, completed status and saved-body coverage. Real export omits two reviewed State error pages and preserves ordinary meeting text byte-for-byte. Broader source-role assignment and public adoption remain. Source refetch recovered Mast/Mahoney corrected addresses; Cornwell still empty; see ct-z4w5.

**2026-11-15T07:05:12Z**

Direct source-role review: 14 Congress.gov statute PDF viewers and one distinct challenge. The authoritative frozen 4,169,182-row capture input contains all 13 distinct linked PDFs, each with its own exposed association and selected completed baseline reading. Seven viewer bodies are exposed; seven others and the challenge are unassociated. Only 06984 PDF source fidelity was directly checked; the other 12 are metadata-bound. No PDF refetch needed. Evidence: repairs/corpus-assessment-20261113/triage-current-20261114/ct-g4yz-fallback-release-binding-20261115/. Existing role wrapper is reused by 9801e9af (19 focused tests, doctor passed); actual exclusions are pending. Historical readings/planner completion remain intact.

**2026-11-15T07:24:33Z**

Accepted-set-v6 is independently qualified: selection SHA 95fad5e005670ce150ce4d09321ff9e321f11fdfa9abd641970c8e63b037c72f; independent result SHA dbd3e66bcd9d8e66142f318e501108db20976557c02e13c254dc349dd17ef539. Evidence: repairs/accepted-text-adoption-20261114/accepted-set-v6-independent-review/. The 210 actual appended pairs are selected; fifteen exact source roles exclude seven exposed viewers while preserving thirteen linked PDFs and the alternate resolution. Main heads: body_text 4020361685539847953; readings 6816097245686786721. PR174 merged at 8965dc00e409dbdbdc6ee4e00af7418a4fc87e59 with both CI workflows successful. Wrapper helper code merge and final handoff remain separate.

**2026-11-15T15:42:25Z**

Consolidated known invalid source records into the current source-recovery inventory without overwriting frozen body triage, Q5, captures or readings. The new worklist binds old diagnoses and latest actual fetch receipts, preserves the covered short bill, keeps all 49 zero-page cases unresolved, and carries 394 error-response bodies forward for URL/history review. Two GovInfo candidates remain alternate_revision_review_pending until source identity/revision review establishes coverage. A null needs_refetch on an error response means unresolved history, never resolved/forgotten; feeds and wrappers are excluded from this invalid-file list. The old inventory directory now has current-source-recovery.json pointing to the new generation. This is a known-failure inventory, not a corpus-wide audit, and reuses the 384 examples' representative-template review limits. Source/input/output metadata checks pass; no new raw-source semantic review or network/OCR action.

**2026-11-17T09:17:02Z**

Manual audit credits v12 source exclusions and shared detection. Own the missing inventory entries for four Natural Resources error bodies and links for two archive wrappers of existing errors; do not create duplicate recovery requests or include valid feeds/viewers. Capture-history and role qualification still remain. ct-z4w5 consumes per-source eligibility, so unrelated unresolved history must not block already-qualified recovery targets. Audit evidence: <main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md.

**2026-11-17T10:28:52Z**

Implemented selected 80/20 scope via subagents. The current implementation update above records completed work, exact evidence and remaining acceptance. Full evidence is under <main checkout>/.cache/archive-release/ticket-fixes-20261117/. Historical notes are preserved.

**2026-11-20T23:29:16Z**

November 20 source-role reconciliation completed against Explorer release 0e7084cde775d0064646c56b2200a14e1f13d8b512f1a61a6fe815d597faf4d3 and v13 body text 7aea7925da324273d16c04e7dd7d53b2a7d3a0ade895f9343063015458d88688 (selection bbeb4e1c94e195ac8ec5085578331543b2b2f709e77d2c83e523474e07bbe10b). The ledger preserves all 455 source identities from November 17 and the per-target recovery decisions from ct-z4w5 on November 20. It binds every case to the pinned captures and selected readings, Explorer source and address lookups, URL state, saved and recovery rows, and v13 membership. No requests were dispatched.

All 188 historical URL gaps have original receipt provenance. For 187 saved House meeting HTML fallbacks, the receipt pointer's meeting ID matches the exact body's form action. The remaining SHA is a verified retained Senate Appropriations listing security response. The ledger distinguishes reconstructed source addresses from absent HTTP request observations. The 398 error responses include 197 missing recording playlists, 173 missing House meetings, 14 House file errors, four Natural Resources error bodies at five document targets, one Senate listing security response and nine other reviewed HTML error responses. The remaining inventory contains 56 damaged PDFs and one zero-byte response to an expected PDF. Two State Department archive wrappers share their failed payloads' receipts.

The earlier 345 zero-page failures form a separate population. Fifty overlap the 455. The evidence establishes 154 PDFs shorter than their declared length, 140 failed PDF transfers, 44 capped PDF transfers, six unterminated PDF streams and one zero-filled PDF tail. All 345 lack v13 text. All 455 inventory originals also lack v13 text. Of the 27 selected public PDF error readings, 21 match historical zero-page failures, one is the damaged Walling source, and five lie outside the inventory. All eight reviewed landing cases now have a public target PDF with v13 text. The 94 positive controls cover the Atom feed, ordinary HTML/XML, statute viewers, a verified four-member ZIP, valid empty outputs and ordinary documents mentioning error phrases. Fourteen unassessed template siblings retain their review limits.

The broader public-copy exclusion check failed. Explorer still has 28 invalid-source SHAs on 29 saved document rows. Twenty-two damaged PDFs and two State Department error pages have unhidden saved-copy links. Four Natural Resources HTML errors occupy five hidden recovery rows. All 398 reviewed error hashes have an explicit text-selection exclusion. All 197 playlist errors have HTTP failure receipts and zero saved-body associations. URL state contains one body_not_qualified entry, outside this inventory. A failed reading or an absent export row does not remove the Explorer download. The current operational inventory reports 26 closed and 429 open exact-original obligations. Qualification, revision limits and recovery eligibility remain per target.

The full ledger and report are /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/long-tail-20261120/pdf-source/ct-en4n-reconciliation.json and ct-en4n-summary.md in the same directory. The ledger's public_copy_control names every counterexample by Explorer link key and saved SHA. The good-fetch HTTP status rule is in model/sql/good-fetches.sql. Ticket ct-fb29 covers schema descriptions. No production or selection policy changed.

**2026-11-20T23:33:09Z**

Closed the requested inventory, provenance, controls and release-exposure reconciliation. The public-copy exclusion remains failed on the pinned release. The verifier writes the complete ledger and exits 1 with the 24 counterexamples. Linked open release defect ct-qmh5 owns their correction and verification on a successor release. Qualification, acquisition and publishing were outside this read-only investigation.
