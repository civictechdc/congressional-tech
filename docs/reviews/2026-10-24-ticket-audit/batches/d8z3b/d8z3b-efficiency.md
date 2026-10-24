# Batch d8z3b — efficiency pass (read-only)

Scope: the code in this batch's area that survives the simplification plan:
- the corpus-recovery raw import (`corpus_recovery/transfer.py`, `guards.py`);
- the R2Store write and read primitives this batch touched (`r2.py`, ct-lu4i);
- export-pins publishing (`publication_cli export-pins`, `ConditionalManifestPublisher`, `filename_exports.export_viewer_pins`);
- the accepted-mapping publication (`corpus_recovery/mappings.py`), which the plan moves into the export-pins flow.

Code deleted by the plan gets one line, and only where it bears on the plan.

Code read at local main c858a5a2. `git diff HEAD origin/main` shows no change to any file analysed here; origin/main adds only 54a68ac7's `raw_storage.py` edit and docs.

Measurements used the project venv (`/Users/mikewolfd/Work/congressional-tech/.venv/bin/python`) and two scratch scripts I wrote:
- **`d8z3b-count-import.py`** wraps hashlib, gzip and `Path.read_bytes` and uses the test's own counting `Store`. It runs the existing 2-body fixture `ImportTests` from `packages/corpus_recovery/tests/test_import_corpus_recovery_batch.py` and counts only inside `import_batch`; baseline adoption is excluded.
- **`d8z3b-export-measure.py`** runs the real `compute_facet_entries` and `compute_browse_ranges` on a synthetic 200k-row table and compares each against an Arrow or Parquet-footer equivalent. Both produced identical output.

Variables: B bodies per import, |b| raw body bytes, |p| stored gzip payload bytes, W writes per import (B + ⌈B/100⌉ receipts + M metadata manifests), P pinned files, N exported rows, K exported columns, G Parquet row groups, F exported files, A accepted mapping rows, H mapping publications.

---

## 1. Recovery import does every per-body check 2–3 times (measured)

Path: `transfer.py:104-137` → `checked_put` (`transfer.py:26-45`) → `R2Store.put` (`r2.py:338-397`).

Measured on the fixture (per body, new-body path):

