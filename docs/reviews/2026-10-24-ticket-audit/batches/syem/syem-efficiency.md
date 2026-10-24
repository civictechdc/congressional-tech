# syem batch: efficiency pass (complexity, repeated work, hand-rolled work)

Read-only. Code was read at origin/main 56cca36d; the three raw files changed by 54a68ac7 were read via `git show`. Measurements ran in the checkout at c858a5a2 with in-memory or tmp fixtures through the project `.venv`.

Detail lives in three part files in this directory:
- **Raw capture and custody path:** syem-eff-part-raw.md, script syem-eff-raw-measure.py.
- **docspec_client transport, news_lake DocSpec backend and the engine side:** syem-eff-part-dsc.md, script syem-eff-dsc-measure.py.
- **export-pins:** syem-eff-part-exp.md, script syem-eff-exp-measure.py.

Variables used below:
- N: capture rows (3.9M)
- S: state rows (~1.27M; 256 leaves × ~5,074)
- B: bodies (256 index leaves × ~8,098)
- C: changes per run
- H: history
- F: files
- K: columns
- P: bytes of the staged input

## Ranked by cost at today's scale

| # | Hot path | Big O (today) | Repeated or hard-way operation | Easy way | Evidence |
|---|---|---|---|---|---|
| 1 | Raw state and body index save (`raw_storage.py:1143-1253`, `_prepare_bodies:942-994`) | O(min(C,256)·leaf) per run; it grows with S+B, not C. About 1.3 GB decoded rewritten, about 512 new datasets and about 770 route PUTs per normal run. | Copy-on-write of whole leaves, merged in Python, plus 3 route pages per leaf | One dataset per kind with engine `update_table(keys, merge=STATE_MERGE_SPEC)`; the schema-evolution path already does this (`:1214`) | **Measured:** 100% of the state table rewritten at C=4,000 (fixture), 4,051 dataset writes; real leaf sizes from the routing cache |
| 2 | export-pins local path (`filename_exports.py:820-1009`) | O(N·K) Python objects: whole-table `to_pylist` in facets (`:507`) and the component sort (`:699-705`). Plus O(N log N) Python sort and an O(occurrences) Python size estimator. About 110 µs per row at K=18, before scaling to K≈400. | Re-implements docspec-rs export (fold, sort, child tables, facets, browse ranges). Re-reads row groups for min/max that the footer statistics already hold (`:470-500`). Hashes each file 2 more times after writing (`file_identity`, then `put_immutable_asset` without `validation=`). | Engine `export` (`export.rs:184-230,380-392`), which returns `ObjectRef` digests. If anything local must stay: `pc.value_counts`, `sort_by`, footer statistics, and pass `validation=`. | **Measured:** 2.20 s at 20k rows; Arrow equivalents 0.016 s and 0.027 s. Full scale is reasoned. |
| 3 | Body-index lookups per new digest (`raw_storage.py:599-608`, `raw_archive.py:584`) | O(B_new × leaf); about 2.6 MB decoded per new body | A one-leaf cache, so nearly every lookup re-reads a leaf | Group lookups by leaf; later engine `read_keys`, or R2 `HeadObject` with a stored SHA-256 checksum | **Measured:** 199 leaf reads for 200 lookups |
| 4 | Capture queue (`raw_state_routes.py:111-160`) | O(S), about 620 MB decoded per run | Reads almost every state leaf to admit up to the limit | A projected 4-column read with Arrow top-k, or one engine query with ORDER BY … LIMIT | **Measured:** 248 of 256 leaves read for limit 1,000 |
| 5 | Raw state merge (`specs.py:476-692` from `raw_storage.py:1160`) | O(leaf) Python dicts per touched leaf, about 7 µs and 490 B per row. The same partition goes through `to_pylist` 4 times, once only to get `nbytes`. | Python merge, then the engine merges again (`merge=STATE_MERGE_SPEC`, `:1221`) | Let the engine merge; delete the Python merge | **Measured** (synthetic 200k rows) |
| 6 | Engine Build input, remote (`write/build.rs:341-345`) | P up plus P down per Build, about 350 MB + 350 MB per full raw rebuild | Uploads the producer Parquet, then downloads it again | Keep the generic verified local read (`build.rs:356-372`); locally, hard-link instead of `copy_verified` | Reasoned from code; P is measured (18 MB per 200k rows) |
| 7 | Recovery import (`corpus_recovery/transfer.py:42,129`) | 2 full GETs and 6 SHA-256 passes per new body | Existence GET plus read-back GET after upload | Create-only PUT with `ChecksumSHA256`; `HeadObject(ChecksumMode=ENABLED)` on a 412 or a lost acknowledgment | Reasoned from code |
| 8 | `blake3` hashing in locked environments (`transport.py:11-125`) | About 1000× slower IPC hashing, plus a `docspec hash` subprocess per producer file | Hand-written BLAKE3 fallback. `blake3` is in no pyproject and not in `uv.lock`; it only happens to be installed in the local `.venv` (confirmed: v1.0.11). | Declare `blake3` and delete the fallback | **Measured:** 1.36 MiB/s for the fallback; dependency absence confirmed |
| 9 | news_lake views and dedup (`incremental.py:293-336`, `lake.py:266`) | O(S) re-read after each lifecycle compaction; dedup is O(n·d) | Discards the engine's exact `full` change stream; quadratic duplicate scan | Accept `full`; dedup with a dict keyed by id | **Measured** dedup: 0.035 s, 0.57 s and 2.36 s at 5.5k, 22k and 44k records; views reasoned |
| 10 | `RawChanges` | O(C/128) PUTs per save, O(H) storage (10,151 pages, 129 MB cached) | Write-only after WS7 | Delete with WS7 | Measured on the local cache |
| 11 | Publishing integrity (`viewer_publication/client.py:327-348`) | O(F) | Local SHA-256 is never sent; a 412 counts as success | Send `ChecksumSHA256` and verify with a HEAD on 412. This is the same primitive as #7 and WS2's verifier. | Reasoned; R2's HEAD checksum echo needs one live probe (not run, no network) |
| — | Leave alone | | Client Parquet staging (about 2 µs per row; IPC would be 3.9× the bytes), `ArrowResponse` (70 MB in 12-30 ms), the pointer's single conditional PUT, and the code-only clones | | Measured (dsc) |

