---
id: ct-cbkz
status: in_progress
deps: [ct-55qo]
links: [ct-chc4, ct-m704, ct-f6hr, ct-0a35, ct-n3ik]
created: 2026-11-12T15:38:26Z
type: task
priority: 2
assignee: mikewolfd
external-ref: ss-mkxe
tags: [congress_api, body_text, spicy-docs, html, xml, post-wave-6]
---
# Finish the HTML/XML reparse and adopt qualified text

The composed spicy-docs reader and bounded pilots are qualified, and the full CPU-only HTML/XML reparse is running. Finish exact-key reconciliation and adopt the useful outputs through the existing selection/publication path. Earlier packaging and reader fixes are completed work; successful local staging does not yet establish catalog adoption or searchable publication.

## Design

Reuse the qualified composed spicy-docs wheel, merged GPO cleanup and maintained markup readers. ct-f6hr owns residual encoding and XML-policy compatibility; ct-55qo supplies the implemented selected-reading mechanism. Apply those accepted components to this real cohort, keeping historical readings and refusal evidence until exact retained-table reconciliation passes. Compaction does not establish selection.

The retained inventory names 310,964 unique HTML/XML bodies (310,047 completed baseline plus 917 recovery targets), with 11.92 GB of historical text. Reuse completed representative/largest-input pilots and continue the bounded, checkpointed run under its measured memory/storage limits. WARC remains outside this cohort pending separate payload and saved-body reachability qualification. No PDF OCR rerun; OCR remains paused.

## Current execution and remaining work

The frozen cohort contains 310,964 body/parser keys: 310,563 in the unchanged bulk lane, 400 completed in the separate verified-retained-copy lane and one House feed with an existing dedicated structured reading. The feed is not an xml_text completion and its zero prose bytes are not a failed extraction. The 400 remain bound to observed archive size/ETag and decoded identity; do not invent missing original capture metadata or restamp historical readings.

Run evidence and final collector: <main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/markup-reparse-20261114/. Preserve the running source/policy pins. ct-f6hr owns cause-specific residual encoding/XML failures; only affected inputs should be retried after a qualified fix. ct-fb7k/ct-en4n supply response-role evidence, ct-n3ik owns the practical exception queue, and ct-0a35 owns source-to-search acceptance.

At completion, bind authoritative reading/text catalogs and one accepted actual key per body/parser using ct-55qo. Carry prior usable text when a new attempt fails. Keep source errors, unknown roles, active refusals and unattempted work visible; completion alone must not promote an error page to substantive document text. Retain legitimate metadata/feed outputs according to their role. No PDF OCR or publisher refetch is part of this lane.

## Acceptance Criteria

1. The composed wheel passes real bill XML, mixed HTML with local <pre>, adjacent links/buttons and GPO verbatim controls. PDF text and declared PDF identity remain unchanged relative to the chosen baseline.
2. A measured CPU-only pilot and complete deduplicated HTML/XML manifest name supported, malformed, refused and unassessed bodies; no PDF enters that lane.
3. Reparse the qualified non-OCR cohort with measured capacity and compare text, refused and pending records in both directions. WARC requires a separate justified reachable cohort.
4. Account for all 310,964 keys across bulk results, the 400 retained-copy results and the distinct feed route. Check missing/extra/duplicate keys in both directions and preserve completed/error/unreadable/pending outcomes and their exact causes.
5. Publish only ct-55qo selections, reconcile the authoritative catalogs used by subsequent jobs and read back actual selected text hashes. A failed replacement preserves prior accepted text; retain earlier evidence and prove row uniqueness before any separately authorized destructive compaction.
6. A named reviewer directly reads a small raw -> actual intermediate -> adopted output sample spanning changed markup, ordinary controls and explicit refusals. Record remaining exceptions for ct-f6hr/ct-n3ik and hand the release/selection identities to ct-0a35.

## Notes

**2026-11-13T17:46:16Z**

2026-11-13 reconciliation: retain this ticket's CPU markup-normalization scope with upstream ss-mkxe. New compatibility work (legacy HTML encodings, empty XML internal subsets and max_events) is tracked separately in ct-f6hr. The earlier statement that PDF text was clean was limited to that sample and is superseded by source-confirmed GPO loss: PR #151 fixed cleanup, and ct-kfsd owns its historical reread/publication. For this markup-only change, preserve PDF output relative to the chosen current baseline; do not restore an obsolete PDF pin. Before compaction, retain replayable prior readings/refusals and verify one current selection per body/parser. Verify current shared-reader implementation and qualification before duplicating it.

