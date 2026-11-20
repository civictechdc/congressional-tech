---
id: ct-z4w5
status: in_progress
deps: []
links: [ct-en4n, ct-saqg, ct-4jms, ct-6v77, ct-5cdu, ct-m704]
created: 2026-11-13T17:46:16Z
type: task
priority: 3
assignee: mikewolfd
tags: [body_text, captures, refetch]
---
# Recover qualified damaged or missing sources and reconcile each attempt

## Implementation update — 17 November 2026

Three selected alternatives now have direct Terra-medium source/native/selected-output reviews and scoped search-coverage records. Their later-edition or missing-original limits remain explicit. Original invalid bytes and recovery obligations are preserved; identical failed requests were not repeated.

The maintained guarded integration uploaded ten exact create-only raw objects (297,472 bytes) and appended five retained receipts to authoritative captures. Snapshot advanced `729090216083851021` -> `5877413658015059876`; exact five-row native readback, unchanged other heads and the producer Gate-5 check passed. Failed HTTP 410 and HTTP 200/empty outcomes remain failed. One older Mast error receipt is held because its gzip representation differs from the immutable stored representation; neither was overwritten. Evidence: `<main checkout>/.cache/archive-release/ticket-fixes-20261117/inventory/capture-integration/`.

Remaining: Mast's recovered PDF is now captured but still needs normal model document association and reviewed-text adoption, as specified in `mast-association.md`. Exact-original recovery remains open for 454 inventory records, with backoff/history eligibility and scoped alternative coverage kept separate. The final handoff pins the successor inventory and completed capture integration.

## Audit baseline — 17 November 2026

The current inventory has 450 open records: 56 PDF/empty-response recovery cases and 394 error-response cases needing capture-history review. All 47 actual requests in the 49-source zero-page batch returned the same invalid bytes; two GovInfo alternatives still need document/revision comparison. A selected replacement covers the truncated short bill. Mahoney is selected; Mast's receipt/document association and Cornwell's empty response have no verified closeout in the reviewed evidence.

ct-en4n owns adding four newer publisher error bodies and linking two archive wrappers to existing failures. Those additions require reconciliation before revised unresolved counts or requests. v12 prose exclusion is not source recovery, and historical `needs_refetch=null` means unresolved history, not success.

## Scope and ownership

Own acquisition attempts, alternative-copy qualification, receipt ingestion, intended-document association and recovery closeout. Consume the canonical inventory owned by ct-en4n. Its eligibility gate applies per source: work on already qualified targets need not wait for every unrelated history review. The 14 November user authorization permits targeted OCR/refetch; preserve originals, partial bytes, headers, receipts, prior accepted fallbacks and historical outcomes.

## Acceptance Criteria

1. For each requested source, retain current URL/history eligibility, old/new hashes, receipt and completion evidence. Reuse maintained acquisition/recovery components; avoid immediate same-byte retry loops and preserve backoff.
2. Compare the two GovInfo alternatives against the intended document/revision. Reconcile Mast receipt ingestion/association and Cornwell or record an explicit unresolved cause. HTTP 200 and complete=True cannot close damaged content.
3. Every processed item ends in a reviewed usable selected replacement, explicitly accepted scoped coverage or a named unresolved state. Do not erase invalid originals or count an exclusion as a replacement.
4. Hand changed reading/source identities to ct-m704 for delivery and readback; keep logical associations intact. Directly read bounded raw -> intermediate -> output examples for candidate replacements, using gpt-6.1-terra at medium reasoning for bulk PDF review. No blanket request over all 394 history cases or corpus-wide OCR.

## Audit evidence

17 November manual audit: `<main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md`; PDF sample: the sibling `pdf-manual-review.md`. New v12 files: `<main checkout>/.cache/archive-release/ocr-recovery-20261113/repairs/body-text-ssot-20261116/`. These evidence files retain the exact inputs, identities and sampled/unread scope. Historical notes below are dated evidence; the current scope and criteria above supersede their unfinished-work summaries.

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

**2026-11-17T09:17:02Z**

Manual audit keeps this open: exclusions and successful HTTP transfers do not recover source content. Preserve 47 same-byte failed requests, two alternative-revision reviews, the named Mast/Cornwell obligations and per-attempt evidence. ct-en4n owns new invalid-source inventory reconciliation. Replaced its whole-ticket dependency with a per-source eligibility requirement so qualified targets can proceed while unrelated history remains open; no fetch was launched by this ticket update. Audit evidence: <main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md.

