# Batch czsd: efficiency audit (fourth pass)

Read-only. I reviewed code at congressional-tech `main` `c858a5a2`. Commit `54a68ac7` (stored_sha256,
engine pin, delete_gzip) sits on `fix/raw-data-lockdown` and is not on main; I treat those three
items as fixed. Plan read: `simplification-plan-20261024.md`. Scope is my area's surviving paths: raw
capture and custody, the docspec_client transport as the raw path uses it, and export-pins
publishing. news_lake and the engine internals belong to other batches, and I did not review them
beyond the raw leaf layout.

**Measurements.** All are scripts in this directory, run with the project venv. Inputs are read-only:
the retained Oct 20 adoption inputs and the memory-native test fixtures.

| Script | What it found |
|---|---|
| `czsd-raw-sizes.py` | **S = 1,298,420** state rows (368 decoded bytes per row, 478 MB decoded). **B = 1,036,256** distinct bodies, so the body index has about **2.07M** rows (a `body:` key and a `sha:` key per body). N = 3,909,134 capture rows. |
| `czsd-daily-changes.py` | Recent daily runs added **C = 259 to 3,520** distinct bodies (Oct 13–16). |
| `czsd-body-bytes.py` | Bodies total 763 GB raw and 696 GB stored; the mean stored body is 672 KB. For the 260,834 PDFs, gzip saves only 9.5% (403.2 GB raw against 364.7 GB gzipped). |
| `czsd-leaf-amplification.py` | Leaf rewrites per state update follow L·(1−(1−1/L)^C). With L = 256: C = 50 touched 45 leaves (46 expected) and C = 200 touched 141 (139 expected). Each touched leaf meant 1 native read, 1 new native dataset and about 3 routing-page writes. |
| `czsd-body-lookups.py` | Each new body costs 1 native body-leaf read for the "already known?" lookup, then the same leaves are read again at save (C = 100: 100 lookup reads plus 195 save-time reads). |
| `czsd-roundtrip.py` | The Arrow → Python → Arrow round trip in `_read_table` costs only **6.4 ms per 5,071-row leaf**, so it is *not* a cost driver (downgraded). |

**Production leaf count L (derived from code, not counted on R2).** `split_partition` divides a leaf
16 ways whenever it exceeds `max_state_rows` = 16,384 (`partition_routing.py:28-58`;
`raw_storage.py:785`). The state table (S = 1.30M) therefore lands on about 256 leaves of about 5.1k
rows. The body index (2.07M rows) lands on about 256 leaves of about 8.1k rows.

## Findings, ranked by cost at today's scale

### 1. The raw index rewrites most of itself every day: O(S + B) per run, not O(C)
- **Where:**
  - `raw_storage.py:1146-1269` (state leaves). Each touched leaf is read whole, every row is merged
    in Python (`_merge_states`, `:1160-1166`), the whole leaf is re-serialized, and it is written as
    a brand-new native dataset (`_candidate`, `:1058-1075`, with a new dataset identity per operation
    and leaf).
  - `raw_storage.py:943-997` (body leaves): the same pattern.
- **Big O per run:**
  - Native leaf reads and Runs: min(C, L_s) + min(2C, L_b).
  - Rows rewritten: about (touched/L)·(S + 2B).
  - Routing-page writes: about 3 per touched leaf.
- **At today's C (259–3,520):** each run touches 64% to 100% of the 256 state leaves and almost all
  256 body leaves. That means it rewrites roughly 0.8M to 3.4M rows and creates roughly 300 to 512 new
  datasets. The curve is measured on a fixture; S, B and C are measured from the retained tables.
- **Growth with history:** removal is never executed (`native_capacity.py:543-560` only *plans*
  removals). So each run leaves another near-full copy of the raw index under
  `__r2_data_catalog/`, and the catalog gains up to about 2L tables per run. Storage is O(H·(S + B))
  and the table count is O(H·L). Reasoned, not measured on R2.
- **Hard-way operations:**
  - Hash-prefix routing pages (`partition_routing.py`, `raw_state_routes.py`, the body routes)
    hand-roll a keyed index.
  - `_merge_states`/`apply_update_merge_spec` (`raw_storage.py:411-536`,
    `docspec_client/specs.py:554`) re-implements the engine's `UpdateMergeSpec` in Python. The engine
    merge is used only on `schema_evolved` leaves (`:1203-1225`).