**2026-11-13T18:48:44Z**

Rewritten from the independent ETL/greybeard/evolutionary audit. Prior notes and evidence remain below; old running-job and automatic reread assumptions are superseded. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T19:34:05Z**

Packaged the qualified markup slice from spicy-docs ce38a3db87438f247262fe9485fda5efaa95e3a6 as 0.85.0+markup.20261113 (wheel SHA-256 3b8fd70132cee1f3c64aaefa251fcec3fff9b22d1eb323d1242c06778dc6ae56). Reuses 847a32fd/e247fc9b while retaining GPO cleanup. Independent review caught and fixed generic-XML field concatenation/metadata loss, namespace alias/rebinding errors, hidden pre state and cross-event spaces. Only the Congressional native bill DTD or GPO USLM namespace qualify legislative metadata/inline rules; other XML and unknown/foreign fields retain boundaries. Raw evidence spans remain literal. Two builds are byte-identical and every wheel RECORD/source member verifies. Shared focused suite: 326 passed, 3 skipped, 2 deselected. CT focused suite: 73 passed (partial lane), watchdog peak 0.85 GiB RSS. Seven retained actual-CT native-only consumer cases cover six markup bodies and one native PDF: GPO pre controls and PDF text/offsets/cleanup unchanged; all four HTML bodies conserve non-whitespace text. HTML/XML and composed WARC receive explicit new declarations; PDF identity remains 4d04558965d9baf630033c94857169bfddad68988fce34041a4a35a0c6ddd2a8. Evidence: .cache/archive-release/ocr-recovery-20261113/repairs/ct-markup-readers-20261113/. This small local sample is not a corpus throughput estimate. Keep this ticket in progress for representative/largest-input pilot, source reachability and the 310,964-body reparse/qualified-selection acceptance. ct-f6hr compatibility remains separate. OCR paused; publisher refetch deferred.

**2026-11-13T19:48:19Z**

PR154 at 37ec7906 has an independent seven-original consumer review with no blocker. A separate CPU-only pilot parsed 34 retained markup bodies (1,179,343 source bytes) in 0.109 s, peak 0.05 GiB RSS. Known error-response controls remain role-classification work; parser completion does not qualify them. This small local set is not a corpus throughput estimate. Evidence: repairs/ct-markup-readers-20261113/local-cpu-pilot-*.json and independent-review.md. The largest event-limit case is an Atom feed, owned by ct-en4n; it should not establish legislative-prose throughput. OCR remains paused; no selection/publication.

**2026-11-13T21:30:08Z**

Added bounded retained-input qualification and corrected two directly observed legislative-reader gaps; the full non-OCR cohort is not yet reparsed or selected.

Shared source b064f96aa8d5b0d93dcd2cb10237b1063af64b94 includes the ct-f6hr compatibility/recovery work. Exact amendment-doc root plus Congressional amendment v2.8 DTD identity now selects the existing legislative normalizer: native meta-house editor/path/save-history content is removed, sponsor and section-6 quoted instruction remain inline, and other draft facts plus foreign metadata survive. No broad display=no or generic XML metadata rule was added. Indentation-only whitespace no longer inserts a space before the small bill's final period; explicit horizontal source spacing remains unchanged.

Evidence root: /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ocr-recovery-20261113/repairs/ct-markup-compatibility-20261113. data-review-final/manifest.json names six exact original -> ordered markup events -> normalized output chains for direct reviewer reading. ct-consumer-final/results.json records ten actual CT-consumer inputs. Six of the seven prior consumer controls preserve their text digests; the small-bill punctuation change is intentional. The native hearing-cover PDF's text hash remains aabe39b1592ff978dc7e01142929a7facf671d3308048386eb884d788b525e6b with zero OCR. Every worktree-only original needed by these packets now has a durable copy under data-review/originals.

pilot-final-plan.json and pilot-final-results.json evidence: 41 deduplicated locally retained HTML/XML inputs, 1,242,427 source bytes, largest 343,627 bytes; 40 parsed and the genuinely truncated XML stayed refused by the ordinary reader. Its separate attempted recovery remains partial under ct-f6hr. One-worker source read/hash/normalization time 0.0819 s; process-reported peak RSS 35,700,736 bytes. The 0.2s watchdog sampler can miss a short process peak, so its smaller RSS sample is not used as peak evidence. An initial default 15 GiB disk-floor refusal was retained; this small read-only pilot used an explicit 10 GiB floor against about 14 GiB free and wrote only bounded receipts. No OCR, source acquisition, selection or publication ran.

