# docspec-rs efficiency audit: complexity, repeated work, hand-rolled work

Read-only review at `d9c6719`. Paths are relative to `/Users/mikewolfd/Work/spicy-stack/docspec-rs` unless prefixed `ct:` (congressional-tech).

**Binding context.**
- Decision 6: the engine takes over incremental catalog updates (WS7).
- Decision 1: durable per-phase commits stay. The post-`c949c67` deferral and the production-only forks are reverted (WS1).

**Measurement status.** I ran no cargo commands, so every finding below is **reasoned, not measured** unless it cites a retained receipt or crate source.
- `docspec-rs/target/` was deleted between my first pass and this one, so any test run would need a from-scratch debug build of DataFusion, Arrow and Iceberg. That is not "cheap".
- A separate large cargo build (formspec-stack) is running on the machine.
- Retained receipts used as evidence:
  - `ct:output/news-poll-scale-20261021/{id-1080.csv,time-id-1080.csv,after-time-id-1080.csv,summary.md}`
  - `iceberg_optimization_report.md`
  - the ss-lcbc and ss-1txq ticket measurements
  - the iceberg-0.10.1 crate source in `~/.cargo/registry`
- The ready-made harness for the most important claim is `src/engine/profile_tests.rs:262-494` (`profile_lifecycle_compaction_and_warm_commit_scaling`: warm commit latency, cold open and revisions at 0/8/32/250 ops). Run it when a build exists: `cargo test --locked --all-features --lib engine::profile_tests::profile_lifecycle_compaction_and_warm_commit_scaling -- --ignored --nocapture`.

**Variables.**

| Symbol | Meaning |
|---|---|
| R | rows in a table |
| F | live data files in a table (per group) |
| F_a | data files touched by an Update |
| P | partitions |
| C | changed rows |
| H | lifecycle history (commits and snapshots since the last lifecycle compaction) |
| L | live lifecycle records in a dataset |
| D | datasets in the workspace |
| K | protection records |
| S | input bytes |
| O | output bytes |
| RTT | one R2 round trip |

## 1. Big O per hot path

### Build (remote, the pinned path that decision 1 restores)

**Time and I/O:**
- Admission: the producer hashes S (`docspec hash`), then the engine uploads S, hashing during the upload (`src/storage/remote/objects.rs:555-600`).
- In the pinned and test builds, the engine then GETs and re-hashes S to verify the upload (`src/storage/object_io.rs:258-262`).
- Processing GETs and decodes S again from R2 (`src/engine/write/build.rs:376-385`, non-local branch).
- It writes O as source plus occurrences (inputs are aliased for identity SQL).
- Pinning GETs and hashes every new object in full, sequentially (data, manifest, manifest list, metadata) (`src/storage/pinned.rs:312-321`; pinned revision `c949c67:src/storage.rs:2000-2008` → `remote/objects.rs:734-747,853-880`).
- **Totals: upload S once, download S twice, upload O once, download O once, hash S three times and O once.**
- Catalog work: about 11 lifecycle commits per operation. ss-lcbc measured 22 revisions for 2 operations, and each commit is about 4 objects plus one REST commit (see the Catalog section). On top of that come 2–3 native table registrations and appends.

**Memory:** bounded by batch admission. Fine.

**Flag:** decoding S again from R2, and hashing O by re-downloading it, are repeated work that the post-pin forks hid instead of fixing.

### Update / merge (`replace_keys_with_merge`, `src/engine/write.rs:597-893`)

- **Pruning:** a manifest walk over F per Update, then a key-point test per file (`src/engine/key_pruning.rs`). That is O(F log C) metadata work.
- **Key probing:**
  - With hash-distributed keys every file is a candidate, so each Update decodes the key column of all R rows: O(R).
  - **Measured:** with `id` keys, `files_scanned` = F at every poll, and p50 wall time rose from 670 ms (60 polls) to 1,098 ms (720) to 1,097 ms (1,079 polls) (`ct:…/id-1080.csv`). With time-clustered keys it is 0 files.
