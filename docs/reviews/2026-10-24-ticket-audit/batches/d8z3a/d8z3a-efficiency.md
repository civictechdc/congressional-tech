# d8z3a efficiency audit: surviving publication, export and custody paths

This was a read-only review of congressional-tech at `main` c858a5a2 and docspec-rs at d9c6719. The plan referenced is `simplification-plan-20261024.md`, which I read only.

Commit `54a68ac7` (stored_sha256 round trip, engine pin, delete_gzip) is on the branches `fix/raw-data-lockdown` and `docs/ticket-audit-20261024`, **not on main**. The findings below describe main.

## Variables

| Symbol | Meaning | Today's value |
|---|---|---|
| S | filename/source rows | 1.68M |
| D | document/component rows | 1.24M |
| O | observation occurrences | 7.25M |
| N | capture rows | 3.9M |
| R | receipts | 2,289 |
| B_r | distinct bodies across the 17 retained recovery batches | 13,748, in 16,860 captures (counted from `output/corpus-retry-20261015/publication-batches/*/prepared-source-records.json`) |
| F | export files per release | sources, components, occurrences, document_occurrences |
| w | columns per row | |
| H | journal events | |

**Measurements run** (project venv, scratch probe `d8z3a_test_import_counts.py` plus `cProfile`):
- `cProfile` on `test_import_corpus_recovery_batch.py::ImportTests::test_complete_zip_import_and_pair_readback`.
- A counting wrapper around that fixture's store, active only during `import_batch`.

Everything else is marked "reasoned, not measured".

---

## Findings, ranked by cost at today's scale

### 1. Recovery import downloads each body it writes, plus one extra GET beforehand

**Code:** `corpus_recovery/transfer.py`. This module survives the plan.

**Measured.** In one import of 2 new bodies:

| Object class | PUTs | GETs |
|---|---|---|
| bodies | 2 | 4 |
| receipts | 1 | 1 |
| indexes | 8 | 13 |

That is 2 GETs per new body: a pre-read and a readback.

The existing test enshrines this. `test_import_corpus_recovery_batch.py:194-208` asserts `store.reads.count(key) == 2`, which tests the mechanism, not the contract.

**Big O.**
- Requests: O(B) PUTs plus 2·O(B) GETs, and one full-object download per new body.
- Every object written through `GuardedStore.put` (receipts, native indexes) gets one PUT plus one full readback.
- Local work per body: 2 reads of the raw file (`:108-112`, then `:116-117` with `read_bytes`) and 2 SHA-256 passes over the raw bytes.
- 1 gzip compression, then 1 decompression of the payload this code just compressed (`:134`).
- SHA-256 over the gzip payload twice: once for the journal intent (`:29`) and once for `stored_sha256` (`:136`).
- MD5 twice inside `R2Store.put` (`r2.py:112`, `:128`).
- An already-present body costs a full GET plus a decompression (`:129,134`), where a HEAD would do.

**What the repeats buy.**
- The readback after a successful PUT (`transfer.py:41-44`) buys nothing. `R2Store.put` already sends `Content-MD5`, so R2 rejects corrupted bytes, and `verify_upload` already checks the ETag against the MD5 (`r2.py:111-129,394`).
- The pre-GET (`:129`) is a read-before-create that `IfNoneMatch='*'` already does atomically.
- The readback is useful only after a lost acknowledgement (`write_recovery.py:8-40`) or a 412.

**The easy way.**
- PUT with `IfNoneMatch='*'` and trust the 2xx, which `Content-MD5` already verified.
- On a 412, or a lost acknowledgement, use WS2's single verifier: HEAD, then compare size and the stored digest. Do a full GET only when they disagree.
- Hash and compress each local body once, and reuse that digest.

**Scale.** About 13.7k redundant full body downloads plus 13.7k pre-GETs across the retained batches, plus one readback per receipt and index object.

### 2. The export-pins local export path re-implements engine export in Python, materializing whole tables four times

**Code:** `filename_exports.py:820-1104`. The plan's WS6 step 6 says to time it against the native path.

**Big O (reasoned from code, not measured at scale).**

