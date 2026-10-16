# Finish corpus document recovery

Goal: make genuinely missing documents accessible in the viewer and give remaining URLs an evidence-backed disposition. Preserve existing files, source relationships, and failure evidence. A filename, HTTP 200, or stored response alone does not prove recovery.

## Verified checkpoint

The accompanying `../recovery/corpus-recovery-checkpoint-20261016.json` records the snapshot time, counts, and local evidence hashes. These counts describe local preparation, not publication:

- 184 recovered URL links reference 137 distinct validated file bodies.
- 15 retained ZIPs yielded 149 distinct validated PDFs, with prepared parent/member receipts. No ZIP redownload was needed.
- The combined preview adds 5,924 URL mappings while preserving all 14,505 previous mappings.
- Document groups without a saved copy fall from 311 to 277 in the preview. The 149 ZIP members are not yet included in that reduction.
- The separately deferred 164 files remain excluded.

The first direct NARA session processed 35 of 776 entries: 33 validated links, one unsuccessful entry, and one rate-limited entry. It stopped on HTTP 429. The new continuation includes 741 untouched entries plus the rate-limited entry, preserves the original run, reuses successful digests, and waits 15 seconds between requests. Its live status is `output/corpus-retry-20261015/nara-direct-resume/status.json`.

One Zyte HTTP proxy request returned a rate-limit page. Actual billed cost is not yet known; the pass has a $25 total cap and a $0.02 conservative reservation for that request. Current acquisition uses direct Web Harvest access, with no active paid route.

## Remaining work and completion evidence

1. Finish targeted acquisition. Reuse completed indexes and valid files before requesting anything. Finish the direct NARA queue; stop on rate limits, access checks, or repeated transport failures. Preserve those outcomes as unfinished, not absent. Retry the eight incomplete Wayback index partitions within the existing bounded retry policy; keep complete partitions. Check official package and retained-body routes before paid fallback. Record each outstanding URL's next route or reason to stop.
2. Combine recovery evidence. Merge newly validated bodies and URL associations, verify full hashes, deduplicate bodies without losing URLs, and regenerate the preview. Validate every ZIP member's parent association. Preserve prior mappings and exclude the 164 deferred files. Report unique URLs, unique bodies, and missing document groups separately.
3. Wait for the existing cloud writer. Run 38823678887 was active at the checkpoint. Do not cancel it or publish over its inputs. Before any shared write, verify all cloud capture writers are clear, acquire the existing local recovery lock, and read fresh raw index versions, selected catalog, and accepted mappings. Rebase preparation if they changed.
4. Import and publish. Use maintained import/publication functions, retain original ZIP parent/member context, and preserve raw download state where required. Upload only absent verified bodies. Use conditional updates and reconcile uncertain acknowledgments before retrying. Do not select an older catalog or overwrite another writer's mappings.
5. Verify the user-visible outcome. Read back the selected generation and paired catalog hashes, verify all new URL mappings reference retained bodies, and check representative PDFs through the public viewer, including ZIP members, official bill aliases, and archive recoveries. Publish final counts and remaining dispositions with the exact snapshot time.

Completion requires successful publication and readback, not just this plan, a running downloader, or a local preview. Blocked routes do not establish archive exhaustion or corpus completeness. No video bytes are in scope. Commit only this recovery checkpoint and plan; existing unrelated workspace changes remain separate.

## Local batch preparation

`scripts/prepare_corpus_recovery_batch.py` creates an immutable local snapshot of the recovered mappings, ZIP receipts, and body inventory. It verifies complete body hashes and sizes, ZIP coverage and parent context, mapping membership, and deferred URL exclusions. It does not upload, import, or change a selector. Use a new destination for each checkpoint; never overwrite a prior snapshot.

```sh
.venv/bin/python scripts/prepare_corpus_recovery_batch.py \
  --source output/corpus-retry-20261015 \
  --deferred output/viewer-streaming-rerun-20261015/accepted-files.json \
  --destination output/corpus-retry-20261015/publication-batches/checkpoint-01
```

