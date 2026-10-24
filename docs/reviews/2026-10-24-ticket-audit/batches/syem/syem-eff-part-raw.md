# syem efficiency pass: raw capture and custody path

**Scope:** the code on this path that survives the plan:
- `retention/{r2, raw_archive, raw_storage, raw_values, raw_schemas, body_files, partition_routing, raw_state_routes, immutable_metadata}.py`
- `acquisition/raw_sync.py`
- `corpus_recovery/transfer.py`

Read-only throughout. `raw_storage`, `raw_schemas` and `raw_values` were read at origin/main 56cca36d; everything else from the checkout c858a5a2. Those three files differ only by 54a68ac7 (the stored_sha256 fix and the removal of `delete_gzip`), which does not touch any cost measured here.

**Variables:**
- N = capture rows (3.9M)
- B = distinct bodies
- S = URL-state rows (1,298,420 measured)
- C = state changes per run
- B_new = new bodies per run
- R = receipt files (2,289)
- H = history (runs and saves)
- L = rows per routing leaf

**Measurement tools:**
- `syem-eff-raw-measure.py` (project venv, run with cwd set to the scratch directory, so no `output/` state file is picked up) wraps `hashlib`, a `MemoryStore` and a counting `MemoryNative`. It drives `run_async` and `RawStorage.prepare`/`publish` on in-memory fixtures at checkout c858a5a2.
- Real leaf sizes come from the local routing-page cache `.cache/docspec-catalog/r2-native-manifests/raw-{state,bodies,changes}-v1`, one generation dated Oct 23 00:34:
  - State: 256 leaves, median 5,074 rows (range 4,861–5,273), 620.6 MB decoded, 256 distinct datasets.
  - Bodies index: 256 leaves, median 8,098 rows, 668.4 MB decoded, 256 distinct datasets.
  - raw-changes-v1: 10,151 pages, 129 MB.
- `syem-eff-raw-roundtrip.py` times the `_read_table` normalisation.

## 1. URL-state and body-index updates rewrite whole routing leaves (`RawStorage.prepare`, `_prepare_bodies`, `partition_routing`, `raw_state_routes`)

**Model:**
- Every save looks up the routing leaf of each changed key.
- It reads the whole leaf (`raw_storage.py:974`, `:1143-1153`) and merges in Python (`_merge_states` → `docspec_client._merge_row_pair`, `:1160`).
- It rebuilds the full leaf table (`:1174`, `:989`) and writes it as a **new docspec dataset** with `run_table(operation='initial')` (`_candidate`, `:1055-1072`, `:1247`).
- It then rewrites the routing path (`:1253`, `:993`).

**Big O per run:**
- Rows written: L × (leaves touched) ≈ L × 256 × (1 − (255/256)^C). For C ≥ ~1,000 that is the **whole table**, O(S + 2B) instead of O(C).
- Native datasets created: one per touched leaf (~512 per typical run), never reclaimed. That count grows with H.
- Route-page PUTs: 3 per touched leaf, because each `replace()` call rewrites root → branch → leaf.

**Measured** (fixture S0 = 8,192 states, 64-row leaves → 256 state leaves):

| C | state rows written | % of state table | body rows written | `run_table` calls | state page PUTs |
|---|---|---|---|---|---|
| 1 | 34 | 0.4% | 119 | 19 | 3 |
| 10 | 297 | 3.6% | 549 | 59 | 27 |
| 100 | 2,883 | 35% | 5,376 | 401 | 264 |
| 1,000 | 7,997 | 97.6% | 13,143 | 2,261 | 744 |
| 4,000 | 8,192 | **100%** | 23,084 | 4,051 | 768 (vs 273 if batched) |

**At today's scale** (reasoned from the measured scaling and the real leaf sizes):

| Change | Rows rewritten | Decoded MB |
|---|---|---|
| C = 100 changed URLs | ~416k state rows | ~199 |
| C ≥ 1,000 changed URLs | ~1.27M (the whole state table) | ~605 |
| B_new = 500 new bodies (1,000 keys) | ~2.04M body-index rows | ~658 |

So a normal capture run rewrites about **1.3 GB of decoded index** and creates about 512 datasets to record a few thousand changes. Write amplification is about 5,000× for a single URL change.

**Do-once violations:**
- Each touched state leaf is converted between Arrow and Python rows 5 times:
  1. `_read_table` normalisation (`:922`)
  2. `prior.to_pylist()` (`:1150`)
  3. `from_pylist(rows)` (`:1174`)
  4. `from_pylist(part.to_pylist())` just to compute `decoded_bytes` (`:1250`)
  5. `summarize(part.to_pylist())` (`:1251`)
