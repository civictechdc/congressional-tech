---
id: ct-z4w5
status: in_progress
deps: [ct-en4n]
links: [ct-en4n, ct-saqg, ct-4jms, ct-6v77, ct-5cdu]
created: 2026-11-13T17:46:16Z
type: task
priority: 3
assignee: mikewolfd
tags: [body_text, captures, refetch]
---
# Refetch reviewed damaged or missing publisher sources and preserve new evidence

The current invalid-source inventory keeps 450 recovery records open: 56 PDF/empty-response cases need source recovery, while 394 error-response records need URL/history reconciliation before requests. All 47 actual refetches from the 49 damaged zero-page PDFs returned the same invalid bytes; two GovInfo alternatives still need document/revision comparison. HTTP 200 or complete=True does not resolve those failures. The short bill has a verified selected replacement and stays covered. Mahoney is selected in accepted-set-v11; Mast still needs receipt ingestion and a supported document association. Use docs/plans/ocr-source-recovery-inventory.json for the durable per-source worklist and evidence.

## Design

The user has resumed this work. Continue through measured, explicit target batches. Depend on the response-role/capture-history qualification and reuse acquisition/recovery components. Preserve every original response, header, partial body, hash and receipt. A new complete or alternate publisher response receives its own capture/body identity. Preserve accepted official-hearing and URL-variant fallbacks; encrypted, unavailable or irreparable inputs keep named unresolved outcomes.

## Acceptance Criteria

1. The prerequisite supplies a deduplicated, evidence-backed list excluding already selected complete captures and accepted recoveries. Record the 14 November authorization and current capture eligibility before publisher requests.
2. For each resumed request, retain transfer completion evidence, source identity, old/new hashes and receipts; verify actual PDF/markup readability and source completeness before selection.
3. Reconcile every requested item to a selected qualified copy, accepted scoped fallback or explicit unresolved reason. Preserve logical document associations and prior evidence.
4. Publish qualified results through existing gates and independently read back them without treating HTTP success or OCR completion as proof of completeness.


## Notes

**2026-11-13T17:46:16Z**

Evidence: <main checkout>/.cache/archive-release/ocr-recovery-20261113/coordination/text-quality-audit-20261113/repair-plan.md; source review under .cache/archive-release/investigations/text-quantity-review-20261113/research-followups/. These durable local artifacts contain source identities, review limits and retained failures. See docs/plans/ocr-text-quality-remaining-20261113.md for plan ownership and sequencing.

**2026-11-13T17:46:56Z**

Additional confirmed damaged-source candidates: 04a74549a18e2de5103e79c99714af3ad9b9ccea7cc0d6c62ddc419af5abbe30 (1,553 retained bytes versus declared 43,652; page tree missing) and 8ec3cad9a2221fc57fb59b03aa7318c916bead34adabb971ea114795c518eedb (32,056 bytes, no readable trailer/xref). Keep every candidate subject to ct-en4n retained-history reconciliation before a later refetch. A shared error string does not prove all 345 page-selection failures have the same cause.

**2026-11-13T18:48:44Z**

Deferral remains in force. Neither inventory creation, source classification nor a corrected parser authorizes publisher refetching. OCR is also paused independently. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T21:31:52Z**

Deferral preserved. Added a retained-history proposal under repairs/response-roles-offline-20261113/deferred-source-proposal.json:2 unresolved landing targets (P001 exact target unattempted,P005 exact target HTTP410),6 already-selected targets explicitly excluded; additional prefix/zero-payload/damaged-PDF/zero-page cases remain unreconciled rather than queued. Reviewer /root/ocr_ticket_completion directly read raw P001/P005/P002 landing links,stored capture/selection trace objects and actual proposal; paths/hashes and scope are in data-review.md and artifact-hashes.json. This reconciles the existing8-target snapshot,not all damaged sources or current publisher state. No acquisition requests ran. The user must lift refetch deferral before requests; source completeness,selection and publication criteria remain open.

**2026-11-14T15:08:53Z**

User authorization on 14 November lifts the old deferral. First bounded reviewed batch used maintained capture policy/Fetcher/DirectAdapter/BodyStore/ReceiptWriter with current URL history and capture scope. P001 Mahoney and P005 Mast targets both returned HTTP410, each a complete tiny HTML response containing only a meta-refresh to its /404 page. /root read both complete raw bodies and receipts. They remain unresolved; new bodies, headers, source hashes and create-only receipts are retained. Three reviewed State Department URLs were not requested because they fall outside the published capture scope. No original or accepted selection changed. Evidence: repairs/source-refetch-20261114/{authorization.json,current-target-history.json,queue.json,results.json,finished.json,README.md}; final batch 1.4 seconds / 0.106 GiB RSS. Remaining damaged/prefix/zero-payload candidates still need exact history qualification; do not repeatedly fetch already satisfied targets.

**2026-11-14T15:57:37Z**

Corrected bounded refetch completed: short bill e5de955c… (43,652 bytes, four pages), Mast amendment 4ee6fd1a… (25,289 bytes, one page) and Mahoney disclosure f500112e… (224,265 bytes, three pages) are readable useful FTS sources. /root/ocr_pilot_manual_review used GPT-6.1-Terra medium and genuinely read all eight raw pages, actual producer intermediates and final text. Report SHA fd04f6df13bd14bc29f6d6fe13eb1ef98e9961de5830b252f05f781af581af12. Cornwell remained HTTP 200/zero bytes/failed. Exact receipts, bodies, source roles and prior failures are under repairs/source-refetch-20261114/scheduler-followup/refetch-four/. Batch: 5.5 seconds / 0.108 GiB RSS; no public adoption. The maintained query repair changes &download=1 to ?download=1; original two HTTP 410 responses stay retained. Post-refetch accounting includes actual attempts plus reviewed seed context, superseding an earlier context-incomplete diagnostic. Planner defects now have separate tickets ct-saqg (absent journal) and ct-5cdu (whole-history build).