Memory is O((S + D)·w) Python objects, four times:
- `_sort_components_table` calls `to_pylist()` on the whole components table just to sort it (`:702`).
- `compute_facet_entries` calls `to_pylist()` on all of sources, including nested occurrences (`:507`, via `:868`), and on all of components (`:932`).
- `fold_source_readings_table` calls `to_pylist()` on all of sources again (`:587`).

Each occurrence also becomes a Python dict, so another O(O) objects (`:385,414-433`).

I/O repeats:
- `compute_browse_ranges` re-reads every file it just wrote and decodes the key columns per row group (`:470-500`). The writer already recorded min/max statistics (`write_statistics=True`, `:858,925`).
- `file_identity` re-reads and re-hashes each of the 4 outputs after writing them (`:842,861,904,927`).

**The engine already does all of this.**
- `ExportPin` carries `facets`, `browse_ranges` (row-group key bounds) and `child_tables` (`docspec-rs/src/export.rs:374-394`).
- The writer hashes while it writes (`HashingFile`, `src/engine/export.rs:658-668`).
- Plain Arrow equivalents would be `pc.sort_indices` with `null_placement`, `pc.list_flatten` plus `list_parent_indices`, and Parquet `RowGroupMetaData.column(i).statistics`.

**The easy way.** Delete the local path and keep `native.export(...)` (`:763-818`).

**Plan change (WS6 step 6):** don't time both paths. Decision 6 already settles it, and the local path is a hand-written duplicate of engine operations. It is not wired into any workflow today; the cost above is what it would cost if chosen.

### 3. The export-pins publisher hashes every file but sends no checksum, and publishes an incomplete release

**Code:** `client.py:310-391`, `publication_cli.py:155-172`.

**Per release:**
- For each file, one SHA-256 pass (`client.py:327-330`) and one upload pass.
- No `ContentMD5` and no `ChecksumSHA256` is sent (`:335-342`), and the returned ETag is never compared. So the hash pass verifies nothing, yet it is reported as a `VerifiedTransfer`.
- A 412 returns the *local* digest as if it were verified (`:344-349`).

**Correctness gaps found while tracing the I/O:**
- The upload list is hard-coded to `sources`, `components` and `occurrences` (`publication_cli.py:162`). It omits `document_occurrences.parquet`, which the export writes (`filename_exports.py:897-905`), and the manifest, which the pointer names (`:169`).
- In native mode, the engine writes its exports to host paths given in `pin.object` (`export.rs:470-520`), so nothing under `args.directory` matches and no data object is uploaded.
- The pointer is always written with `IfNoneMatch` (`expected_etag` is None, `client.py:294,383-389`), so every publish after the first fails with 412.

**The easy way.**
- Upload exactly the objects the pins name: primary files plus `child_tables`.
- Send `ChecksumSHA256` so R2 verifies the bytes server-side. R2 accepting `x-amz-checksum-sha256` is **reasoned, not verified offline**.
- On a 412, HEAD with `ChecksumMode=ENABLED` and compare.
- Read the pointer's ETag first, then advance it with `IfMatch`.
- The engine's digest is blake3, which S3/R2 cannot check. So either Python hashes once with SHA-256 and sends that hash, or docspec-rs adds SHA-256 to `HashingFile` as a generic primitive (WS9).

**Plan change (WS6 step 1):** give each object a content address from its own digest, for example `viewer-publications/objects/sha256/<d>.parquet`, rather than putting everything under `releases/<id>/`. Then a file that did not change is never uploaded again, and storage grows with changes, not with releases.

### 4. Each publish costs a full export, and the "nothing changed" skip only happens after the export

**Big O.** Each export materializes the full tables, O(S + D + O) (`export.rs:412-520`). That grows with the size of the corpus, not with the C changes in a run. The plan triggers publishing on every capture completion (WS6 step 7).

**Why the skip comes too late.** The engine caches results by operation id (`export.rs:104-123`; admission checks the spec digest at `:229-251`). But the operation id here is the constant placeholder `exp-sources-{version}`, with `version` defaulting to `v-export-01` (`filename_exports.py:745,766,773,826-827`; `publication_cli.py:41`).
- After the first run, an identical spec gets the first pin back: stale.
- A changed spec is refused.