The first snapshot was successfully prepared. Five offline tests verify the valid case and rejection of corrupt bodies, deferred URLs, missing mappings, and ZIP members lacking receipt coverage. This local batch is an input to the guarded importer; it does not replace the fresh cloud/input checks or final publication readback above.

## Readiness update

The separate `../recovery/corpus-recovery-readiness-20261016.json` records the newer preview and evidence hashes. Its frozen `checkpoint-02` batch contains 208 URL links; it is smaller than the still-growing combined preview. Full R2 readback verified 123 existing body objects, and 202 body keys were absent. There were no conflicting bodies. All 208 source records have established timestamps and provenance; three bill records preserve their original GPO capture URLs rather than implying new GovInfo requests. These checks do not authorize reuse of stale selector or raw-index versions.

Acquisition now includes 132 official GovInfo bill packages for 144 explicit bill-version URLs outside the active NARA queue. Package-generation responses use their requested delay and at most three total attempts per package. Successful packages are reused across continuations. Wayback's eight incomplete partition lookups remain unresolved: its retry worker was stopped after three consecutive transport failures, preserving partial evidence.

At publication time, regenerate the final batch from the completed acquisition evidence, extend the body/source-record checks to all additions, and use fresh shared-state versions. Keep the ZIP member import, raw-state preservation, selected catalog rebuild, accepted mapping update, and public viewer readback in the completion checklist. Local source-record preparation has not assigned fresh download state or written receipts remotely.

## GovInfo acquisition completion

The 132-package queue is fully accounted for: 127 packages yielded validated PDFs covering 139 URL links; five package routes returned HTML rather than ZIPs. No package remains unprocessed. The exact unresolved identifiers and evidence hash are recorded in `../recovery/govinfo-package-completion-20261016.json`. Those five links need their original committee attachment or an archive capture of the requested version; do not silently substitute another bill version.

The combined local preview at this checkpoint contains 508 recovered links referencing 441 distinct bodies, plus 149 ZIP-member PDFs. NARA acquisition remains active, so these counts are a snapshot. Finish that queue, classify its unsuccessful results, and prepare the final publication batch. The existing cloud capture run remains active; import and publication are still pending.

## Expanded import preparation

The immutable `checkpoint-03` contains 518 recovered links, 15 ZIP parents, and 149 ZIP-member PDFs. Its 615 distinct body objects include 302 verified existing R2 objects and 313 absent objects. Existing-object verification used 179 fresh full-body reads and 123 earlier full-body verifications with fresh matching object versions and sizes. No conflicts or unresolved objects were found. This is a preparation snapshot, not publication.

All 518 recovered links have source timestamps. An offline schema roundtrip retained all 682 capture rows from 533 receipts, including every ZIP member's filename, parent association, body reference, and source timestamp. The evidence is recorded in `../recovery/corpus-recovery-batch03-20261016.json`. The preview uses explicitly local placeholder receipt locators and must never be uploaded as an index. The guarded importer must create real immutable receipts, include every capture rather than just the first capture in each receipt, assign verified stored-body metadata, and preserve fresh download state.

A direct follow-up on unresolved bill attachments returned identical HTML for two links and HTTP 403 for a third. The probe stopped and retained its responses; two further links were not attempted by that probe. These results do not establish that archive copies are absent.

## Import assembly implementation

`scripts/assemble_corpus_recovery_import.py` now assembles every capture in each prepared receipt and creates index rows without network access. Five focused tests cover ZIP member retention, unchanged existing retry state, pending new URLs, mismatched body metadata, missing source associations, and wrong ZIP parents. The frozen batch check produced all 682 capture rows, preserved 262 existing historical state rows, and left 204 additional source URLs pending. Evidence: `output/corpus-retry-20261015/publication-batches/checkpoint-03/assembly-verification.json`.