- **Easy way:**
  - The receipts already are the append-only log. Every one of the 3,909,134 capture rows carries a
    `receipt_key`, and each receipt line has `download_state`. So the capture, state and body tables
    are derived.
  - Keep receipts plus bodies as the only per-run raw writes, which is O(C).
  - Maintain the state and capture tables as engine datasets: append plus engine keyed merge, or a
    nightly rebuild from receipts.
  - Note: copy-on-write over hash buckets would still rewrite every bucket. The O(C) shape needs an
    append-only log with a latest-per-URL view, or merge-on-read. Under decision 6 that is an engine
    primitive.
  - Then delete the app routing for state and bodies, and the Python merge.

### 2. "Is this body already known?" costs a whole leaf read per captured body
- **Where:**
  - Every captured body checks `digest in archive.body_info` (`acquisition/raw_sync.py:443`;
    `raw_archive.py:376`).
  - That calls `RawSnapshot.body_info` (`raw_storage.py:600-609`): a route lookup plus a native read
    of the whole body leaf. The leaf cache holds a single leaf, so random digests miss almost every
    time.
  - `_prepare_bodies` then re-reads the affected leaves (`:977`) without reusing those reads.
- **Big O:** about C + min(2C, L_b) native leaf reads per run. At C = 3,520 that is about 3,800
  reads × 8.1k rows ≈ 31M rows decoded, about **15× the whole body index** for one day.
  Measured: 1 read per lookup.
- **Easy way:**
  - The R2 key `bodies/sha256/<d>.gz` is content-addressed, so the object itself answers "retained?".
  - Use HEAD, or the conditional PUT that already exists (`r2.py:150-161`, `IfNoneMatch`), plus an
    in-run set.
  - If metadata is needed, upload with `ChecksumSHA256`; then HEAD with ChecksumMode returns the
    stored digest.
  - Short of deleting the index: batch lookups by leaf, the way `states_for` already does
    (`raw_storage.py:633-645`).

### 3. Recovery import downloads every new body twice and hashes it six times
- **Where, per body in `corpus_recovery/transfer.py`:**
  - Local file read and sha256 (`:108-112`), then read and sha256 again (`:116-118`).
  - Full GET as an existence check (`:128`).
  - `body_payload`: sha256 of the raw bytes, gzip, sha256 of the gzip (`raw_archive.py:225-229`).
  - `R2Store.put`: MD5 plus the ETag check (`r2.py:112,386-397`).
  - **Full GET read-back** (`checked_put`, `:43`), even though the ETag already verified those exact
    bytes.
  - gzip decompress (`:132`), then sha256 of the remote copy (`:134`) instead of the
    `stored_sha256` computed above.
- **The test pins the double read:** `test_import_corpus_recovery_batch.py:106,205` asserts
  `store.reads.count(key) == 2` ("Presence check and full readback"). That is the measured count.
- **Big O:** 2 local reads, 2 remote GETs, 1 PUT and 6 hashes per new body; 1 GET per existing body.
  At the 672 KB mean, that is about 1.3 MB of extra download per new body. Reasoned: about 17 GB if
  the 12,431 accepted-only recoveries were re-imported.
- **Easy way:**
  - PUT with `IfNoneMatch` plus `ChecksumSHA256`, reusing the already-computed `stored_sha256`.
  - Drop the existence GET and the read-back.
  - On a 412, HEAD and compare length and checksum. The existing prior-readback path already does
    HEAD-only reuse (`:120-127`; test `test_prior_body_identity_reuses_head_without_get_or_gzip`).

### 4. Export-pins publishing re-hashes files and skips a file the manifest names (survives WS6)
- **Re-hashing:** the export already computes each file's sha256
  (`filename_exports.py:842,861,904,927`) and puts it in the manifest. Publishing hashes every file
  again (`client.py:330-332`, because `validation=None` at `publication_cli.py:162-165`). It then
  uploads with **no integrity header**, never compares the ETag, and treats 412 as success.
- **Correctness gap:** the upload list is hand-written as `sources`, `components` and `occurrences`
  (`publication_cli.py:162`). It omits `document_occurrences.parquet`, which the manifest references
  as a child table (`filename_exports.py:895-910`). The plan already notes the missing
  `manifest.json`; this file is a second missing object.