| Operation | Count per body | Sites |
|---|---|---|
| Local body file read | 2 | `transfer.py:105-106` (pre-check `file_digest`), `transfer.py:116` (`read_bytes`) |
| sha256 over raw bytes | **3** | `transfer.py:106`, `transfer.py:117`, `raw_archive.py:225` (`body_payload`) |
| sha256 over the gzip payload | **3** | `raw_archive.py:229` (`body_payload`'s `stored_sha256`), `transfer.py:29` (journal), `transfer.py:136` (`stored_sha256` recomputed) |
| MD5 over the payload (real R2Store) | 2 (reasoned from code; the fixture Store has no MD5) | `r2.py:112` (`put_parameters` ContentMD5), `r2.py:128` (`verify_upload`) |
| Object GET | **2**: presence, then full readback (the fixture test pins this at `test_import_corpus_recovery_batch.py:106`, "Presence check and full readback") | `transfer.py:129`, `transfer.py:41` |
| gzip.decompress of the just-written payload | 1 | `transfer.py:134` |
| Metadata manifests written through `GuardedStore.put` → `checked_put` | each read back | 13 index reads for 8 index writes on the fixture |

Totals on the fixture: 63 `sha256()` calls; 19 come from `partition_routing.key_hash` and are legitimate routing.

**Big O.**
- Time O(B·(3|b| + 3|p|) hashing + B·|p| downloaded).
- Bytes downloaded per import = Σ|p|: the full payload is read back after it was already MD5-verified on upload.
- This is linear and bounded by the change, but every byte is verified 2–3 times.

**What the repeats buy.**
- The pre-check loop buys all-or-nothing refusal before the first write. That is real.
- The second raw hash buys nothing when file custody (dev, inode, size, mtime_ns, ctime_ns) is unchanged. `VerifiedFile.require` already expresses this.
- The readback after a successful PUT buys nothing beyond what R2 already did. `put_parameters` sends Content-MD5 (`r2.py:112, 122`), so R2 rejects mismatched bytes, and `verify_upload` (`r2.py:394`) checks the returned ETag. The readback is real only when the PUT outcome is uncertain (lost acknowledgment) or `put` returns False (412).

**The easy way.**
- Issue a VerifiedFile proof in the pre-check and `require()` it in the main loop (a stat, not a hash).
- Pass the known digest into `body_payload`.
- Reuse `body_payload`'s `stored_sha256` and one MD5.
- Skip the readback when `put()` returned True. Keep it for 412 and lost acknowledgment.
- For existing bodies, HEAD and compare the ETag with md5(deterministic payload) before any GET; `gzip.compress(level=1, mtime=0)` is stable for one zlib version. Fall back to GET + decompress on a mismatch.
- Target per body: raw sha256 ×1, payload sha256 ×1, MD5 ×1, GET ×0–1, no download of new bodies.

**Plan impact.** This narrows the Keep-list item "Recovery checked_put with readback". Keep readback only for uncertain or 412 outcomes, and update `test_import_corpus_recovery_batch.py:106` and `:114` deliberately.

## 2. Raw "already exists" checks need a download; store the digest at write time instead (reasoned)

Path: `r2.py:386-387`, `:157-158`, `:438-440`. WS2 step 2's verifier would compare "size and stored sha256 (or the ETag MD5)", but no raw put records a sha256 the server could return.

**Big O.** Verifying an existing raw object today costs O(|p|) bytes plus a decompress (`transfer.py:129-135`). With the digest stored on the object, it is O(1): one HEAD.

**The easy way.**
- Write `Metadata={'sha256': stored_sha256}` on every raw put. This is S3 user metadata; the publisher already does it at `publish_viewer_r2.py:508`.
- Optionally also send `ChecksumSHA256` (`x-amz-checksum-sha256`), so the server verifies and stores the checksum. R2 support for checksum headers and their HEAD return needs confirming first.
- The verifier then HEADs and compares, falling back to ETag==md5(expected payload) for legacy objects, then to a GET.

**Plan impact.** This adds a concrete mechanism to WS2 step 2.

## 3. Export-pins local path: a full-table `to_pylist()` to count four facet columns (measured)

`compute_facet_entries` (`filename_exports.py:504-546`) converts the entire sorted sources table, every column including nested `source_occurrences`, into Python dicts. It is called at `:878-881` (sources) and `:933-936` (components).

**Measured at N=200k with a 3-item occurrence list:**

| Approach | Time | Python heap peak |
|---|---|---|
| Hand-rolled | 2.20 s | 385 MB |
| Arrow `value_counts` per column | 0.64 s | 28 MB |

Output was identical.

**Big O.** O(N·K) Python objects; the hand-rolled version needs to touch only O(N·facet columns).
- A linear extrapolation to today's 1.68M rows gives about 18 s and 3.2 GB or more. Real occurrence structs are wider, so expect more. This is extrapolated, not measured at full scale.

**The easy way.**
- `pc.value_counts` (with `pc.list_flatten` for list columns) on the facet columns only.
- Better under decision 6: the engine's `facet_summary`, which the native branch already uses (`:779-782`).

**Browse ranges** (`:470-501`) decode two key columns of every row group into Python lists to get min/max, although the file was just written with `write_statistics=True` (`:850`, `:922`).
- Measured: 0.03 s hand-rolled versus 0.0006 s from footer statistics, over 49 row groups, with identical output.
- Big O: O(N) decode versus O(G) footer reads. This is minor at today's scale.

**Plan impact (WS6 step 6).** Do not spend a real-catalog timing run on the local path. It re-implements the engine's export (sort, occurrence flattening, facets, ranges). The native spec already takes `facet_columns` and `occurrence_columns` (`:234-272`). Under decision 6, delete the local branch (`:820-1000`) and keep `native.export`.

## 4. Export-pins publish hashes every file twice, then sends no checksum (reasoned)

Each exported file is:
1. written (`pq.write_table`);
2. fully read for sha256 by `file_identity` (`filename_exports.py:853, 916, 927`);
3. fully read again for sha256 by `put_immutable_asset` (`client.py:334-337`). `publication_cli.py:160-163` passes no `validation`, although the method accepts the proof (`client.py:330-332`);
4. read a third time to upload.

The digest is never sent: there is no ContentMD5 and no ChecksumSHA256 (`client.py:339-346`). The bytes on R2 are therefore unverified, and a 412 returns the local digest as if it were the stored one (`client.py:347-352`).

**Big O.** 3 full reads per file, O(F·size), plus no integrity check.

**The easy way.**
- Pass the `file_identity` proof as `validation=`.
- Send `ContentMD5` (known to be supported, as at `r2.py:122`) or `ChecksumSHA256`, and compare the ETag.
- Alternatively, revisit `storage.py:121-123`. It sets `request_checksum_calculation="when_required"`, which disables botocore's built-in single-pass CRC32 checksums on every PUT. Re-enabling them needs one R2 compatibility check (not done here: no network).

**Plan impact.** This supports WS6 steps 1–2 and makes the "verify on 412" mechanism the same one as finding 2.

## 5. Accepted mapping: each publication rewrites and rereads the whole history (reasoned)

`publish_mappings` (`mappings.py:43-120`):
1. GETs the whole `accepted.json` (`:44-51`; up to 16 MiB, `CONTROL_LIMITS`);
2. merges and re-serializes all A rows (`:59-66`);
3. PUTs the whole document with IfMatch (`:76-78`);
4. reads the whole document back again through the guarded client's own `verify()` (`client.py:162-173`), plus a HEAD in `confirm_transfer` (`client.py:103`).

**Big O.** O(A) bytes read ×2 and written ×1 for every publication of C new rows, so the cost grows with history (A is cumulative) rather than with the change. Over H publications that is O(H·A).

**The easy way.**
- Under P5, append immutable, content-addressed delta objects, or derive the mapping from import receipts' `source_associations` (`prepare_corpus_recovery_source_records.py:178`). Readers then stream O(C) per publication.
- If the single document stays, at least drop the second full read: send ContentMD5 and check the ETag.

**Plan impact.** This is input for P5 / WS6 step 5 and adds a cost argument for treating receipts as the authority.

## 6. RecoveryGuard does O(P) stats per write (reasoned, low)

`RecoveryGuard.check` → `_pins(full=False)` stats every pin on every immutable write (`guards.py:101-109`). The import pins P ≈ 230 `congress_api` files + about 9 named modules + engine files + inputs (`dispatch_corpus_recovery_import.py:107-127`).

**Big O.** O(W·P) stat calls; for example, about 1,100 writes × about 250 pins ≈ 275k stats, roughly 0.5 s. This is cheap, but it is per-item work that could be done once per phase.

**The easy way.** WS4's git tree hash plus a clean-tree refusal replaces the 250-file list. Each per-write check then becomes one `git status --porcelain` per phase, or just the existing lock and parent checks. Confirms WS4.

## 7. R2Store.put hashes each object with MD5 twice (reasoned, low)

`put_parameters` (`r2.py:112`) and `verify_upload` (`r2.py:128`) each MD5 the same bytes. This applies to every raw capture body and receipt and to every metadata manifest; `AsyncBodies.put` does the same (`r2.py:155, 160`).

**Big O.** 2·Σ|p| MD5 per run where Σ|p| would do. The fix is to compute the digest once and compare the ETag against it. Small next to the network cost; it is a do-once cleanup inside WS2 step 1.

## Adjacent (other batches' code; one line each)

- **Capture start lists every receipt each run.** `raw_archive.py:672-677` LISTs every `receipts/` object and does one delivery lookup per key. That is O(R) LIST calls and lookups per run, growing with history (R = 2,289 means about 3 LIST pages today). Listing only the current run's day prefixes, or keeping an orphan marker, would make it O(change). Reasoned, not measured.
- **Raw reads can be served unverified from a local cache.** `r2.py:273-278` returns cached `receipts/` and `bodies/` bytes with no hash check. Already covered by WS2 step 4.

## Deleted by the plan (only where it bears on the plan)

- **Preflight (WS6 step 7):** about 44 MB read per no-op poll at 48 polls a day (`hosted-qualification.json` `scheduled_cost`), plus a hand-written SigV4 signer. Confirms deleting it.
- **GuardedPublicationClient (WS6):** sha256 before each write, then a full GET and sha256 readback, with no ContentMD5 (`client.py:136-173`). If any of it survives for mappings until P5, send ContentMD5 and drop the readback.

## Plan-changing findings (summary)

1. **Keep list, "Recovery checked_put with readback":** read back only on an uncertain or 412 outcome. After a successful Content-MD5 PUT with a matching ETag, the readback is a redundant full download.
2. **WS2 step 2:** record the payload sha256 on raw objects at create time (user metadata or checksum header), so the verifier is a HEAD, not a GET.
3. **WS6 step 6:** skip the real-catalog timing. Delete the local export branch; its facet pass alone measures 385 MB of Python heap per 200k rows.
4. **WS6 steps 1–2:** export-pins must send a checksum it already computes, and must reuse the `file_identity` proof rather than rehashing.