- Each key in a split leaf is SHA-256'd again (`partition_routing.py:43`).
- The UpdateMergeSpec merge runs in Python, duplicating the engine's merge.

**Easy way:**
- Keep one state dataset and one bodies dataset.
- Update them with `NativeDatasets.update_table(keys=[STATE_KEY_FIELD], merge=STATE_MERGE_SPEC)`. That is the engine's keyed merge with key pruning, and this file already calls it on the `schema_evolved` path (`:1214-1232`).
- Let the engine's bucket partitioning (`STATE_PARTITION_SPEC`, already defined at `:378`) replace the app's 256 hash-prefix leaves.
- That deletes the copy-on-write leaves, `split_partition`, the per-leaf `RoutingPages.replace` calls, and the Python merge for raw state.
- **Interim first move:** call `replace_stream` once for all touched leaves. This cuts route PUTs about 2.8×.

**Hypothesis, not verified:** state leaves are written with `partition_by=STATE_PARTITION_SPEC`, which buckets on `state_key_sha256`. That column is not in `state_native_schema` (`:805` builds it from `_state_order`, `_state_key` and the state schema). If the engine accepts this, each 5k-row leaf becomes 64 tiny bucket files. If the client raises TypeError, the call silently retries without `partition_by` (`:1063-1072`). Check this with the real engine before relying on either outcome.

## 2. Each new body digest reads a whole body-index leaf (`_BodyLookup` → `RawSnapshot.body_info`)

**Model:**
- `raw_sync.retain` checks `digest in archive.body_info` (`raw_sync.py:443`).
- `_BodyLookup.get` (`raw_archive.py:584-604`) calls `body_info(digest)` (`raw_storage.py:599-608`).
- That reads the routed bodies leaf through native `source_batches` plus a Python round trip, then filters one key.
- The leaf cache holds **one** leaf (`:605`), and digests are uniformly random across 256 leaves.

**Big O:** O(B_distinct × L_body) rows decoded per run, plus B_distinct native read calls. This is the same whether the digest is present or absent.

**Measured:**

| Lookups | Kind | Leaf reads |
|---|---|---|
| 200 | existing digests | 199 |
| 200 | absent digests | 199 |

**At scale (reasoned):** each lookup decodes about 8,098 rows (~2.6 MB). 500 new bodies per run means about 1.3 GB decoded and 500 engine reads.

**Easy way, in order of effort:**
1. Batch the lookups per run, grouped by routing prefix: one read per touched leaf, O(min(B_new, 256)).
2. Use the engine's `read_keys(pin, 'key', ['sha:' + d ...])` on a single bodies dataset, which is key-pruned.
3. Drop the index lookup and ask R2: `HeadObject` with `ChecksumMode=ENABLED`. This works if bodies are uploaded with `x-amz-checksum-sha256` set to the stored digest. ContentLength and ChecksumSHA256 then give `stored_bytes`/`stored_sha256` with no download. The key is content-addressed, so the content digest and byte count are already known locally.

## 3. Choosing the capture queue reads almost every state leaf (`StateRoutes.candidates`, `Archive.capture_queue`)

**Model:**
- A best-first heap over the schedule summaries (`raw_state_routes.py:111-160`).
- Each popped leaf is read whole (`:154`), converted to Python rows (`:155`), re-summarised to verify (`:156`), and its accepted rows are pushed.
- Due rows are spread by URL hash, so admitting `limit` rows needs almost every leaf.
- `capture_queue` traverses twice: first with `invalid_only`, then the main pass (`raw_archive.py:714-727`).

**Big O:** O(S) decoded per run, independent of `limit` once `limit` exceeds the leaf count.

**Measured** (256 leaves):

| limit | Leaves read |
|---|---|
| 10 | 10 |
| 100 | 80 |
| 1,000 | 248 |

**At scale (reasoned):** the default `limit=5000` reads all 256 leaves, about 620 MB decoded across 1.3M rows, every run.

**Easy way:** after #1, one projected read of `url, outcome, next_attempt_at, checked_at` (`read_arrow(columns=...)`, about 4 of 14 columns), then a top-k in Arrow (`pc.select_k_unstable`/`sort_indices`). If that is still too large, a generic engine filtered-and-ordered read is a WS9 item. No hand-rolled summaries are needed.

**Related, reasoned:** `iter_states_for` reads **every** state leaf as soon as more than 512 URLs are requested (`raw_storage.py:674-683`). Its main consumers are WS7 modules.

## 4. Recovery import downloads every body twice and hashes it six times (`corpus_recovery/transfer.py`)

