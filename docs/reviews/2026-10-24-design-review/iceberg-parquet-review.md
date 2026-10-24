# Engine-first architecture: Iceberg, Parquet and query-plan review

Reviewed: `docs/engine-first-architecture.md` (uncommitted, worktree `wt/ct-ticket-audit` at `ce1ff7ef`),
against docspec-rs `d9c6719` (iceberg 0.10.1, DataFusion 53.1.0, parquet/arrow 58.4.0,
object_store 0.13.2) and hyparquet 1.31.2 / hyparquet-compressors 1.1.2 (the versions pinned in
`apps/site/package.json:20-21`). Skills applied: `iceberg`, `iceberg-optimizer`,
`parquet-optimization`, `explain-plan`. Date: 2026-10-24.

**How evidence was gathered.** Code was read in place. Measurements used DuckDB 1.5.5 from the
project venv `wt/ct-viewer-publish/.venv` (4 threads, 4–6 GB cap, `nice`), over the Oct 19 adoption
inputs in `congressional-tech/output/incremental-updates-20261019/adoption-inputs/`. These were read
only; no checkout code, venv or git state was touched. Scratch outputs went to this session's
scratchpad and were deleted. **No DataFusion `EXPLAIN` was run.** No DataFusion binary exists
without a from-scratch docspec-rs build: `target/` is gone, and the machine sat at load average
about 17. A `datafusion-cli` from `PATH` is ruled out by the brief. DataFusion plans below are
sketched from the engine's code. DuckDB numbers are a proxy for data volume, not a forecast of
docspec-rs time, and the load inflates them.

## Verdict

The direction is right: append-only raw log, readings once per body and parser version, SQL
recompute, content-addressed publish, one If-Match flip. Two parts do not work as written:

- the "replace table" commit, which iceberg-rust 0.10.1 cannot express safely on a REST catalog;
- the claim that the data is small, which is true by row count and false by bytes.

The current model tables carry about 400 mostly-empty columns, and the explorer cannot use most
of the Parquet features the doc lists. The cheapest fix also removes engine work: keep Iceberg
for the two append-only tables, and make the model and export one step whose durable output is
content-addressed Parquet plus a manifest.

## How small the derived files can be (measured)

The owner's instinct is right: the derived files do not need to be this large. Today's model
tables, the Oct 18 catalog generation:

| File | Rows | Leaf columns | Row groups | Footer | Compressed / uncompressed |
|---|---:|---:|---:|---:|---|
| `filenames.parquet` | 1,683,430 | 406 | 1,644 × 1,024 rows | **81.3 MB** | 465 MB / 1.92 GB |
| `documents.parquet` | 1,241,157 | 409 | 1,213 × 1,024 rows | **62.2 MB** | 479 MB / 1.92 GB |
| `captures.parquet` (legacy) | 3,909,134 | 20 | 4 × 1,048,576 rows | 15 KB | 283 MB / ~1.17 GB |

Where the bytes go:

1. **Hundreds of sparse reading columns.** Each possible filename reading is its own
   `list<string>` column (337 of them). In a sample of 120, the median is non-null in **550 of
   1.68M rows**. 373 of 406 leaf columns hold under 2 MB each, yet every column costs a
   column-chunk entry in every row group's footer. That is why the footers are 62–81 MB.
   Stored long, there are 39.6M non-null reading cells, about 23.5 per filename row.
2. **Random 64-character hex hashes, repeated.** `source_id`, `document_id`, `body_key`,
   `state_body_key` and `body_keys` are the five largest columns in both files. `body_key` is
   derivable from `sha256` (`raw_schemas.py:179-195`). Random hashes do not compress. In a lean
   14-column `filenames`, the three hash columns are **158 of 207 MB**, even stored as 32-byte
   binary.
3. **Capture provenance copied into the model.** Columns such as `source_link_url`,
   `source_capture_url`, `state_body_key` and the nested `source_occurrences` repeat per filename
   row what `raw.captures` already holds.
4. **1,024-row row groups** multiply items 1 and 2 into the footer.

What the explorer actually needs to list, search and filter, measured on `documents`:

| Browser file shape (1,241,157 documents, ZSTD) | Size |
|---|---:|
| filename + congress + document_kind + document_family + format, sorted by filename | **3.6 MB** |
| same + 16-hex ID prefix (unique across all 1.24M) | 15.3 MB |
| same + full 64-hex `document_id` | 47.2 MB |
| ID lookup index: 32-byte binary ID + list row number, sorted by ID | 43.5 MB |

The list-and-search file is small enough to download once and search in memory. Today the search
path downloads every column of every row (finding M3).

## Findings

Severity: **blocker** means the design does not work as written; **major** means it works but
misses its goals (cost, determinism, budget); **minor** means a correctness or cleanliness gap
with a cheap fix.

### B1 (blocker): iceberg 0.10.1 cannot do a safe "replace table", branch swap or tag, and the engine's existing workaround drops the commit check on REST

**Evidence**
- iceberg 0.10.1's `Transaction` offers only `fast_append`, `expire_snapshots`, schema,
  properties, sort order, location, statistics and format upgrade
  (`iceberg-0.10.1/src/transaction/mod.rs:135-170`). There is no overwrite, delete,
  replace-partitions or rewrite action, and no `ManageSnapshots` for branches or tags.
- Every snapshot the library produces is committed to `main`
  (`transaction/snapshot.rs:507-527`), so "write to a branch, then fast-forward" is not
  available.
- `fast_append` carries every existing manifest forward (`transaction/append.rs:114-139`), so
  appending a new full copy doubles the table.
- The extension points are crate-private: `pub(crate) trait TransactionAction` (`action.rs:37`)
  and `TableCommit`'s builder is `pub(crate)` (`catalog/mod.rs:350`). docspec-rs cannot add an
  overwrite action without patching or forking the crate.
- docspec-rs already "replaces" a table, for its lifecycle store, in `replace_baseline_snapshot`
  (`docspec-rs/src/catalog.rs:1115-1166`). It removes `main` from an in-memory copy of the
  metadata, so `fast_append` writes a manifest list without the old manifests, then expires
  every old snapshot. The commit's requirements are then discarded:
  `let _ = commit.take_requirements();` (`catalog.rs:1354`). The comment says this is safe
  because "`SqlCatalog::update_table` performs an atomic compare-and-swap on
  `metadata_location`".
- On the R2 REST catalog, the requirements are the only compare-and-swap. A commit sent without
  `assert-ref-snapshot-id` is applied to whatever the table holds when it arrives. The
  `load_table` pre-check (`catalog.rs:1349`) is check-then-act. A manual run racing the
  scheduled run would silently replace a newer snapshot instead of failing.

The design's §6 "Add 1" (replace table) and "Add 4" (release pins as Iceberg tags) both rest on
primitives the library does not have. §6's "Library constraint" paragraph (lines 223-226) is
right about delete files but misses this.

**Recommendation.** Prefer not needing it (finding M1): the model tables do not need to be
Iceberg tables. If they stay in Iceberg, build replace as follows:
1. Reuse the detached-base `fast_append` to write the new manifest list. It needs no library
   change, and the data files are already written.
2. Send the commit with explicit requirements, not none: `assert-table-uuid` plus
   `assert-ref-snapshot-id {ref: main, snapshot-id: <real current>}`. Since `TableCommit`
   cannot be built outside the crate, take its updates with `commit.take_updates()` (public)
   and post a standard REST `UpdateTable` request with those updates and the correct
   requirements. `TableUpdate` and `TableRequirement` are public and `Serialize`. The other
   route is a small `[patch.crates-io]` adding an `OverwriteAction` (`Operation::Overwrite`),
   offered upstream.
3. Mark the snapshot (for example `docspec.operation=replace`), because the summary will
   otherwise say `append` (`append.rs:104`).
4. Skip tags. A release manifest that names its inputs (finding m2) gives the same audit trail.
   With no `ManageSnapshots` action, a tag would need the same raw-REST path for no reader
   benefit.

### M1 (major): Iceberg fits the append-only tables, not the replaced model tables; persist the model as content-addressed Parquet

**Evidence.** Nobody time-travels the model tables. The site reads only exported files (§4.5,
§4.6). Each run rewrites every model table. For these tables Iceberg adds the missing replace
primitive (B1), retention and orphan handling (m1), a second copy of about 1 GB per run, and a
read-back from R2. The release manifest already gives atomic publish (If-Match) and history (each
`releases/<id>.json` is immutable). The doc concedes "Plain Parquet plus a JSON manifest" is
"reasonable if Iceberg proves heavy" (line 280).