Capture hashing (6× and 3× the content-byte work) is real but costs CPU only, so it is low priority.

## Changes to the plan
1. **Q7 (one raw dataset per kind) is answered by measurement: yes.**
   - The keep-list item "raw-side routing (`partition_routing.py`, `raw_state_routes.py`)" conflicts with decision 6, and it costs O(S+B) per run.
   - This is a staged migration with a differential check of old leaves against the new datasets (owner Q3: repair, don't regenerate).
   - Interim: batch lookups by leaf (#3) and project the queue read (#4).
2. **WS3 / WS7:** move the raw state merge onto the engine and delete `specs.py:476-692`. Declare `blake3` and delete `transport.py:17-125`.
3. **WS6 step 6 is settled by decision 6 without the timing exercise.**
   - Keep the native export and delete the local export path. That is about 400 lines in `filename_exports.py`, plus `filename_budget.py` with the v6 preparer.
   - First add a native-against-local parity test.
   - Also: export-pins in native mode uploads no data files today, so publishing must take the engine's `ObjectRef` objects (server-side copy or reference).
4. **WS2 step 2 and WS6 step 2, the "one verifier":** implement it with `x-amz-checksum-sha256` on every create-only PUT plus a HEAD on 412. Do not download the object for a byte comparison.
   - The keep-list item "recovery `checked_put` with readback" becomes this server-checksum check.
5. **WS1:** keep `docspec-rs write/build.rs:356-372` (the generic verified local read) instead of deleting it.
6. **WS7:** add `raw_changes.py` and `manifest['change']` to the delete list.
7. **WS8:** accept `full` in the views and fix `_dedup_incoming`.
8. **WS9 (optional):** hard-link verified producer inputs.

**Unchecked:** state leaves are partitioned on `state_key_sha256`, a column absent from `state_native_schema` (`raw_storage.py:805`, from the raw pass). It needs a check against the real engine.