- **Easy way:**
  - Upload from the manifest's own file list.
  - Pass the manifest digest as `ChecksumSHA256`, so the file is hashed once and verified by the
    server.
  - Key each object by its own digest, as `filename_native.py:24-35` already does. Then a 412 means
    identical bytes by construction, and WS2's byte-compare verifier is unnecessary for release
    assets.
  - `compute_browse_ranges` already uses Parquet footer statistics (`:470-490`). That is already the
    easy way; keep it.

### 5. Smaller repeats (low cost today; listed for completeness)

| Path | Big O and repeated work | Easy way | Evidence |
|---|---|---|---|
| Raw selector publish (`raw_storage.py:1290-1296`) | Pre-read, then CAS put, then read-back: 2 extra GETs of a ≤ `SELECTOR_BYTES` object per save | The If-Match CAS plus the MD5-checked ETag already prove it; keep one read only for lost-ack reconciliation | Reasoned |
| Archive startup (`raw_archive.py:670-677`) | O(R) LIST calls plus O(R) delivery lookups per run; R = 2,289 means 3 LIST pages | Keep it (it is the orphan-receipt safety net). Bound it by the `receipts/<family>/<day>/` prefix after the selection's last day if R grows | Reasoned |
| Scheduling (`raw_archive.py:724,727`) | `scheduled_states` runs twice with the same options, re-reading the due leaves, and recomputes `summarize` on every leaf read (`raw_state_routes.py:157-158`) | One pass that yields refusals and the queue | Reasoned |
| Capture body hashing (`raw_archive.py:225-229`, `r2.py:112`) | sha256(raw) + sha256(gz) + MD5(gz) per body | Replace MD5 with `ChecksumSHA256` = `stored_sha256` (check R2 support) | Reasoned |
| Streamed bodies (`body_files.py:105-157`) | Production (no exclusions or PDF siblings; `cli/raw_sync.py:320-325`): an MD5 pass, an upload pass and a sha256 pass over the scratch file after the gzip pass. With exclusions on, `read_bytes()` loads the whole file into memory twice (`:131-137`, `r2.py:415-418`) although the gate needs only the digest | Hash the gzip stream while writing it; read bytes only when a digest is actually excluded | Reasoned |
| docspec_client `hash_input` (`client.py:411-412`) | Reads the whole input into memory for BLAKE3 (O(F) memory). The engine then re-hashes it for custody, which is worth keeping | Stream with BLAKE3 `update` | Reasoned |
| PDF siblings | `.pdf` copies double PDF storage for a 9.5% saving (measured). Production capture writes none (the flag is off); only `backfill_uncompressed_pdfs` does | Q2: one object per body. For inline serving, write new `.gz` with `Content-Type: application/pdf` and `Content-Encoding: gzip` instead of a second copy | Measured ratio; serving behavior reasoned |
| `_read_table` Python round trip (`raw_storage.py:922`) | 6.4 ms per leaf | **Leave alone** | Measured |

## Findings that change the plan

1. **WS7 step 6 keeps `partition_routing.py` and the raw-side routing pages "as raw provenance".**
   They index *derived* capture, state and body tables: every capture row points to one of the
   2,289 receipts. They also drive finding 1's O(S + B) daily rewrite. **Change:** after Step 0 Run A
   confirms that receipts reproduce capture and state, put the raw index on the engine (or a nightly
   rebuild) and delete the state and body routing and the Python `UpdateMergeSpec`. Keep only receipts
   and bodies as raw writes.
2. **Step 0 should also baseline today's "incremental" raw update.** Count native Runs and rewritten
   rows per save on one real day's change set. Today it is O(S + B), so WS7's engine-native update
   must beat that, not O(C).
3. **WS2 step 2's verifier for content-addressed keys** should use platform checksums
   (`ChecksumSHA256` on PUT, HEAD with ChecksumMode on 412), not GET plus decompress. The recovery
   tests that pin 2 reads (`test_import_corpus_recovery_batch.py:106,205`) must change deliberately.
4. **WS6 finish:** upload from the manifest's file list (adding `document_occurrences.parquet`),
   send the existing digests as checksums, and drop the re-hash.