For `raw.captures` and `derived.readings`, Iceberg fits well:
- `fast_append` is exactly the operation needed.
- The high-water mark and the appended files commit atomically in one snapshot, which gives
  exactly-once append without a journal.
- `identity(parser_version)` partitioning gives manifest-level pruning (see the settings table).

**Recommendation.** Keep Iceberg for `raw.captures` and `derived.readings`. Make model plus export
one engine step whose durable commit is:
1. create-only PUTs of content-addressed Parquet;
2. a step manifest keyed by (input high-water marks, SQL digest, engine digest).

`url_state`, which the fetcher needs, is one more content-addressed file named in that manifest.
This still meets "durable commit after every step" and "engine first": docspec-rs computes and
writes everything. It deletes §6 Add 1 and Add 4, and with them most of the retention surface. Is
Iceberg worth it at about 4M rows? For the two append-only tables, yes, cheaply. For the rest, no.

### M2 (major): the engine writes 2 MiB files with 2,048-row row groups to R2 and scans them one file at a time, and the doc's measurement cannot see it

**Evidence**
- For every `s3://` table, `write_batches_inner` caps the file target at 2 MiB, row groups at
  2,048 rows and 2 MiB (`docspec-rs/src/storage.rs:376-388`). These caps arrived in `b4b827d`
  ("perf(remote): extend fast initial leaf admission…") with no stated reason. The audit calls
  them "unmeasured" (README §Fourth pass, item 5).
- Native scans read one data file at a time: `.with_data_file_concurrency_limit(1)`
  (`storage.rs:211`).
- Scans expose a single DataFusion partition with unknown byte statistics
  (`query.rs:349, 368`), so all decoding funnels through one stream before any repartition.

At today's sizes, a lean `raw.captures` (about 130–150 MB) becomes about 70 files and about
1,900 row groups. Small row groups also weaken dictionary encoding: a 64-hex column in the legacy
file compresses only because values repeat within a row group (188 MB → 68 MB over
3.9M rows / 1.04M distinct). Model tables at today's width would be about 235 files per run, each
a sequential GET on read and a PUT on write.

The §9 measurement runs SQL over local Parquet. `is_remote` is false for local tables
(`storage.rs:376`), so the measurement exercises none of this. It is a check that cannot see the
production path.

If R2 managed compaction (64–512 MB targets) is ever enabled on these tables, it rewrites the
engine's 2 MiB files behind its back. That changes the `__docspec_file` paths that occurrence
identity uses (`storage/occurrences.rs:21-23`).

**Recommendation**
- Make file target, row-group rows and bytes per-table settings read from the standard Iceberg
  properties: `write.target-file-size-bytes`, `write.parquet.row-group-size-bytes`,
  `write.parquet.page-size-bytes`. Then set them (settings table below).
- Keep the memory bound the cap was protecting. The FanoutWriter close-on-pressure logic at
  `storage.rs:414-427` already bounds open partitions.
- Raise scan concurrency to the budget (for example 4 files in flight on a 4-vCPU runner).
- Keep R2 managed compaction off for engine-written tables, and write right-sized files instead.
- Run the §9 measurement against R2 from the hosted runner, not only locally.

### M3 (major): the browser layout the doc describes (one sort per table, page indexes, Bloom filters on IDs) does not match how the explorer reads

**Evidence**
- **Lookup by an unsorted column.** The components export is sorted by
  `(filename, document_id)` (`viewer_publication/filename_exports.py:211-214`). The reader
  resolves a `document_id` by filtering per-row-group `browse_ranges` on `document_id`
  min/max (`catalog-v6.ts:265-287`). With a filename sort, every row group spans nearly the
  whole hash range, so every candidate group is read in turn. A document lookup is O(N) in the
  browser. One sort cannot serve both browse order and ID lookup.
- **Search reads everything.** Any search text or facet filter reads every column of every
  component row: `read(componentsFile, 0, componentsFile.rows, undefined)`
  (`catalog-v6.ts:308`). That is the whole file.