This remains a small local pilot, not a throughput forecast for 310,964 bodies or proof of the largest whole-cohort non-feed input. The complete 38.9 MB Atom source is routed and measured separately under ct-en4n. Broad retained-source availability, largest non-feed qualification, full-cohort CPU reread, refusal/pending reconciliation and ct-55qo production selection remain gates. Final composed wheel/declarations and the named review of its raw input/intermediate/output belong to the integration owner. Keep historical rows and refusals; refetch remains deferred and OCR paused.

**2026-11-13T21:33:15Z**

Independent direct data review completed by /root/ocr_ticket_completion: /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/ocr-recovery-20261113/repairs/ct-markup-compatibility-20261113/data-review-final/independent-content-review.md. The reviewer read original amendment/bill XML, ordered event records and final shared/actual CT text, confirming narrow metadata/inline/punctuation changes. This qualifies those bounded examples only; largest-input/full-cohort reread, final composed-package and selected-reading acceptance remain open.

**2026-11-13T22:24:49Z**

Extended the capacity and custody investigation using frozen inputs, without OCR, acquisition, reparse dispatch or selection. Evidence: `.cache/archive-release/ocr-recovery-20261113/repairs/ct-markup-compatibility-20261113/capacity-reachability/capacity-custody-report.md`.

All 310,964 frozen HTML/XML identities now join retained capture source sizes: 24,532,785,195 original bytes, zero missing/extra bodies or original-size conflicts. Baseline extracted text remains a separate 11,920,622,693 bytes. Captured stored-copy sizes cover 310,564 bodies and total 5,406,276,117 bytes; the other 400 have observed archive sizes but `copy_usable=false`, so their admission/identity gate remains explicit. Sizes and custody do not prove content completeness.

The proposed reparse cohort mixes roles. Capture families nominate 69,609 MODS/PREMIS XML bodies totaling 9,242,440,733 bytes, plus 9,568 meeting/witness XML records. These need dedicated-role disposition before a prose throughput estimate or dispatch. The complete House Atom source is separately routed under ct-en4n. A bounded 229-identity exact local/canonical-catalog check found seven local objects: three native documents, three MODS objects and one witness list. Other exact canonical-path absences do not establish missing alternate custody; the whole cohort has not received a local reachability census.

Three larger native originals, 12,746,049 bytes total, completed through actual CT 0e74c264d72240a4e19f7564d02b34dc15db4975 with shared 0.85.0+ctreaders.20261113.2 and unchanged reader hashes. Derive time was 1.0072 s, process high-water RSS 259,112,960 bytes, watchdog peak 0.26 GiB. The 8.326 MB amendment plus 3.134 MB hearing and 1.286 MB report extend the prior 343 KB maximum local pilot. They do not qualify the largest 13.788 MB XML or 6.617 MB HTML native candidates, cold archive retrieval, worker/Parquet costs or full-cohort throughput.

Named reviewer `/root/ocr_ticket_completion` directly read original → actual intermediate → actual CT output passages; see `independent-data-review.md` and `data-review-manifest.json`. Opening, interior, table and tail passages preserve substantive text. XML table output is plain text and omits empty-cell placeholders; source graphics remain absent. Unread portions, structured fidelity, role/custody reconciliation, full-cohort CPU reread/refusal reconciliation and ct-55qo production adoption remain gates. The durable report gives a bounded one-worker producer-batch plan and explains why the whole decoded corpus must not be staged locally. OCR pause and deferred refetch persist.

**2026-11-13T22:47:26Z**

Frozen role/custody proposal now preserves every one of the310,964 HTML/XML identities in disjoint primary states:400 custody-refused,1 dedicated House feed,80,276 metadata-family candidates,37,568 native-document candidates and192,719 unresolved roles. Eighty-six MODS/transcript label conflicts explicitly remain unresolved. Family/filename/path labels are nominations, not semantic qualification; all production_dispatch_authorized values are false. Exact proposal SHA03b418dca49d839c66ddc17e81dab8d1346614a320e1b15dc0382a0d0eb96e3e. Evidence is .cache/archive-release/ocr-recovery-20261113/repairs/ct-markup-compatibility-20261113/role-partition/{README.md,summary.json,direct-data-review.md,producer-seam-review.md,artifact-manifest.json}. The metadata-only build measured2.9seconds/0.942GiB; it did not re-read corpus bodies.