**The easy way.** Derive the operation id from (source catalog release id, spec digest). Unchanged input then costs one O(1) engine lookup before any export. That is what actually makes the plan's "nothing changed" skip free; a release id computed from the manifest only exists after an O(S + D + O) export.

**Plan change (WS6 steps 1 and 7).** Reasoned, not measured.

### 5. A filtered ExportPin search decodes the entire components table on every query

**Code:** `catalog-v6.ts:298-318`.

**Big O.** Any text or facet query reads rows `0..D`, all columns (`:305`), and builds JS objects for every row. That is O(D·w) decode, O(D) memory and up to a full-file range transfer **per query**, with no yield in the loop. The 48 MiB decoded cache cannot hold a table with D = 1.24M rows. A missing `browse_ranges` makes the source and component lookups read the whole file too (`:252-254,275-277`).

**The easy way.** Read only the searched and filtered columns, prune row groups with the pin's facets and statistics, or have the engine export emit a search projection (`facet_sets`).

**Plan impact.** WS11 freezes this work. WS6 step 4 (reader parity) must not copy the pattern into the five methods it adds. Reasoned, not measured.

### 6. Raw body retention reads the gzip file three times (cross-check; mostly covered by WS2)

**Code:** `body_files.py:106-162`.

**Per new body:**
- The original file is read once, with SHA-256 and gzip in the same pass (`:117-125`). That part is good.
- The gzip scratch file is then read three times: MD5 (`r2.py:419-422`), upload (`:434-438`), and `stored_sha256 = file_digest(scratch)` (`body_files.py:157`).

The ingest gate's full `read_bytes` (`body_files.py:126-133`, `r2.py:416-418`) does not run in production today. `raw_sync` passes no exclusions (`cli/raw_sync.py:320-324`), and the default `accepted-files.json` is absent (the fail-open the plan already notes).

**The easy way.** Hash the gzip output with MD5 and SHA-256 while writing it, send `ContentMD5` (plus `ChecksumSHA256`), and drop the third read. If the gate is kept, check the digest from the key (`raw_storage.py:185`) before materializing any bytes.

**Cost.** O(B·size) local reads; local disk and CPU, small next to network time. Reasoned.

### 7. Recovery admission reads and hashes the same evidence files several times (my ct-4r1c)

**Code:** `admission.py`.
- `prepared-source-records.json` is read 3 times: hashed (`:144`), parsed (`:172`) and hashed again for pins (`:245`).
- The manifest is hashed in memory (`:107`) and then re-read and hashed again (`:245`).
- Readiness is read (`:115`) and later hashed (`:245`).

**Cost.** About 20 MB per batch at the largest real file (6.7 MB). Negligible.

**Do once.** Compare the pins against the digests already computed.

---

## Plan-deleted code (one line each, only where it changes the plan)

- **Journal:** the full-state rewrite plus fsync per event (`continuation.py:143-154,217-223`) is O(H²) per publish, about 62M characters for 273 writes (`combined-comparison.json`). Confirms deleting it in WS6.
- **Guarded client readback:** the per-PUT full readback (`client.py:162-174`) duplicates Content-MD5. Confirms deleting it in WS6. **Don't carry `transfer.checked_put` forward**, because it is the same pattern (finding 1).

## Findings that change the plan

1. **WS6 step 6:** delete the local export path outright, with no timing run. It duplicates the engine's facets, browse ranges, child tables and hash-while-writing.
2. **WS6 step 1:**
   - Upload the set of objects the pins name; today `document_occurrences` and the manifest are missing.
   - Address each object by its own content digest.
   - Send a checksum.
   - Read the pointer's ETag, then flip it with `IfMatch`.
3. **WS6 steps 1 and 7:** derive the engine operation id from the source release and the spec digest, so "nothing changed" costs O(1) before the export.
4. **WS2/WS3:** delete `transfer.checked_put`'s readback on the success path and the body pre-GET. Rewrite the test that asserts 2 reads.
5. **WS9 (optional):** add SHA-256 to the engine's export `HashingFile` so Python never re-hashes exports.