**Per new body:**
- **Pre-check:** `file_digest` (`:110`).
- **Read into memory:** `read_bytes` plus `sha256` (`:116-117`).
- **Existence check:** a full **GET** of the object (`:129`), where a HEAD would do.
- **Prepare the upload:** `body_payload` (content SHA-256 again, gzip, then SHA-256 of the gzip).
- **`checked_put`:** SHA-256 of the gzip for the journal (`:29`); the PUT (R2Store: MD5 twice, `r2.py:112,128`); then a **second full GET** to read it back (`:42`) and compare bytes.
- **After that:** `gzip.decompress(remote) != raw` (`:134`) and SHA-256 of the gzip again (`:136`). That digest was already computed by `body_payload`.

**Totals:**

| Case | GETs | PUTs | SHA-256 passes | Other |
|---|---|---|---|---|
| New body | 2 | 1 | 3 over content, 3 over gzip | MD5 twice, gunzip once |
| Existing body, no prior readback | 1 full GET | 0 | 1 over the stored gzip | gunzip once |

Bodies with a prior readback are already reused through HEAD with ETag and ContentLength (`:121-128`), which is the right pattern.

**Big O:** O(Σ body bytes) egress, done twice per new body.

**Evidence:** reasoned from code; not measured, because the test fixtures don't count GETs. Recovery batches are the largest bulk-ingest path, so this doubles egress where it matters most.

**Easy way:**
- Make the PUT create-only (`IfNoneMatch='*'`). On a 412, HEAD and compare ETag/ChecksumSHA256.
- Rely on R2's server-side Content-MD5 or `x-amz-checksum-sha256` validation instead of reading the object back.
- Take `stored_sha256` from `body_payload`.
- Keep "no second PUT after a lost acknowledgment": reconcile with HEAD plus checksum, not GET.

**This revises a keep-list item:** "Recovery `checked_put` with readback".

## 5. The capture path hashes the same bytes 3–6 times (`raw_archive`, `bundles`, `models/content`, `body_files`, `r2`)

**Measured** (4 × 1 MiB random bodies through `run_async`; the stored gzip is about the same size as the content):

| Shape | SHA-256 bytes per content byte | Necessary |
|---|---|---|
| Zyte-shaped in-memory, as `source_capture.fetch_source(raw=True)` builds it | **6.02** | about 2 (one content hash, one stored-gzip hash) |
| Spooled file, the Rust direct path | 2.02, plus one more full re-read of the gzip scratch by `file_digest` | about 2 |
| Fixture with `RawContent` | 8.02 (the validator re-hashes 3×) | about 2 |

**Where the 6.02 comes from:**
- `content.py:27`: one pass.
- `bundles.py:48`: the provider `httpResponseBody` copy is base64-decoded and hashed, then re-base64-encoded for a canonical check (`bundles.py:55-56`).
- `raw_archive.py:109`: twice.
- `raw_archive.py:225`: once.
- `raw_archive.py:229`: once, over the gzip.

**Where the spooled cost comes from:**
- `body_files.py:27` and `:112`: two passes over the content.
- `:156`: a re-read of the gzip scratch.
- `r2.py:419`: another re-read of the scratch to compute the MD5.
- The upload itself: a third read of the scratch.

**R2Store adds** MD5 twice per in-memory payload (`r2.py:112` and `:128`). Not measured, because MemoryStore skips it.

**Big O:** O(k × body bytes) CPU, with k = 3–6 where 2 would do. At about 1–2 GB/s per core this is seconds per GB, so it is a low priority at today's scale.

**Easy way:**
- Pass the already-known digest (`CapturedBody.sha256`/`CapturedFile.sha256`) into `prepare_capture.retain` and `body_payload`.
- Compute MD5 and SHA-256 of the gzip in the same loop that writes it.
- Send `ChecksumSHA256` instead of a client-side MD5 twice.

## 6. `RawChanges` becomes write-only after WS7 (`raw_changes.py`, `RawStorage.prepare:1269`)

**Cost:**
- Every save writes ⌈C/128⌉ + 1 content-addressed pages (`raw_changes.py:15-63`). Measured: 33 PUTs at C = 4,000.
- They accumulate forever: the local cache already holds **10,151 pages, 129 MB**.
- The consumer walks the history chain one object per 128 keys (`since`/`_values`), O(H).

**Readers:** `source_capture_inputs`, `catalog_selection` and `catalog_raw_updates`. WS7 deletes all three, and the engine already serves change reads (`read_changes`/`changes_batches`).

**Easy way:** delete `RawChanges`, `manifest['change']` and `RawSnapshot.changes_since`/`changed_*` together with WS7's incremental layer.