- **Rewrite:** copy-on-write decodes and rewrites every touched file in full: O(rows in F_a).
  - When C changed keys are spread randomly, F_a ≈ F as soon as C ≳ F. Each Update then rewrites the **whole table**, O(R), whatever C is.
  - Reasoned, not measured. This is the dominant cost for WS7's keyed catalog updates over 1.68M filename rows and 3.9M capture rows.
- **Merge:**
  - Prior rows are decoded from the base files, written to a `removed` table, then read back and decoded again for the merge (`write.rs:771-789` → `merge.rs:221-260`).
  - The merge holds all prior rows and a key-bytes BTreeMap in an arena. That is O(C) memory, bounded by refusal.
- **New tables per Update:** three brand-new Iceberg tables (candidate, removed, added) per group (`write.rs:711-719`).
  - The candidate's single `fast_append` lists **all** F files in a fresh manifest (`write.rs:874`).
  - The resulting `TablePin.objects` (a `Vec<ObjectRef>` of every file) is copied into the authority, result, readback and phase records and into `release.json`.
  - So every Update writes O(F) metadata bytes, independent of C. **Measured:** about 5.8 KiB of lifecycle bytes per live file; 4.21 MiB at 720 polls, 6.28 MiB at 1,079 (ss-7hrv/ss-1txq receipts).
- **Verification per Update (remote):**
  - Pinning HEADs every inherited file one at a time (`pinned.rs:314-316`; `c949c67:src/storage.rs:2003`).
  - `inspect_table` HEADs every pinned object again (`src/storage/inspection.rs:154-156`, sequential via `src/storage.rs:286-316`) and walks the manifests again (`inspection.rs:179-180`).
  - `trust(base)` walks the base manifests (`src/engine/verification.rs:193-230`).
  - **Total: about 2F sequential HEADs (each an RTT) plus 3 manifest walks per table per Update. This grows with F, not C.**

### Export (`src/engine/export/pipeline*.rs`)

- **Time:** read and join groups, then a DataFusion sort: O(R log R) with spill.
- **Facets:** a `BTreeMap<String, Option<String>>` key per row per grouping set (`src/engine/export/pipeline/facets.rs:197-232`). That is O(R × sets × columns) allocations plus value stringification.
- **Browse ranges:** stringified min/max per batch (`facets.rs:36-80`).
- **I/O:**
  - The file is written locally, then uploaded with hashing during the upload.
  - In the pinned and test builds it is then fully re-downloaded for verification (`object_io.rs:258-262`).
  - Child tables are a second writer pass over the unnested lists.