- **Index features are never switched on.** The reader calls
  `parquetReadObjects({file, metadata, compressors, columns, rowStart, rowEnd})`
  (`catalog-v6.ts:188`) with no `filter`, `useOffsetIndex`, `usePageIndex` or
  `useBloomFilters`. hyparquet 1.31.2 supports all four, but each defaults to `false`
  (`hyparquet/src/types.d.ts:46-48`). The page indexes written today
  (`page_index_columns`, `filename_exports.py:179, 215`) are dead weight to this reader, and
  Bloom filters would be too.
- **Bloom filters add little even when enabled.** hyparquet uses them only for `$eq`/`$in`
  filters, after a separate fetch. On a sorted key, min/max and the column index already prune
  exactly. On an unsorted key, a 5% false-positive rate across about 76 row groups still reads
  4–5 groups. parquet-rs 58 sizes each filter from the row-group row count
  (`parquet-58.4.0/src/file/properties.rs:644-651`); with `row_group_rows` unset it is sized for
  1,048,576 values, about 1 MiB per column chunk.

**Recommendation.** Split browser files by access pattern (settings table below):
- a whole-file `list.parquet` (about 4 MB) for browse, search and client-side facet counts;
- a `detail.parquet` in the same row order, read by row number with `useOffsetIndex: true`;
- an `ids.parquet` sorted by ID, read with `filter: {id: {$eq}}` and `usePageIndex: true`;
- occurrences addressed by `[occ_start, occ_start + occ_count)` stored in `detail`, replacing
  `browse_ranges` JSON.

Drop Bloom filters, and add the reader options in the same change as the writer settings.

### M4 (major): export byte-determinism is assumed, not built in, and "two consecutive runs" cannot detect its failure modes

**Already deterministic (keep):**
- arrow IPC schema metadata is key-sorted (`arrow-ipc-58.4.0/src/convert.rs:132-151`);
- facet counts use a `BTreeMap` (`engine/export/pipeline/facets.rs:171-176`);
- `CollectSet` is `array_sort(ARRAY_AGG(DISTINCT …))` (`engine/aggregation.rs:406`);
- child tables sort by key then ordinal (`pipeline/child.rs:240-246`);
- `created_by` is a per-version constant (`parquet/src/file/properties.rs:51`).

**Not guaranteed:**
1. **Row order needs a unique key.** Exports sort with `df.sort(order_by)`
   (`pipeline.rs:153-190`). Nothing checks the key is unique. With ties, row order follows
   partition arrival order.
2. **Bytes depend on how input is chunked.** Row groups flush on `in_progress_rows` and also on
   `memory_size()` / `in_progress_size()` (`pipeline.rs:607-616`). parquet-rs decides page
   splits and dictionary fallback per mini-batch inside each `write()` call. Output bytes
   therefore depend on the batch boundaries DataFusion emits, which change with `batch_size`,
   spills or an engine upgrade.
3. **Physical identity leaks into IDs.** If a model row lacks a row key and body tokens,
   ConnectedComponents falls back to physical occurrence paths for `document_id`
   (`connected_components/topology.rs:256`). It also breaks representative ties by "physical
   occurrence" (`connected_components/eval.rs:205`). Under replace-per-run, input file paths
   are new UUIDs every run (`storage.rs:477`, `DefaultFileNameGenerator`). Such rows get a new
   `document_id` each run, breaking both content addressing and permalinks.
4. **Model SQL can reorder freely.** `ARRAY_AGG`, `string_agg`, `first_value` without
   `ORDER BY`, windows with ties, and float sums across partitions can all vary.
5. **Wrong hash.** The export hashes while writing, but with BLAKE3 (`engine/export.rs:660`),
   while §4.5 names objects by SHA-256.

**Recommendation**
- Before writing, rechunk the sorted stream into fixed K-row slices (K = row-group rows), and
  flush on row count only.
- Set `data_page_row_count_limit` so page splits depend on rows, not encoder state.
- Verify sort-key uniqueness while streaming (one comparison of adjacent rows, O(N)) and refuse
  on duplicates.
- Forbid `__docspec_*` columns in model SQL. Make CC tie-break and fallback on logical keys only,
  or refuse rows without a key.