The existing stage(planned,items) interface supports a bounded exact-key native producer probe. Filtering captures alone does not restrict plan(): candidates originate from sniff_facts and settled-reading state. Preserve original planned storage fields, anti-join the exact400 refused keys, and account for held/missing keys. A recovery-observed size must not fill a missing captured pin; an external copy_usable=false field alone is not a stage guard. The demonstrated nomination accounts for3 already reviewed local sources and310,961 held identities with no overlap, omissions or wrong-role/refused nominees. No producer was dispatched. An optional exact execution-key scope in existing plan/run/CLI is the minimal maintained CLI gap if needed; accepted-reading selection is not that scope. Current custody, larger producer-batch capacity, unresolved roles, content qualification and selected adoption remain open. OCR remains paused and publisher refetch deferred.

**2026-11-13T23:17:11Z**

The actual maintained CT producer-stage control now passes for three previously reviewed retained identities: amendment abfd84a3bd8c, hearing 43bcbb089f9c and report eaa8b01fa8e3. Core code 7f25abf9 (runtime docs-only descendant 7f33f789) used the frozen local interpreter, shared wheel 0.85.0+ctreaders.20261113.2, one real parser worker and the pinned native engine. The final Parquets contain exactly three readings and three body-text rows, with all 6,838,782 text bytes identical to the earlier reviewed outputs. There were no pending/missing worker keys, missing pins, unreadable outcomes or OCR pages. The supervised process took 3.1 seconds at 0.343 GiB peak RSS; this is a bounded control, not a full-cohort throughput estimate.

Named reviewer /root/ocr_ticket_completion/markup_compatibility directly read the actual worker requests/responses, parsed intermediate records and staged final row contents. The earlier independent source/event/text review is reused only for byte-identical content. Evidence: repairs/ct-markup-compatibility-20261113/role-partition/producer-probe/{README.md,direct-data-review.md,artifact-manifest.json} under the durable OCR recovery root; manifest SHA bcc1c1159fb2024d7d76d0755904700d6ec7c23bdef6598ee79a45775a140d89.

Production gates remain explicit: current plan/selected-reading eligibility, captured-gzip replay or deliberate retained-raw custody adoption for the two HTML copies, role/custody qualification and broader stratified capacity. The 310,964-key manifest still accounts for every key; 400 capture-storage refusals remain held. No production selection or catalog append occurred. OCR remains paused and publisher refetch deferred. The mechanism fixes merged in PR156; this bounded evidence does not close the corpus-reparse ticket.

**2026-11-14T06:07:10Z**

All three previously reviewed larger markup inputs are now nominated by the maintained current body_text.plan() at CT d1b8a0b, using exact retained capture records, native sniff lookups and frozen unreadable/current-version evidence. Amendment abfd84… uses xml_text 5a0768…798c and preserves its original gzip key and 1,513,112 stored / 8,325,960 decoded byte pins. Hearing 43bcbb… and report eaa8b… use html_text f1cefe44…94a3 and preserve their original gzip keys plus 1,251,899 / 3,134,001 and 365,849 / 1,286,088 stored/decoded pins. All report conflict=false. No source object listing was supplied, so nomination does not prove reachability.

The HTML lookup preserved all 60 actual capture observations and exact receipt_key/receipt_line/capture_index identities; no duplicates collapsed or missing fields fabricated. Root read the actual planned rows, native sniff rows and representative original capture records for all three bodies. Their direct source/intermediary/text reviews remain the earlier unchanged producer-probe evidence. These probes establish current-code nomination under the explicitly frozen source snapshots, without a body worker or source fetch. The final HTML metadata job peaked at 0.257 GiB RSS and ran 2.2 seconds. It projected 12 columns across ten row groups (101,019,809 compressed column bytes declared by the footer); this is metadata planning, not source extraction throughput.

Evidence: coordination/markup-current-plan-eligibility-20261114/ and coordination/markup-current-plan-html-eligibility-20261114/ under the main OCR recovery root. The earlier missing-metadata observation and two bounded harness refusals remain preserved. Captured-gzip replay or explicit retained-raw custody adoption for the two HTML copies, broader role/custody qualification, measured cohort reparse and accepted reading selection remain open. OCR stays paused and publisher refetch deferred.

**2026-11-14T12:31:10Z**

Updated the lead and remaining acceptance to the active run: 310,563 bulk keys plus 400 completed retained-copy keys and one dedicated feed route, all reconciled against the frozen 310,964-key cohort. Qualified packaging/pilots are completed work. Remaining work is final outcome accounting, cause-specific exception handoff, authoritative catalog/selection adoption and readback; ct-0a35 owns search verification. No running process, policy pin or source output changed during ticket editing.