**2026-11-14T16:48:30Z**

Root directly compared retained CHRG-116hhrg35338 HTML original, actual worker record and final text at opening, middle, appendix transition and tail. Existing unhidden document df2a0a3aa21bb697 binds body df2a0a3aa21bb6976aa1145a70484afb48064838a01875e3a4a4add33d1f756d; current HTML output 114,116 bytes matches prior hash 68ac36b47779b6b11996cd9c6be8eeb2745b26ad979e82af5b705439e7854e24. Raw prepared-statements section explicitly says GRAPHICS NOT AVAILABLE IN TIFF FORMAT. Reuse useful HTML; retain PDF/appendix gap. No publisher request for that review. Report SHA bc64fb1af58e7f363578082ebad31a898b52941d8dbb7a5ee0a3920b606dba14 at source-refetch-20261114/scheduler-followup/retained-package-html/manual-review.md. Additional exact damaged PDFs a558032c/e51dfab3 are source-recovery candidates from the 17-page Terra review.

**2026-11-15T12:11:19Z**

Read-only current capture resolution found archive_r1b.captures_df55_20261113 snapshot 4529945025615165014 unchanged from the published nightly pin. It contains the bill/Mahoney bodies, Mast parent HTML 00a251 and historical 410 70ae; it contains neither Mast PDF 4ee6fd1a nor any of the six checked 14 November refetch receipt keys. Preserve those receipts and failures during ingestion. Terra compared actual selected and reviewed outputs: bill baseline retains the provisions with cleaner page boundaries; Mahoney 4d restores Self/Organization/CV lines but leaves radio state ambiguous. Its exact reviewed pair is reserialized to native schemas with all stored values unchanged. Mast parent HTML explicitly links the malformed &download=1 URL; corrected ?download=1 redirects to the reviewed PDF, but that trail is not a logical release-document association. Evidence: refetch-three-adoption-planning-20261115/{plan.md,result.json,capture-exact-result.json,mahoney-native-staging/receipt.json}.

**2026-11-15T12:27:39Z**

Established-viewer probe: maintained macOS PDFKit returned no document for both a558032c and e51dfab3 originals; installed Adobe Acrobat 25.001.20432 separately reported both damaged and unrepairable. Originals and copies remain byte-identical. No export or image rendering could follow those refusals. Earlier white PyMuPDF renderings remain unknown source content, not confirmed blank pages, and the e51 Goose Creek letter remains partly obscured. These two ZIP-code collections are distinct from Walling ed029. Exact tool/source pins and the six directly reread earlier samples: repairs/established-viewer-damaged-probe-20261115/{review.md,pins.json}. No OCR or new fetch occurred.

**2026-11-15T13:34:46Z**

Mahoney selected 4d04558965d9baf630033c94857169bfddad68988fce34041a4a35a0c6ddd2a8 / text 04b5bb0d829fde64467f8e44f6e661152386d152568ee07ae2256e9d795c40a9; 4,524 bytes, three pages/three OCR markers, +80 bytes. Independent actual-native/selection review passes, preserving radio-state ambiguity and name typo. The 49-source archive-only inspection verified 46,370,178 decoded bytes; 42 originals are shorter than declared linearized length, six end inside streams without recoverable trailers, one has a 54,818-byte zero tail. All fail qpdf checks. Capture complete=True is a transfer observation, not PDF semantic completeness, and the damage origin remains unknown. repairs/zero-page-cause-inventory-20261115/handoff.json SHA 1f95436520591946b23494465bc1c543f799dc91d8a2a1d0d36ac6b6260264e0 binds the evidence. The proposed 49 primary URLs retain all 52 spellings; 47 are outside the pinned static scope, two inside, and one needs a target-specific 32 MiB bound. No publisher requests for this proposal have run. Two selected same-URL alternatives need document/revision review before new acquisition.

**2026-11-15T15:42:25Z**

Updated the invalid-source inventory at the user's request so successful transfers cannot hide unusable files. Durable generation: repairs/source-recovery-inventory-20261115/{invalid-sources.jsonl,invalid-sources.csv,summary.json,verification.json,README.md}; tracked entry point: docs/plans/ocr-source-recovery-inventory.json. There are 451 exact invalid-source records: 56 damaged PDF bodies, one empty Cornwell response, and 394 error responses (384 existing template examples plus ten reviewed excluded errors). The short bill is covered by e5de955c; all other 450 stay open. All 49 zero-page cases retain needs_refetch=true, including the two pending alternate comparisons. The 47 actual refetches preserve timestamps, URLs, HTTP status, returned hashes, receipt keys and same-invalid-source refusals. Four wrappers link to three existing damaged bodies. HTTP/transfer/parser success does not close recovery; require reviewed usable replacement or accepted scoped coverage tied to the intended document/revision. Error responses remain history-review work, not 394 automatic requests. Metadata verification passed with exact 49/47/2 conservation, input/output pins, deduplication and preserved valid controls. No OCR, fetch, catalog or selected-text mutation. Updated corpus-recovery instructions to consume this worklist. Earlier notes describing the 47 requests as unrun are superseded; URL counts are 51 requested, 54 final, 56 across all four URL fields.