- Lint model SQL for unordered aggregates.
- Swap the export hasher to `sha2` (doc §6 Remove 5 already wants `sha2`).
- Change the §8.2 test to run export with `target_partitions` 1 vs 4, `batch_size` 1,024 vs
  8,192, a forced-spill memory pool, and once after rebuilding `raw.captures` from receipts (new
  file layout). Byte-compare all of them. Two consecutive runs on one machine vary none of the
  inputs that cause drift. Record the parquet crate version in the release manifest; an
  upgrade legitimately re-uploads everything once.

### M5 (major): the ConnectedComponents operator is single-threaded, string-heavy, and under-reports its memory

**Evidence.** `GraphTopology::from_table` (`connected_components/topology.rs:94-277`) holds
per-row `String`s and cloned tokens in `Vec`s and `HashMap`s: `row_keys`, `occ_files`,
`row_tokens`, `row_body_tokens`, `key_owner`, `token_owner`. It then builds `components` and an
`occurrence_to_doc` map keyed by `(String, i64)` after the budget check. The budget charges only
payload lengths plus 16–32 bytes (`topology.rs:187-190, 204-207, 225-233`). It ignores 24-byte
`String` headers, allocator rounding, the clones in both hash maps, hash-table load factor and
the final maps.

At 1.68M rows with 2–3 edge tokens each, I estimate real heap at 3–5× the charged bytes, around
2–3 GB, on one core. That is unmeasured, and it is the one model step that is not SQL.

**Recommendation**
- Run union-find on dense integers. Assign token IDs with DataFusion (`DENSE_RANK` over distinct
  edge values, or dictionary keys), run `u32` union-find over parallel arrays (tens of MB, under
  a second), and join component IDs back in SQL.
- Compute `document_id` in SQL from the sorted body set per component, as §4.4 already intends.
- Include this step in the §9 measurement.

### M6 (major): engine defaults overcommit the 16 GB runner, and hash-join builds cannot spill

**Evidence.**
- `Limits::default()` is 12 threads, 24 GiB memory and 32 GiB scratch (`budget.rs:41-46`). Half
  goes to a DataFusion `FairSpillPool` and half to the engine's semaphore (`budget.rs:89-99`),
  24 GiB promised on a 16 GB machine.
- Sorts and aggregates spill. `HashJoinExec`'s build side does not in the DataFusion releases I
  know; confirm on 53.1 with a small pool. A wide build side (readings at today's width is
  about 1–2 GB decoded) therefore fails with a resources error, or with the pool overcommitted,
  gets killed by the OS.
- Scans report only an inexact row count (`query.rs:368`). Join-side choice works by rows, but
  nothing sees bytes.

**Recommendation.** Pass explicit limits on the runner: about 4 threads, `memory_bytes` about
10 GiB (5 GiB pool), scratch sized to the runner disk. Join on narrow keys and attach wide
payloads after the join. Run the §9 measurement with these limits.

### M7 (major): the 1–5 minute estimate holds for narrow relational SQL, not for the data as it is

**Evidence (DuckDB proxy on real inputs, 4 threads, load average about 17):**
- Latest-per-URL over 2.58M rows with a URL, materializing all 20 columns: **1.10 s**
  (1,158,426 states).
- Distinct counts over 3.9M captures: 0.2 s.
- Lean 14-column `filenames` written sorted: 2.4–3.1 s.
- Unpivoting the 337 reading columns: 39.6M cells, 9.4 s to count. Writing them long and sorted:
  **30.6 s with about 10 GB peak footprint**, past DuckDB's own 6 GB limit.

So the relational core is seconds. The minutes, and the memory risk, come from:
- the wide, nested readings and occurrence lists;
- the custom CC operator (M5);
- remote I/O through 2 MiB files read one at a time (M2);
- each step re-reading its inputs from R2 under per-step commits.

**What §9's plan would miss:**
1. The R2 path (M2), because it runs locally.
2. CC and export, which are not "SQL".
3. Runner memory limits and the 24 GiB defaults (M6).
4. Per-operator timings: it records time and peak memory only. Use `EXPLAIN ANALYZE` per
   statement.
5. Cold-runner network and disk.
6. A parser-version bump (O(B) re-parse).
7. Growth.