## 7. Lower-cost items

- **Bitmap normalisation round trip:** `_read_table` converts Arrow to Python rows and back (`raw_storage.py:922`) on every leaf and capture batch, only so that `decoded_bytes` compares equal.
  - Measured: 0.032 s per 16,384-row capture batch, against 0.0006 s for `combine_chunks()`, which gave equal `nbytes` on that test table. My input did not come through native IPC.
  - At scale: about 8 s per full 3.9M-row capture read (the Step 0 rebuild), about 3 s per full state read.
  - Fix: compare rows and a content digest, not decoded bytes.
- **Capture rows converted repeatedly within one save** (O(N_run), linear):
  - `prepare_capture_table` (`raw_archive.py:781`)
  - `capture_table` called twice (`:1108` and `:1127`, each a full round trip in `_to_legacy_capture_table`)
  - IPC serialisation and hash in `_request_digest` (`:1008`)
  - per-batch `decoded_bytes` round trip (`:1133`)
  - `_prepare_bodies` `to_pylist` (`:944`)

  That is 5 round trips where 1 would do. Fine at today's run sizes.
- **Orphan-receipt scan:** `Archive.__init__` lists all of `receipts/` every run (`raw_archive.py:672`) and looks up each delivery. It is O(R) and grows with H, but today that is only 3 LIST pages. Listing from the last selected day prefix would bound it.
- **Collision verification on 412:** `raw_sync.py:413-415`, `raw_archive.py:381-383` and `body_files.py:137-149` GET, gunzip and hash the existing object. It happens rarely, because the index check comes first. HEAD with an ETag or ChecksumSHA256 compare should be tried first, falling back to GET only for orphans whose gzip differs. This fits WS2 step 2's verifier.
- **`MetadataObjects.read`** hashes a disk-cached page twice (`immutable_metadata.py:139,156`). Trivial.
- **Hypothesis (correctness, not cost):** `R2Store._upload_manifest`/`put` skip the PUT when a *local* cache file of equal size exists (`r2.py:212-215,347-352`). A local cache hit is not proof that the remote object exists.

## Ranked top list (cost at today's scale)

1. **Leaf copy-on-write for state and body index (#1).** Per run it costs O(min(C,256)·L): about 1.3 GB decoded rewritten, about 512 new datasets and about 770 route PUTs. It grows with S and B, not with C.
   - **Replace with:** engine `update_table(keys, merge)` on one state dataset and one bodies dataset, with engine bucket partitions.
   - **Evidence:** measured 100% of the state table rewritten at C = 4,000 on the fixture, plus real leaf sizes.
2. **Per-digest body-index leaf reads (#2).** O(B_new × 8k rows), about 2.6 MB decoded per new body.
   - **Replace with:** batched lookups now; later `read_keys` or R2 HEAD with ChecksumSHA256.
   - **Evidence:** measured 199 leaf reads for 200 lookups.
3. **Queue construction (#3).** O(S), about 620 MB decoded every run.
   - **Replace with:** a projected 4-column read and an Arrow top-k.
   - **Evidence:** measured 248 of 256 leaves read for limit 1,000.
4. **Recovery import (#4).** Two full GETs and six SHA-256 passes per body.
   - **Replace with:** a create-only PUT, server checksums and a HEAD on 412.
   - **Evidence:** reasoned from code.
5. **`RawChanges` (#6).** O(C/128) PUTs per save and O(H) storage (129 MB); write-only after WS7.
   - **Action:** delete it with WS7.
6. **Capture hashing (#5).** 6× / 3× SHA-256 work, measured. CPU only.

## Plan impact

- **Q7 ("only if needed: move the raw index to one dataset per kind") is answered by measurement: needed.** The keep-list item "raw-side routing (`partition_routing.py`, `raw_state_routes.py`)" conflicts with decision 6. It re-implements keyed merge, partitioning and key pruning above the engine, and it costs O(S+B) per run. The routing pages index native pins. The raw provenance is the receipts and bodies in R2, which this change does not touch.
  - This is a **staged raw-index migration**: owner Q3 says repair rather than regenerate, so a differential check of old leaves against the new datasets is required.
  - The cheap interim fixes come first: batched lookups (#2) and a single `replace_stream` per save (#1).
- **WS7's delete list should add `raw_changes.py` and `manifest['change']`** (#6).
- **The keep-list item "Recovery checked_put with readback" should become a server-checksum check** (Content-MD5 or `x-amz-checksum-sha256`, with HEAD on 412 or on a lost acknowledgment), not a full GET of every written body (#4).
