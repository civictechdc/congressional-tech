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