The guarded importer still needs to call this assembly with fresh state and remotely verified body metadata, write immutable receipts, and conditionally update both indexes. This module does not itself acquire a lock, check cloud ownership, upload, or publish.

## Guarded import core

`scripts/import_corpus_recovery_batch.py` now integrates the tested assembly, immutable body and receipt retention, conditional raw-index updates through `R2Store`, and exact readback. Each write invokes an injected ownership/input guard. An uncertain acknowledgment is reconciled read-only without repeating the PUT. A partial index pair cannot produce an import-complete result; proposed receipts and both indexes must be saved locally before their writes.

Five network-disabled tests passed for complete ZIP import, lost acknowledgment without duplicate writes, cloud-guard refusal before writes, a partial-pair failure, and changed local bytes. The dispatch wrapper still must provide the real lock, fresh baseline, cloud and input checks, durable evidence callbacks, and one-shot execution. Catalog rebuild and viewer publication remain separate required steps. No shared writes have been dispatched by these tests.

## One-shot dispatch driver

`scripts/dispatch_corpus_recovery_import.py` supplies the import core with sealed-file checks, an exclusive local recovery lock, complete paginated cloud-writer checks, fresh raw-index/selector/accepted-mapping versions, code/input pins, disk and parent checks, durable local payloads, and a write journal. Default mode is read-only preflight; `--execute` is required for the authorized import. Existing dispatch directories cannot be reused after a failure. SDK request retries are disabled so uncertain PUT acknowledgments are reconciled before any further action.

Four offline driver checks passed. A live read-only preflight correctly refused while cloud run 38823678887 was active and created no dispatch directory. After acquisition finishes, prepare a new complete batch and its source/readiness evidence, then run preflight again. Execute only after the cloud writer is clear; use a fresh destination and inspect any failure journal before considering another attempt. A successful raw import still requires catalog rebuild, mapping publication, and viewer readback.

The driver suite now has six passing offline checks, including end-to-end execution through the maintained `R2Store` with a simulated conditional object store. The successful case verified immutable conditions on bodies/receipts and baseline-version conditions on both indexes. An injected competing capture-index update after the state write stopped before the capture PUT, preserved the failure journal, and produced no completion marker. This is simulated boundary evidence, not a live import.

## Recovery work beyond the active NARA batch

The 2026-10-16 03:05 UTC ledger accounts for 23,574 eligible URLs: 644 validated local recoveries, 6,209 unprocessed archive candidates, 16,682 unresolved lookups, and 39 unsuccessful attempts. These categories count URLs, not unique missing documents, and are not a publication claim.

Offline triage of the 6,209 unprocessed candidates identifies 388 entries still in the active NARA queue, 408 additional PDF candidates, 26 XML candidates, two Word candidates, and 5,385 HTML candidates. Preserve all categories: an HTML capture can be a useful source page, but does not establish recovery of a linked PDF. MIME labels are planning hints pending body validation.

A full local hash check of 579 retained bodies found archive-digest matches for 15 of the additional 408 PDF candidates. Before downloading the next batch, validate those target associations and deferred exclusions and admit qualified reused bodies with their original acquisition evidence. The remaining 393 PDF candidates need retained-store or official-package checks before new archive requests. Do not add a second NARA downloader while the current worker remains active. XML and Word need format-specific validation; source pages need extraction of useful document links rather than a blanket recovered label.

Evidence: `output/corpus-retry-20261015/remaining-candidate-triage.json` and `additional-pdf-retained-reuse.json`. These are timestamped planning findings; refresh success exclusions before dispatch. The cloud capture writer was still active at this checkpoint, so shared import and publication remain pending.

### Target association review

Further inspection narrows the additional PDF candidates: 407 of 408 are filename-only matches; only one is an exact canonical URL match. They are search leads, not an established queue of 408 replacement files. Retained body digest equality verifies candidate bytes, but cannot establish that a generic filename belongs to the requested hearing or bill.