Its fallback, "partition the recompute by capture date or family" (lines 270-272), is wrong for
the operators that dominate. Latest-per-URL and document grouping cross dates and families, so a
partition-scoped recompute gives wrong answers unless partitioned by URL hash. That would rebuild
the routing the doc deletes. If a fallback is ever needed, use the fact that "latest per key" is
associative: `url_state_new = latest(url_state_old ∪ new_attempts)`, which is O(S + C) with no
partitions. CC changes only when edges change.

### m1 (minor): retention: pick one owner for snapshot expiry, and add an orphan sweep

**Evidence**
- iceberg-rust's `expire_snapshots` "only rewrites metadata; the now-unreferenced data and
  metadata files are left untouched" (`expire_snapshots.rs:33`).
- R2 Data Catalog (now GA as Basin Catalog) has managed snapshot expiration, defaults 30 days
  and `retain-last` 5. Since 2026-04-22 it also deletes data files that no retained snapshot
  references. It does not remove orphans that no snapshot ever referenced, such as files from a
  crashed write.
  ([table maintenance](https://developers.cloudflare.com/r2/data-catalog/table-maintenance/),
  [expiration launch](https://developers.cloudflare.com/changelog/2025-12-18-r2-data-catalog-snapshot-expiration),
  [data-file cleanup](https://developers.cloudflare.com/changelog/post/2026-04-22-snapshot-expiration-cleans-data-files/))
- The doc's "retention as Iceberg snapshot expiry" (lines 209-214) covers neither orphans nor
  old `metadata.json` files. Whether R2 honors `write.metadata.delete-after-commit.enabled` is
  undocumented.

**Recommendation**
- Use R2 managed expiry on the append-only tables. Expiring appends never deletes live data.
- Delete the engine's own retention planners.
- Add one weekly engine sweep: list the table prefix, subtract files reachable from retained
  metadata, and delete anything older than 3 days. That age must exceed the longest writer, and
  the sweep runs after expiry, never before.
- `metadata.json` growth is about one snapshot entry per commit, roughly 3,650 files a year at
  about 10 commits a day. That is negligible once expiry is on.

### m2 (minor): release manifests should name inputs by high-water mark, not only snapshot ID

Snapshot IDs vanish under expiry (m1), so "input snapshot IDs" (§4.5) cannot reproduce a release
after 30 days. Record:
- the captures high-water mark (last receipt key and line);
- the readings parser version and row count;
- the SQL and engine digests.

Snapshot IDs can stay as a convenience. Rebuild equivalence (§8.3) then has a stable target.

### m3 (minor): manifest-list growth on append-only tables

`fast_append` keeps every prior manifest (`append.rs:114-139`), so planning a full scan costs one
manifest GET per daily append: about 365 a year. The detached-base trick from B1, done safely,
can rewrite manifests with no data rewrite: `fast_append` the existing `DataFile`s into a fresh
manifest list. Run it quarterly. Do not build a general manifest-rewrite feature.

### m4 (minor): `url_state` needs receipt-level fields the legacy capture schema lacks

`url_state` depends on outcome, fetch mode (attempts count only `mode == "fetch"`),
`retry_later.delay_seconds` and scope exclusions (`retention/raw_archive.py:426-457`, `acquisition/raw_sync.py:194`).
The legacy `CAPTURE_SCHEMA` (`raw_schemas.py:11-34`) has none of them, and it has one row per
body pointer, not per attempt.

`raw.captures` should carry: `requested_url`, `attempted_at`, `outcome`, `mode`,
`retry_after_s`, and a monotonic `attempt_seq` (run ordinal × 2^20 + line) as a single,
tie-free ordering key. Plan sketch 1 below depends on that key.

### m5 (minor): the edge config does not mark the new object prefix immutable

`immutable_prefixes` lists `releases/` and `catalogs/` but not `viewer-publications/objects/`
(`infra/cloudflare/congressional-data-r2-edge.json:69-75`). Content-addressed objects should be
`immutable`, or every range read revalidates. CORS already allows `Range` and exposes
`Content-Range` (lines 15-21).

### m6 (minor): skip the HEAD on unchanged files by consulting the live release manifest

A create-only PUT of an existing object still sends its body before the 412 unless the client
uses `Expect: 100-continue`. Since objects are named by digest, check the new digest against the
live release manifest first and PUT only the new ones. That is one read per run instead of one
HEAD or wasted PUT per file. This matches §6 Add 3.

## DataFusion plan sketches and bottlenecks

Assumptions: docspec's session (`budget.rs:112-125`), `target_partitions = 4`, the
`aggregate_statistics` rule removed, dynamic join filter pushdown off, and native scans as one
partition with inexact row counts (`query.rs:349, 368`).

**1. Latest outcome per URL (`url_state`).** As a window:
```
FilterExec rn = 1
  BoundedWindowAggExec row_number() PARTITION BY url ORDER BY attempt_seq DESC   mode=Sorted
    SortExec [url, attempt_seq DESC] preserve_partitioning                       <- holds all columns; spills
      RepartitionExec Hash(url, 4)
        RepartitionExec RoundRobinBatch(4)
          DataSourceExec NativeScan rows=~3.9M  (one stream, one file at a time)  <- scan-bound on R2
```
Prefer the aggregate form. It never sorts the wide rows and has no spill risk:
```
HashJoinExec Partitioned Inner on attempt_seq                    build: 1.3M int64 keys
  AggregateExec FinalPartitioned gby=[url] max(attempt_seq), count(*) FILTER (mode='fetch')
    RepartitionExec Hash(url,4) <- AggregateExec Partial <- NativeScan [url, attempt_seq, mode]
  RepartitionExec Hash(attempt_seq,4) <- NativeScan [state columns]
```
Hash-aggregate state is about 1.3M groups × (URL plus two accumulators), a few hundred MB. The
DuckDB proxy for the window form took 1.10 s, so the cost is the scan, not the operator.

**2. Filenames joined with readings.**
```
HashJoinExec Partitioned Left on (body_sha256)          build = readings (fewer rows, chosen by row count)
  RepartitionExec Hash(sha256,4) <- FilterExec is_stored AND kind IN (...) <- NativeScan(captures)
  RepartitionExec Hash(body_sha256,4) <- FilterExec parser_version = $v <- NativeScan(readings)
```
Bottleneck: the build side materializes every projected readings column and does not spill (M6).
Use FIXED_LEN_BYTE_ARRAY(32) keys rather than 64-character strings. Join on keys only, carry one
folded `readings` column (`List<Struct<field, values>>`), or keep readings long and fold at
export, as the engine's `fold_readings` already does. Partition readings by `parser_version` so
the filter prunes at manifest level instead of decoding every version.

**3. Document grouping (ConnectedComponents).** Not a DataFusion operator. It is one
`NativeScan` stream into in-process union-find, then evidence batches, then aggregates via
DataFusion re-scans with a per-component sort (`connected_components/eval.rs:205-230`).
Bottlenecks: one core, string hashing and cloning, under-counted memory (M5). The integer
union-find in M5 turns this into about a second of work plus two hash joins.

**4. Export.** `SortExec` over the model rows (spillable), then sequential `ArrowWriter` with
hash-while-write (`pipeline.rs:153-190, 446-660`). Bottlenecks: the global sort of wide rows, and
footer size from many columns × row groups (refused above `max_metadata_bytes`,
`pipeline.rs:620-630, 650-657`). Narrow files (M3) make both trivial.

## Recommended settings

**Iceberg tables (format v2; everything that reads them is iceberg-rust):**

| Table | Partition spec | Sort order (within files) | File target | Row group | Page | Encoding notes | Stats / indexes | Bloom |
|---|---|---|---|---|---|---|---|---|
| `raw.captures` (3.9M rows, append-only) | none: one partition is under 200 MB, and the global queries (latest per URL) prune nothing by date or family | `(url, attempt_seq)` | 128 MB (2–3 files now, plus one per daily append) | 131,072 rows | 1 MiB | hashes as `fixed[32]` with dictionary on (3.9M rows share 1.04M bodies); no `body_key` column (derive it); ZSTD(3) | chunk stats; no page index | none |
| `derived.readings` (about 1.04M bodies per version) | `identity(parser_version)` | `body_sha256` | 128 MB | 65,536 rows | 1 MiB | narrow typed core (filename, title, page count, format) plus one folded `readings List<Struct<field string, values list<string>>>`; large text spans in their own table if kept | chunk stats | none |

**Model step outputs (content-addressed Parquet, M1):** one file each, sorted by primary key,
131,072-row row groups, ZSTD(3), hashes as 32-byte binary, no copied provenance columns.
- `url_state`: about 1.3M rows, 12 columns, tens of MB.
- `filenames`: about 1.68M rows. Keep body and reading data out; join by `body_sha256`.
- `documents`: about 1.24M rows. Member lists as a separate `(document_id, source_id)` table,
  not nested.

**Browser exports (hyparquet 1.31.2):**

| File | Row order | Row group | Pages | Columns and encoding | Reader call |
|---|---|---|---|---|---|
| `list.parquet` (about 4 MB) | `(filename, document_id)` | 65,536 rows | default | filename (dictionary off; `DELTA_BYTE_ARRAY` suits sorted names, and parquet-rs writes it in V2 pages, which hyparquet decodes; V1 pages would throw, `datapage.js:50-63`), facets as dictionary strings or small ints, flags `int8` | fetch whole, cache, search and count facets in a worker |
| `detail.parquet` | same as `list` (row number is the join) | 8,192 rows | `data_page_row_count_limit` 256; offset index on | full ID, URL, body hash, folded readings, `occ_start`, `occ_count` | `rowStart`/`rowEnd` with `useOffsetIndex: true` |
| `ids.parquet` | `id` | 65,536 rows | column index on `id`, 8 KiB pages | `id` (32-byte binary or 16-hex prefix), `row int32`; dictionary off | `filter: {id: {$eq}}`, `usePageIndex: true` |
| `occurrences.parquet` | `(list_row, ordinal)` | 16,384 rows | offset index on | occurrence fields | range from `detail.occ_*` with `useOffsetIndex: true` |

For all browser files:
- **Codec:** ZSTD(3). The site already ships `hyparquet-compressors` (fzstd); measure decode time
  in the canary before considering Snappy.
- **Writer:** `PARQUET_2_0`.
- **Statistics:** chunk level, with the current 128-byte truncation (bounds stay valid).
- **Bloom filters:** none.
- **Footer:** under 512 KB, so hyparquet's first 512 KB fetch covers it in one request
  (`hyparquet/src/metadata.js:11`).
- **Facet counts:** unfiltered counts come from the manifest (the existing `FacetAccumulator`);
  filtered counts are computed client-side from `list.parquet`.
- **Short public IDs:** this is an owner decision. A 16-hex prefix (64 bits) of today's SHA-256
  is unique across all 1.24M documents and has a negligible collision risk at 10× the size. It
  cuts the ID-carrying files by about 3×. The export must refuse on collision. Old full-length
  links still resolve by prefix.

**Engine runtime on the hosted runner:** `compute_threads` 4, `memory_bytes` about 10 GiB,
`batch_rows` 8,192, scan concurrency 4. Remote caps come from table properties, not the 2 MiB
constant.

## What the doc gets right

- Raw is the only truth, and the rest is a function of raw plus versioned code. The weekly
  body-hash check and create-only PUT with Content-MD5 are the right platform primitives (§4.1).
- Readings keyed by `(body_sha256, parser_version)`, parsed once, with the anti-join listing
  missing work (§4.3). This is the only incremental work, and it is correct to make it explicit.
- Full recompute over keyed merges (§10). Copy-on-write in iceberg 0.10.1 makes merges O(files
  touched), and hash-spread keys touch nearly every file. Measured here: the relational core is
  seconds.
- The library constraint is stated honestly (§6). It holds for row updates; B1 adds that it also
  covers replace and tags.
- Content-addressed objects, one release manifest, a canary through the real reader, and an
  If-Match flip (§4.5). These remove the journals and custody code.
- The reader accepts two schema versions, and CI runs real publisher output through the real
  reader (§4.6). This is the right contract test for every Parquet setting above.
- The model recompute time is named as the load-bearing assumption, measured before deleting
  anything (§9, §11 phase 0). M2, M6 and M7 only widen what that measurement must include.
- Engine policy (`document_id`, edge names) moves out of the engine into SQL (§6 Remove 4). This
  also fixes the physical-path fallback in M4.3 if the SQL refuses rows without a logical key.