- **Footers:** footer accounting appears in three places (mi03a H7, carried in the plan's WS9 "opt.").

### Compaction

- **Table compaction (`Engine::compact`, tail coalescing `src/engine/write/compaction.rs`):** about O(small files) per trigger. Fine. It is bounded by thresholds; the 1,079-poll receipt shows ≤49 files.
- **`compact_lifecycle` (`src/engine/retention/compaction.rs:125-230`):**
  - `rows_for_compaction` reads O(H).
  - `collect_record_paths` parses every live record's JSON: O(L × record size).
  - `prune_obsolete_protections` does O(K × kept-paths) substring matching (`:699-760`), which is **quadratic**.
  - The head walk is O(F).
  - The succession archive is read in full and rewritten in full: O(history) per compaction (`:474`).
  - Local reclaim runs `live_retained_closure`, which scans **every namespace in the workspace**: O(D × L) (`src/engine/retention/inventory.rs:196-232`).
  - The directory sweep checks each file against every protected prefix: O(files × prefixes) (`compaction.rs:781-837`).

### Remote object I/O

| Operation | Behavior | Where | Cost |
|---|---|---|---|
| `check_objects` | Sequential, one HEAD per object, in a blocking worker | `src/storage.rs:286-316` | O(F) × RTT |
| `pin_bound` (pinned) | Sequential HEAD or full GET per object | `c949c67:src/storage.rs:2000-2008` | as above |
| `pin_bound` (post-pin) | Unbounded `try_join_all` fan-out | `pinned.rs:264-310` | no concurrency bound; 429 risk at large F |
| Retry on 429 | Hand-rolled, 10 × attempt seconds, 8 attempts | `storage.rs:880-925` | up to ~6 minutes stalled per commit |
| File size target | Remote target capped at **2 MiB** (`b4b827d`, no reason recorded) | `src/storage.rs:376-380` | about 32× more files than the 64 MiB default; multiplies every O(F) term above and the 141k-object count |

### Catalog commits (lifecycle store, `src/catalog.rs:647-915`)

- **Per commit:**
  - The whole live map is cloned: `previous.values.clone()`, O(L) (`catalog.rs:715`).
  - A `fast_append` writes one tiny Parquet file, one manifest, a manifest list that re-lists every manifest since the last compaction (O(H)), and a `metadata.json` whose snapshot log grows with H (O(H)).
  - **So each commit writes O(H) bytes, and the run between compactions writes O(H²) bytes.**
- **Per operation:** about 11 commits (measured, ss-lcbc), so about 44 objects and 11 REST round trips.
- **Cold open:** `rows_inner` reads every lifecycle data file, O(H) GETs (`catalog.rs:534-600`).
- **Bound:** only baseline compaction bounds H.
  - The consumer runs `compact_lifecycle` **only when local** (`ct:…/native_capacity.py:379`).
  - So on R2, every long-lived dataset grows H without bound. WS7's catalog datasets are exactly the long-lived kind: about 11 more commits per Update, forever.
- **Cache:** the dataset-keyed `SnapshotRows` cache never evicts (`catalog.rs:73-76,289,310,529`). Memory is O(D × L) with one budget permit.

### Verification (routine)

- `checks.table`: HEAD all objects, open metadata, walk manifests, read a footer for each new file, take a small sample (`inspection.rs:143-325`).
- Release availability HEADs `release_objects` again (`src/engine/release_check.rs:161`).
- Footers are cached only within one `Checks` instance (`verification.rs:141-230`). Across operations, `trust(base)` rebuilds the cache by walking the base manifests again.

## 2. Do once: repeated work on the same path

| # | Repeat | Where | Buys anything? | One-pass replacement |
|---|---|---|---|---|
| D1 | Uploaded objects (admitted inputs, exports) are re-downloaded and re-hashed | `object_io.rs:258-262` (pinned/test) | Detects R2 storage corruption. That can be done server-side. | Send a checksum with the PUT (Content-MD5 or `x-amz-checksum-sha256`; reasoned, confirm R2 support) or compare the single-part ETag. Keep the BLAKE3 computed during the upload. |
| D2 | Every newly written data, manifest and metadata file is fully re-downloaded to compute its identity | `pinned.rs:312-321` → `remote/objects.rs:734-747,853-880` | No. The engine just wrote those bytes. | Hash while writing: wrap the `FileIO` output writer. The post-pin "fix" substitutes `blake3("{path}:{bytes}")` (`pinned.rs:~285-296`, `remote/objects.rs:763`), which is not a content digest. WS1 removes it, so the hash-at-write fix must land with the revert. |
| D3 | Processing re-reads the admitted input from R2 | `write/build.rs:376-385` | No, when the local source is still present (it always is during admission). | Tee during admission: upload, hash and decode in one stream. This is the honest version of the deleted name-based fast path. |
| D4 | HEAD of every *inherited* immutable file on every pin, then again in `inspect_table`, then again in release availability | `pinned.rs:314-316`; `inspection.rs:154-156`; `release_check.rs:161` | Nothing new for objects already verified by the base release. AGENTS.md says "check newly transferred objects without repeating completed checks on existing objects." | Skip inherited files. If an availability check is required, one paginated LIST of the prefix (1,000 keys per request) replaces F HEADs. |
| D5 | The new table's manifest list and manifests are read by `pin_bound`, then read again by `inspect_table`. Base manifests are re-walked by `trust(base)` every operation. | `pinned.rs:220-228`; `inspection.rs:179-180`; `verification.rs:193-230` | Validating the written metadata once is required; doing it twice is not. | Return the inventory from the pin step to the check step. Persist `CheckedFile` facts with the release instead of re-walking the base. |
| D6 | Prior rows are decoded, written to the `removed` table, then read and decoded again for the merge | `write.rs:771-789` | The `removed` table is needed (it is the change record); re-reading it is not | Tee the removed stream into the merge index in the same pass. |
| D7 | Affected files' key columns are decoded twice (probe, then full rewrite) | `write.rs:681-726` (documented in `files_scanned`) | Yes: it keeps pruning cheap for the files that are not rewritten | Keep. |
| D8 | Admission hashes S up to three times (client, upload, verify GET), and in the post-pin build `initial_source` hashes the local file once more (`build.rs:362-372`) | as cited | The client hash (request fingerprint) and the upload hash (identity) earn their keep; the rest do not | Drop the verify GET (D1) and the post-pin rehash (WS1). |
| D9 | Each lifecycle commit clones the whole live map | `catalog.rs:715` | No | Use a persistent or shared map (`im`-style), or apply changes against an `Arc` base. Also, fewer commits per operation means fewer clones. |

## 3. The easy way: maintained primitives versus hand-rolled code

| Hand-rolled | Primitive | Status / caveat |
|---|---|---|
| Copy-on-write row replacement (`replace_keys`) | Iceberg v2 merge-on-read (equality or position delete files) | **Not available end-to-end in iceberg-0.10.1.** The reader applies deletes (`iceberg-0.10.1/src/arrow/delete_filter.rs`) and an `equality_delete_writer.rs` exists, but the only commit action is `fast_append`, which refuses non-data files (`src/transaction/snapshot.rs:143-146`). There is no overwrite or row-delta action. Until upstream adds one, the cheap lever is **layout** (bucket partitions plus file-size targets, so a change set touches fewer and smaller files) plus a measured decision in WS7 step 2. |
| Table-per-release versioning (`replacement_metadata_at`, `src/storage/tables.rs:309-350`; three fresh tables per Update) plus `Vec<ObjectRef>` pins copied into lifecycle records | Iceberg snapshots on one table per group, with tags or branches as pins | **Partly forced by the same gap:** with no overwrite action, replacing files means building a fresh table. The O(F) *copies* are not forced. Store `(metadata location, snapshot id)` in lifecycle records and `release.json` instead of the object list; Iceberg manifests already carry each file's path, size and record count. Content digests of derived files are optional under the greenfield lens. |
| Per-file key pruning (`key_pruning.rs`, 916 LOC) | `table.scan().with_filter(...)` using Iceberg's `InclusiveMetricsEvaluator`, plus DataFusion row-group and page-index pruning | **Justified, measured from source:** iceberg-0.10.1 stops pruning IN-lists above 200 literals (`src/expr/visitors/inclusive_metrics_evaluator.rs:25,435`; `row_group_metrics_evaluator.rs:38`). An Update has about 2,000 keys. **Keep.** |
| Availability checks: one HEAD per object | S3 ListObjectsV2 (sizes and ETags, 1,000 per page) via OpenDAL lister | Replace when a check is required (D4). |
| Integrity: re-download and re-hash | PUT checksum headers (Content-MD5 or `x-amz-checksum-*`) or a hash computed while writing | D1/D2. |
| 429 retry loop (`storage.rs:880-925`) | OpenDAL `RetryLayer`, or the REST client's retry with jitter | Minor. |
| Facets: per-row maps (`facets.rs`) | DataFusion `GROUPING SETS` (one vectorized aggregate) | Replace when exports next change; O(R) allocations become a hash aggregate. |
| Year/Month/Day calendar math (`src/storage/partitioning.rs:94-169,335-360`) | `iceberg::transform::create_transform_function` (already used for Bucket at `:289`) | WS9 step 9. |
| SHA-256 (`connected_components/sha256.rs`) | `sha2` crate (already in `Cargo.lock`) | WS9 step 8. No performance effect (tiny inputs). |
| `cli_args.rs` argv rewriter | clap positional args | WS9 step 7. No performance effect. |
| Unbounded `SnapshotRows` cache | A bounded LRU (e.g. the `moka`/`lru` crate) charged per entry | ss-sgmp. |
| Lifecycle key-value store as an Iceberg table, one snapshot per record batch | Within the AGENTS.md Iceberg-only rule: fewer commits per operation (batch a phase's records), Iceberg snapshot-summary properties on the data-table commit, and **remote lifecycle compaction** | AGENTS.md forbids an object-store "latest" pointer, so ETag CAS is not an option. Measure commits per operation before redesigning. |
| SourceFence leases | Catalog commit requirements (the optimistic CAS already used) | Already uses the catalog's CAS. Keep. |

## 4. Ranked findings at congressional-tech scale

Scale: 1.68M filename rows, 3.9M capture rows, 141k native manifest objects.

1. **Copy-on-write rewrites the whole table when keys are hash-distributed.**
   - Big O: an Update costs O(R) decode plus O(R) write once C ≳ F, plus an O(R) key-column probe every time.
   - Evidence: measured probe growth (`id-1080.csv`: `files_scanned` = F, p50 670 → 1,098 ms); the rewrite growth is reasoned.
   - Easy way: none in iceberg-0.10.1 (no row-delta action). Use layout (bucket partitions, file targets) and **measure in the WS7 step 2 prototype** before committing to engine-native daily catalog updates.
2. **Per-operation O(F) object re-verification and re-download on R2 (D1–D5).**
   - Cost: about 2F sequential HEAD round trips plus 3 manifest walks per table per operation, plus re-downloading every written byte and every admitted input.
   - Evidence: reasoned from code. Indirect evidence: `b4b827d` ("perf(remote)") removed these paths only in production builds, using fake digests.
   - Easy way: hash at write, PUT checksums, no HEAD for inherited files (or one LIST), tee the admission input.
   - **This must land with WS1's revert, or the revert restores the repeats.**
3. **Per-operation O(F) metadata copies.**
   - What: three fresh tables per Update with all-file manifests, and `Vec<ObjectRef>` in about 4 lifecycle records plus `release.json`.
   - Evidence: measured at about 5.8 KiB per file per operation (lifecycle bytes in the receipts).
   - Easy way: reference Iceberg snapshots instead of copying inventories.
4. **The lifecycle store grows O(H) per commit, and is never compacted on R2.**
   - Big O: O(H²) bytes between compactions, O(H) GETs on cold open, a whole-map clone per commit, about 11 commits per operation (measured).
   - Easy way: enable remote `compact_lifecycle` (the engine supports it; the consumer gates it at `native_capacity.py:379`) and batch phase records into fewer commits. Measure with `profile_tests.rs:262`.
5. **The 2 MiB remote file cap** (`storage.rs:376-380`, `b4b827d`, unmeasured) multiplies findings 1–4 by about 32×.
   - Easy way: revert with WS1, or set a measured target.
6. **`compact_lifecycle` is superlinear.**
   - What: O(D × L) whole-workspace inventory (local reclaim path), O(K × paths) protection matching, an O(history) archive rewrite.
   - Easy way: WS9 deletes the archive; typed references (WS9 step 3) replace the substring matching; scope the inventory to the dataset.
7. **The merge decodes prior rows twice (D6), and export facets allocate per row.**
   - Easy way: a tee for the merge; DataFusion GROUPING SETS for facets.
8. **Unbounded `try_join_all` fan-out in post-pin pinning; the unbounded cache.**
   - Easy way: these disappear with WS1, plus a bounded LRU.

## 5. Must fix before the engine takes on incremental catalog updates (WS7)

- **Finding 2** (do-once identities and availability), bundled into WS1's revert. Without it, decision 1 brings back 2× download and O(F) HEADs on every operation.
- **Finding 4** (lifecycle growth on R2): enable remote lifecycle compaction and cut commits per operation. WS7's catalog datasets are long-lived, so H grows by about 11 per Update.
- **Finding 5** (the 2 MiB cap).
- **Finding 1, measured, not assumed:** WS7 step 2 must record bytes rewritten per Update and `files_scanned` against C for the documents table. If the rewrite is O(R) per day, choose bucket layout and file targets before promoting the incremental path.
- **Finding 3** can follow, but plan it: as long as pins copy every file reference, catalog-scale F makes every Update's metadata O(F).
- **Keep as is:** key pruning (justified by Iceberg's 200-literal IN limit), tail coalescing, and the vectorized merge core.