Of the 15 retained-body matches, one is qualified: `HHRG-113-IF14-20141210-SD001.pdf` has the same full hearing-document identifier and meeting ID `102797` at Congress.gov and docs.house.gov. Its full SHA-256, archive SHA-1, PDF validation, and deferred URL/body exclusions passed. It is included in local recovery preparation without a network request. Fourteen associations remain unresolved; several clearly differ in hearing date or bill number, such as HR980 versus HR1644 `finalvote.pdf`. Do not admit these from filename equality alone. Evidence hashes are recorded in `../recovery/retained-candidate-associations-20261016.json`.

Next, inspect the one exact URL candidate, then prioritize distinctive document identifiers and source-page context among filename leads. Reuse verified retained bytes only after establishing the requested document association. Preserve unresolved leads for further search; do not count them as archive absence or recovered links.

### Additional official report recovery

The exact-URL archive candidate for the Iran Sanctions Enabling Act has the SHA-1 digest of an empty response in both available captures. Its PDF MIME label does not establish usable content; seek another capture or the exact official document.

Nineteen additional URL leads carry structured document identifiers. Sixteen resolve to nine distinct congressional report packages. Public GovInfo package downloads completed with actual worker exit 0; all nine exact PDF members passed full hash, size, signature, EOF, and qpdf checks. Their 16 URL associations were merged into local preparation. No paid request or parallel NARA request was needed. Evidence: `../recovery/additional-report-packages-20261016.json`.

Three remaining structured hearing-document leads and 387 filename leads still need retained-source or source-context investigation. The current NARA queue remains active, and public publication still awaits cloud-writer clearance and the guarded import/readback steps above.

### Official hearing-file follow-up

The three structured hearing-document leads received direct official requests, with responses preserved and actual worker exit 0. `HHRG-113-IF17-20140522-SD002.pdf` passed PDF validation and was added to local preparation. `HHRG-114-IF14-20150611-SD004.pdf` returned HTML and remains an archive follow-up candidate. `HHRG-118-AG00-20230606-SD001.pdf` returned a PDF with a hash in the deferred-file set; it remains excluded, including through this alternative URL. This preserves the deferred-body boundary rather than bypassing it through an alias.

Evidence: `../recovery/additional-hearing-files-20261016.json`. The remaining archive follow-up must wait for the existing NARA worker and exclude successes and deferred bodies again before dispatch. The live cloud run remains in its capture/rebuild step, so no shared import or publication has started.

### Deferred-body exclusion fix and checkpoint 04

Batch preparation now rejects a deferred content hash or body key even when it arrives under another URL or as a ZIP member. Two regression tests demonstrated the previous gap before the fix; all seven batch tests pass afterward. This applies the existing deferred-file instruction at the byte-identity boundary without changing running acquisition code.

The new immutable `checkpoint-04` passed the stronger exclusion checks with 686 recovered URL links, 15 ZIP parents, 149 ZIP-member PDFs, and 775 distinct body objects. All 686 source records have established timestamps and provenance. Manifest SHA-256: `940b441049b7db96abc6a07e553a2ed5b9371da74f9c4c472fa4c58745487c5a`. This snapshot remains local and is not the final growing acquisition cohort. Extend remote body checks to this or a later final snapshot before dispatch; preserve the fresh cloud/lock/index/selector checks.

Checkpoint 04 remote readback now covers all 775 body objects: 437 already exist with matching bytes and 338 are absent. There were no conflicts or unresolved checks. Of the existing objects, 302 reused previous full-body verification with fresh matching object versions and sizes, and 135 received fresh full-body reads. The batch contains 850 capture rows across 686 source records and 15 ZIP-parent records, including 149 member captures. Its import-readiness file pins the preparation and readback evidence; `../recovery/corpus-recovery-batch04-20261016.json` records the counts and hashes. These read-only checks wrote no remote objects and do not replace fresh ownership/input verification before import.

### Retained XML bill text