**2026-11-17T10:28:53Z**

Implemented selected 80/20 scope via subagents. The current implementation update above records completed work, exact evidence and remaining acceptance. Full evidence is under <main checkout>/.cache/archive-release/ticket-fixes-20261117/. Historical notes are preserved.

**2026-11-18T15:24:52Z**

2026-11-18 owner decision (questions tool): the 47 zero-page PDFs whose refetch returned byte-identical damaged files are to be recorded as 'publisher's copy is broken (seen 2026-11-15)', taken off the publisher-refetch list and kept open as 'find another copy'. Checked today: all 47 refetched files re-hashed equal to their originals; HTTP 200; the server's stated size equals the damaged size; publishers' last-modified dates are 2012 and 2015. Retry a publisher only if its last-modified date or version tag changes. A Wayback index check for older differing copies is running (reviews/ticket-state-20261118/g-wayback/); the owner also asked for Firecrawl search for relocated copies through corpus_recovery.discovery_runtime, which waits on FIRECRAWL_API_KEY being available to the session. The inventory files themselves are not yet changed.

**2026-11-18T17:57:22Z**

2026-11-18 search for another copy of each of the 49 damaged PDFs (index and header queries only; nothing downloaded or adopted). Evidence: .cache/archive-release/reviews/ticket-state-20261118/g-wayback/ (g_summary_by_document.json is the per-document table).
Result: 29 have a lead to another copy of the file itself, 10 more have an official hearing print from the same date, 10 have nothing yet.
- Federal Congressional Web Harvest (webharvest.gov, run by the National Archives) searched by file name in the collection for each document's Congress: a non-damaged-digest copy for 21, including 19 of the 20 from 2009 and 2010, at the old-site address (for example /images/stories/Hearings/pdfs/20090519Reuter.pdf in congress111th, captured 2011-01-06). The twentieth is there under a slightly different name (20100305Howle.pdf). The 2011 testimony exists there only as the same damaged bytes: the next harvest was taken after the site migration.
- Same site, neighbouring upload folder: 8 of the 38 oversight.house.gov files have a larger copy at /wp-content/uploads/2012/02/ (most exactly 32,768 bytes larger), plus one renamed.
- Wayback Machine: for 43 of 47 it holds only the same damaged digest (earliest capture 2012, so the damage dates from the migration); 3 never captured; one real lead (House transcript 1748f1a2) and one that looks cut off too. Two 2011 files were found at the old-site Testimony folder (captured 2011-04-06).
- Official homes: the FTC testimony on ftc.gov; S. 3492 as reported on GovInfo (BILLS-117s3492rs); the GAO report's page exists but answers plain clients with 403.
- Hearing prints: Firecrawl's free government index plus a check of each package's held date and names on GovInfo: 15 by the index, 5 more by Google through SerpApi, 2 more in a date-led pass. A same-date print identifies the hearing; it does not show the testimony is printed inside.
- Library of Congress: its catalogue (loc.gov item lcwa00hsgo00) confirms it archived the Oversight site 2002 to 2020, which covers the 2011 gap, but webarchive.loc.gov answers automated clients with a bot check (HTTP 403, also to an undisguised Playwright browser). Not worked around. Lookup links for a person are in g-wayback/loc/LOOKUPS.md.
- Pattern: 38 of 49 come from oversight.house.gov; 37 of 49 have a size on a round boundary.
Tools: the free government index was best; SerpApi (manual, owner's standing rule for edge cases) added 5 prints and exposed the neighbouring-folder pattern (39 + 26 + 25 searches); the paid Firecrawl web search did worse (78 credits) and is not worth using here.
Next: fetch the 29 file-copy leads through the normal capture path and qualify them (pull request 205 adds the rungs); confirm the shared-prefix check on real bytes; ask the owner about the hearing-print stand-ins; ct-zohj covers starting recovery automatically.

**2026-11-18T18:42:11Z**

2026-11-18 later: the Library of Congress web archive holds every 2011 file. Opened in the owner's own browser at the owner's request (the site's bot check refused curl and an undisguised Playwright browser, and was not worked around): the listing https://webarchive.loc.gov/all/*/http://oversight.house.gov/images/stories/Testimony/* shows 710 archived addresses, and all 18 of the damaged 2011 Oversight testimony files are there under their original names at the old-site address, first captured between April 2011 and January 2012, before the site migration that damaged them (table: g-wayback/loc/loc_listing_20261118.tsv; the Library's catalogue record is loc.gov/item/lcwa00hsgo00, captures 2002 to 2020). Read from the listing only; no file was opened or downloaded.
Standing now, per document (g_summary_by_document.json): 41 of 49 have a lead to another copy of the file itself (Web Harvest, Library of Congress, neighbouring folder, Wayback or an official home), 5 have only a same-date official hearing print (a 2015 biography, two 2021 disclosure forms, a 2023 Senate document, a 2024 transcript), and 3 have nothing yet: HHRG-116-VR03-Transcript-20191030.pdf, HHRG-117-VR00-TTF-BarlettT-20220428-U1.pdf, and gao-26-109023.pdf (GAO's own page exists but refuses plain clients).
The Library's archive cannot be a pipeline rung while it screens automated clients: fetching those 18 needs a person, or a request to the Library's web archiving team for research access.

**2026-11-18T20:16:29Z**

2026-11-18 follow-up (non-LoC leads, hearing prints, browser bridge, LCWA catalog map; local staging only, no remote R2 writes):
- Non-LoC qualification (`.cache/archive-release/loc-followup-20261118/non-loc-leads/{results.json,SUMMARY.md}`): 39 attempts across 32 distinct damaged cases yielded **28 cases** with qualified matching PDFs (`all_pages_decoded_and_rendered`, retained via `ReceiptWriter`, `identity_status=candidate_qualified_pending_source_acceptance`), including **8 of 18** 2011 Oversight PDFs (`1a4cc0de04cb`, `677db170f657`, `67adc19448ab`, `7d29f9acb71f`, `8a4e7ce24642`, `95c584656b56`, `95d508e6988e`, `d3dba58954b1`), `ftc-testimony` via IA Wayback (`6bc8d4492d69`), `HHRG-118-VC00-Transcript-20231213.pdf` (`1748f1a2e34c`), `BILLS-117s3492rs.pdf` (`34a4dc913a51`), and 17 NARA Web Harvest 2009-2010 files (including renamed `20100305Howle.pdf` `25b378fff39c`). Three 2009 Web Harvest PDFs (`05fc38c285f3`, `4c90083757ec`, `d2ba37b370d0`) matched declared lengths & prefixes (20, 16, 12 pages) but `qualification.py` flagged them `unresolved` (`corrupt_pdf_stream` / `encrypted_pdf`). `2013/02/Gordon-Testimony.pdf` (`shared_prefix=16`) was rejected as a 2013 hearing (`rejected_different_hearing_2013`), leaving `e75db22795c2` in the 10-file LoC list.
- 5 hearing-print-only cases (`.cache/archive-release/loc-followup-20261118/hearing-prints/{verification.json,SUMMARY.md}`): 2 `requested_content_in_official_hearing` (`7451a1761b70` -> `CHRG-118shrg55540`, `dfdd2b8e943c` -> `CHRG-118hhrg58136`; standalone URLs stay unrecovered), 3 `omitted_from_hearing_print_unrecovered` (`0cbdd25415da` `CHRG-114hhrg94232`, `2fb1d0375cce` `CHRG-117hhrg43632`, `d01597f14710` `CHRG-117hhrg46026`).
- Browser-session capture bridge (`scripts/corpus_recovery/browser_session_capture.py` + `loc-followup-20261118/browser-bridge/`): ready to capture and qualify the **10** remaining 2011 LoC Oversight PDFs (`08ca05e57e8d`, `393a5e841885`, `4c53c6108c99`, `65b640217635`, `7b2002ff1a85`, `82fd78b27f86`, `9c50cb2fe0da`, `9edf73c62033`, `aa4b1c25d0db`, `e75db22795c2`; awaiting canonical 14-digit `id_` timestamp resolution from `browser_lookup_url`) + optional `gao-26-109023.pdf` into local `BodyStore` + `ReceiptWriter` receipts.
- LoC Congressional Web Archive catalog map (`scripts/webharvest/loc_congressional_archive_map.py`, `loc-followup-20261118/lcwa-catalog/{inventory-overlap.json,SUMMARY.md}`): indexed all 1,414 LCWA results (`1,412` `lcwa*` archive item records + `2` collection info pages) across 1,400 unique normalized hosts; supplemental `web-archives/?fo=json&q=docs.house.gov` also found `lcwaN0016311` (`docs.house.gov/`, 2001-2025), covering `8a4e17b45921` (`HHRG-117-VR00-TTF-BarlettT-20220428-U1.pdf`). Across the 454 open `invalid-sources.jsonl` records: 188 lack `source_urls`, 266 have URLs -> 53 match LCWA hosts (39 known-year overlapping, 12 unknown-year, 2 known year-mismatch; led by `oversight.house.gov` 38), 213 lie outside LCWA (197 Senate Akamai `.m3u8`).

**2026-11-18T22:50:25Z**

2026-11-18 Milestone 2 vetting, 3-PDF diagnosis, local receipt staging, and Phase 1 review fixes (zero R2 writes, zero network calls, qualification.py & byte-hashed parsers untouched):
- 3 unresolved 2009 Web Harvest PDFs diagnosed (.cache/archive-release/loc-followup-20261118/ct-z4w5-vetting/three-2009-pdfs-diagnosis.md): all 3 are exact-prefix + exact-declared-length intact originals that pass pypdf(strict=True), PyMuPDF, pdfinfo/pdftoppm/pdftotext rc=0, and congress_api downstream pdf_tools/document_cover. Reuter (05fc38c285f3, 297,535B, 20pp) and Ruckelshaus (d2ba37b370d0, 272,236B, 12pp) are Acrobat Distiller 7.0.5 PDFs whose Catalog['/OCProperties'] omits /D, causing Poppler stderr 'Syntax Error: Expected the default config...' to trigger qualification.py:477 (corrupt_pdf_stream). Dicken (4c90083757ec, 216,355B, 16pp, GAO-09-819T) is Standard V2 R3 128-bit RC4 owner-permissions-only (P=-1340) with empty user password (decrypt('')==1, PyMuPDF needs_pass=0, pdfinfo rc=0 empty stderr), triggering qualification.py:426 (encrypted_pdf). Policy options recorded; qualification.py left untouched.
- Bounded raw + visual + intended-document review of all 28 qualified non-LoC PDFs (.cache/archive-release/loc-followup-20261118/ct-z4w5-vetting/{vet_and_stage_28.py,vetting-report.json,MANUAL-REVIEW.md,renders/}): all 28 pass (0 wrong documents; 24 exact-prefix + exact-declared-length; 4 non-exact-prefix verified against raw/reconstructed damaged pages: 1bf7f4055319 exact 262,144B prefix + 54,818B zero tail, 6bc8d4492d69 shared /ID[0] + identical p1 text, 1748f1a2e34c same-URL 2024 born-digital GPO Serial 118-82 print matching damaged 2026 vectorized reprint, 34a4dc913a51 official GovInfo Calendar 319 BILLS-117s3492rs.pdf matching committee pre-calendar ink-signed scan DAV22435 06W; 5 clean image-only scans noted for downstream OCR; Howle 25b378fff39c exact-prefix 507,030B canonical copy selected after 25-page zero-diff verification).
- Local receipt staging (.cache/archive-release/loc-followup-20261118/ct-z4w5-vetting/staged-captures/): staged all 28 canonical frozen receipts via congress_api.lake.capture_staging.stage_captures (captures.parquet 28 rows, 28 distinct body sha256s, all outcome=stored, sha256 0940d430b47e3d115cdfaa2c31c76f60849fe7ae733352a479f81aaed6393118; recheck_source_pins passed across 28 sources; watchdog peak 0.43 GiB RSS in 4s). Status remains in_progress awaiting owner browser captures for the 10 LoC + 1 GAO targets and policy decision on the 3 diagnosed 2009 PDFs.
- Phase 1 review fixes applied on loc-followup-20261118: hardened browser_session_capture.py (single-target-per-click step button, redirect:'manual', AbortController fetch+arrayBuffer timeout, non-clobbering resume, preflight ISO-8601 UTC timestamp + content-range + HTML/%PDF- + damaged_manifest sha256/containment guards, atomic qualification-report.json), fixed loc_congressional_archive_map.py (39 known-year / 12 unknown-year / 2 year-mismatch split, matched-host-only crediting, queued LoC visibility, Howle exact-prefix selection, redirect pacing, Retry-After on any status, cached sidecar verification, manifest.complete, fail-fast missing inputs, atomic writes; offline lcwa-catalog regenerated), fixed #364 description, and tightened check_congress_api_changelog.py reviewed_issues validation.

**2026-11-18T23:12:08Z**

2026-11-18 Review #2 fixes (staged-captures/ kept untouched, captures.parquet 0940d430b47e... & ingested-receipts.json 5a4f44ee136c... verified read-only via recheck_source_pins):
- Clarified scope boundary: the 28 locally staged rows establish verified fetch custody and visual readability/content vetting (candidate_qualified_pending_source_acceptance), while formal corpus_recovery/acceptance.py source-acceptance and edition-relationship decisions remain required downstream before replacing any original source in a published release (especially for the 4 non-exact-prefix cases: 1bf7f4055319, 6bc8d4492d69, 1748f1a2e34c, 34a4dc913a51).
- Fixed browser_session_capture.py & browser-bridge/: pickBtn now reads proposed folder manifests into temporary state first and disables capture on failed switch so prior folder state can never overwrite another folder (verified via Node JS execution test); emit_snippet rejects non-14-digit webarchive.loc.gov fetch_urls up front; replaced 4-digit selectors in loc-remaining-targets.json with explicit browser_lookup_url entries + 14-digit template and removed unusable loc-chrome-snippet.js while keeping direct gao-chrome-snippet.js; tightened ingest preflight (explicit UTC Z/+00:00 requirement, maintained leading/%PDF- binary_pdf_header check, A->B URL mismatch rejection, optional --targets binding).
- Fixed vet_and_stage_28.py (detects existing stage before any write and verifies read-only in place) and loc_congressional_archive_map.py (fail-fast missing optional input paths, reported_total_pages completeness check, atomic page byte writes, 1,412 lcwa* archive items + 2 collection info pages, filename-first year extraction + year_hint_source); corrected 3 typo 2011 case IDs (95c584656b56, 95d508e6988e, d3dba58954b1).

**2026-11-18T23:33:55Z**

2026-11-18 Re-Review #2b fixes (staged-captures/ kept untouched; captures.parquet 0940d430b47e... & ingested-receipts.json 5a4f44ee136c... verified read-only):
- Hardened browser_session_capture.py & regenerated gao-chrome-snippet.js against in-flight folder switches (captureInFlight + folderPickInFlight mutual exclusion disabling pickBtn throughout capture and binding all writes to activeDir; verified via paused-write interleaving in Node).
- Tightened default ingest replay validation to require exact equality on resolved 14-digit LoC URLs and preserve ?query strings on <14-digit legacy selectors (rejecting download?file=A.pdf -> download?file=B.pdf and mismatched 14-digit timestamps).
- Hardened loc_congressional_archive_map.py & rebuilt offline lcwa-catalog/: require .meta.json sidecar before admitting any cached page; added 4-digit M-D-YYYY / M.D.YYYY filename year extraction (fixing 9-13-2011 Boushey 65b640217635 & Lindsey 7d29f9acb71f over /2012/01/); separated CMS upload-directory-only matches from known target years (53 matched open LCWA records = 39 known_year_overlap + 2 upload_path_year_overlap + 9 unknown_year + 3 year_mismatch).
- Updated vet_and_stage_28.py to reject mismatched --exclude requests against an existing stage and preserve vetting-report.json staging metadata on --vet --stage retries; softened Vargas (1bf7f4055319) in MANUAL-REVIEW.md to supported reconstruction over the 54,818-byte zeroed tail (pending_source_acceptance).

**2026-11-20T17:29:40Z**

2026-11-20: Ran formal corpus_recovery.campaign.import_candidate acceptances on all 29 vetted targets (28 damaged PDFs + Mast &download=1 malformed URL -> 29/29 accepted), generated model/jobs/inputs/recovery-requirements-ct-z4w5-20261120.parquet (43 rows, sha256 f0ba05f6867c98a1456bda286208409dec53b5a87a3fd6a44f5052bfa0a24b9b), reconciled docs/plans/ocr-source-recovery-inventory.json (455 rows: 26 already_covered, 429 recovery_open, 6 needs_refetch; 47 broken publisher copies marked publisher_copy_broken_2026_11_15), and uploaded & HEAD-verified 29 create-only raw bodies, receipts, recovery provenance records, and provenance/verification/20261120T140000Z-1aeda80f03936bd7.jsonl on R2 (commits 0e554d3f, 4a2478fd); awaiting archive-jobs.yml publish ingestion & readback (10 LoC + 1 GAO remain gated by external Cloudflare/Akamai bot challenges).