Four eligible XML links resolve to exact bill-text members already retained in GovInfo packages: BILLS-117hjres75ih, BILLS-117hr5768rh, BILLS-117hr6968ih, and BILLS-117hr8876rh. Full hashes and sizes match; XML parsing confirms the congress, legislative number, and introduced/reported version. These are bill text, not package metadata. Deferred URL and body exclusions passed. All four were added to local recovery preparation without network requests.

Source-record preparation now selects the actual PDF or XML content type rather than labeling every recovery PDF. The maintained `prepare_capture` path produced one expected body-key capture per XML file with its original package receipt time. Evidence: `../recovery/retained-xml-recovery-20261016.json`. The frozen checkpoint 04 remains unchanged; include these additions and later NARA successes in the final batch.

### Expanded retained XML recovery

A scan of the full eligible queue found 59 additional XML links with exact standard bill-package identifiers. The retained catalog supplied 52 matching official XML records; full stored-body hash checks and XML congress/legislative-number/version checks qualified 54 URL links. Amendment documents use `amendment-doc` rather than `bill` or `resolution`; their metadata and engrossed-amendment form were checked accordingly. All recovered source URL/body pairs have original capture timestamps and receipt locators. No original-site request was needed, and retained local bytes were reused when validation resumed after discovering the amendment structure.

The 54 links were merged into local preparation. Four package identifiers covering five links remain without qualified retained XML: BILLS-115hr1ih, BILLS-117hr8404ih, BILLS-116hres28rh, and BILLS-118hr3058ih. Next use their public GovInfo packages, retaining the exact legislative versions. Evidence: `../recovery/retained-xml-recovery-expanded-20261016.json`. Publication remains pending; these additions are outside frozen checkpoint 04.

### Remaining standard XML packages completed

All four pending public GovInfo packages downloaded successfully, and the worker exited 0. Their exact XML members passed full body hash/size, parsed root, congress, legislative number, version-stage, and deferred-file checks. Five URL links were merged into local preparation. This completes the identified 59-link standard-package XML batch: 54 reused retained official bodies and five came from four new packages. It does not complete nonstandard Rules Committee prints, generic XML feeds, or the whole recovery queue. No further unresolved PDF URL in the eligible queue matched these four package identifiers.

Evidence: `../recovery/additional-xml-packages-20261016.json`. Preserve the actual XML format and original package receipt time during import. NARA acquisition and the cloud capture/rebuild job remain active; final batch preparation, guarded import, catalog/mapping publication, and viewer readback remain outstanding.

### Remaining report identifiers checked against retained files

A scan found 49 unresolved PDF URLs naming 27 exact congressional report identifiers. Retained official GovInfo/GPO body records supplied 25 identifiers, covering 46 links. Each body passed its full content hash and qpdf checks; deferred URL/body exclusions also passed. These links were merged into local preparation without requests to the original publishers. Evidence: `../recovery/retained-reports-recovery-20261016.json`.

Two identifiers covering three links remain for public package lookup: CRPT-116hrpt411 and CRPT-119hrpt694. Preserve exact report identifiers and use the existing bounded package route. Import must reuse the original official source URL, body identity, and capture timestamp. All added mappings remain local pending the cloud-writer, import, publication, and readback gates.

### Remaining report packages completed

Both remaining report packages downloaded successfully; the bounded worker exited 0. CRPT-119hrpt694 supplied its exact PDF. CRPT-116hrpt411 supplied only `CRPT-116hrpt411-pt1.pdf`; its package MODS metadata identifies that granule with the requested report citation. The sole PDF passed full hash/size and qpdf checks, and its `pt1` identity is retained explicitly in recovery evidence and the recovered URL. All three URL links were added to local preparation. This completes the 49-link exact report-identifier batch: 46 retained-file reuses and three links from two public packages.

Evidence: `../recovery/remaining-report-packages-20261016.json`. These remain local recoveries pending final import and publication. Continue the active NARA queue, account for unsuccessful captures, and regenerate the final sealed batch including later PDF/XML additions. Do not reuse checkpoint 04 as if it contained the completed cohort.
