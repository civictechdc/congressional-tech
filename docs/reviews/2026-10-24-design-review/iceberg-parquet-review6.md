# Iceberg, Parquet and DataFusion review (review 6)

**Reviewed:** the frozen snapshot of A (`engine-first-architecture.md`), DM (`engine-first-data-model.md`), P (`plans/simplification-plan-20261024.md`), B (`plans/bindings-20261025.md`) and `decisions.md`, read cold. **Checked against:** docspec-rs at `d9c6719` (read only), the pinned crates in the local Cargo registry (iceberg 0.10.1, iceberg-catalog-rest 0.10.1, iceberg-datafusion 0.10.1, DataFusion 53.1.0, parquet and arrow 58.4.0, opendal 0.57.0), the site's hyparquet 1.31.2, Basin Catalog's own docs (fetched 2026-10-25, User-Agent `congressional-tech-review/1.0`), and the 2026-10-19 data snapshot.

**Number tags:** *(measured)* = measured in this review; *(docs)* = from A, DM, P or B; *(est.)* = my estimate. Measurements used pyarrow 25.0.1 (`ice6_measure.py`, results in `ice6_out/ice6_results.json`), not the engine's parquet-rs writer, so they show layout effects, not exact engine bytes. Nothing here was built or run in docspec-rs.

## Verdict

**Ready to build from once the two must-fixes are folded in.** Both are one-sentence rewrites of existing rules. The should-fixes can land with M2, C1, C3 and C6, before track E depends on them. The design is sound: an append-only lake with work lists, a guarded commit path that already exists in the engine, deterministic exports, binary keys, and a reader built on offset indexes. What remains is in two places. The gate that decides whether to keep Iceberg cannot see the failure it gates. And the writer settings put megabytes of dictionary pages under every ranged read.

| Area | Score |
|---|---|
| Lake design | 74 |
| Release files | 72 |
| Query plan | 70 |
| Engine fit | 80 |
| **Overall** | **75 / 100** |

Counts: **2 must-fix, 6 should-fix, 8 minor.**

## Must-fix

### MF1. The M1 maintenance measurement cannot see the failure it decides on

**Location:** P §5.1 item 2 and its "Decides" line; A §8.7, "Fallback".

**Failure.** M1 decides whether Iceberg stays, and the rule counts **manifests** only. Basin's docs say compaction "combines new files that have not been compacted yet" (Basin docs). They do not say whether files already compacted are merged again toward the target. If they are not, each table gains about one small compacted file per maintenance run, per partition, for good. `readings` alone has five parser partitions a day (docs). The engine's provider reads data files one at a time in one partition (`ds/query.rs:349`, `ds/storage.rs:209-213`), so scan time grows with the number of days.

The planned test cannot observe this. Appending 400 batches in one session gives Basin a single burst of new files. Expiration's defaults are 30 days and 5 snapshots (Basin docs, matching A §8.7), so no snapshot in the session is old enough to expire. "Confirm that expiration deletes the data files only expired snapshots referenced" therefore cannot pass or fail. Manual queueing has a daily request limit (error 42901, Basin docs), so it cannot replay 400 days in one go either. The measurement would report "bounded", because nothing in it could have grown.

**Fix (rewrite, no new text).** In P §5.1 item 2, replace the first two sentences with: "On a scratch table with snapshot expiration at its shortest age, append day-sized batches (about 315 KB) across at least ten Basin maintenance runs. After each run, count the current snapshot's data files and manifests and the bytes expiration removed. Then drop the table with purge and list what remains." Change "Decides: Iceberg stays (manifests bounded)" to "(data files and manifests bounded)". In A §8.7, change "keeping the number of manifests in the current snapshot bounded" to "keeping the current snapshot's data files and manifests bounded". (MN7 moves that paragraph into P.)

### MF2. Dictionary pages make every ranged and lookup read fetch megabytes

**Location:** DM §8.1, "Shared writer settings" and "Writer profiles"; DM §4, "Folds".

**Failure.** DM §4 says dictionary encoding is "on by default". parquet-rs 58 agrees: `DEFAULT_DICTIONARY_ENABLED = true`, with a 1 MiB dictionary page (`parquet/src/file/properties.rs:37-39`). Only `list.filename` turns it off. hyparquet 1.31.2 fetches a column chunk's **whole** dictionary page with any page it selects through the offset index. It does this even when the selected page fell back to plain encoding (`hyparquet/src/rowgroup.js:88-131`). Measured on real snapshot data *(measured)*:

| File | Dictionary bytes a single read pulls | Without dictionaries |
|---|---|---|
| `links` (all 1,036,256 real body prefixes, 16 KB pages, one row group) | `link_key` 998 KB + `list_row` 802 KB ≈ **1.8 MB per lookup** | ≈ 35 KB per lookup; file 11.09 MB instead of 11.81 MB |
| `detail` (one 65,536-row group of real folded facts, 564,727 fold values) | `saved_body` 1.07 MB + fold `value` 248 KB + `source_url` 103 KB ≈ **1.4 MB per view, from three leaves** | one page per leaf; file 7.20 MB instead of 7.24 MB |

The real `detail` adds more unique leaves (`link_key`, `alternates.body`, `occ_start`), and `occurrences` and `recoveries` behave the same way. A detail view therefore pulls several MB *(est.)*, where DM claims 50–90 KB. F0 uses "the final writer settings", and P A11 fixes the speed targets from F0. The bloat would be locked into the targets.

**Fix (rewrite).** DM §8.1 shared settings: "Parquet 2.0 data pages and ZSTD; dictionary encoding only on `dict` columns; …". DM §4: change the fold type to `list<struct<field: dict, value: string>>`. `list.filename`: delete "with dictionary off" (now the rule) and keep `DELTA_BYTE_ARRAY`. *Lookup* profile: "an offset index on every leaf and a column index on the key". Without an offset index, `list_row` is read whole (about 3 MB *(measured)*). Replace the detail figure "50–90 KB" with "about 100–200 KB". A 32-byte hash leaf is a 32 KB page at 1,024 rows *(est.)*.

## Should-fix

### SF1. "Carry its requirements" does not stop iceberg-rust from rebasing the commit

**Location:** A §8.1, first paragraph; DM §6, `commit.retry.num-retries` 0 and its reason; B §3.3, C2.

**Failure.** On every attempt, the first included, iceberg-rust 0.10.1's `Transaction::commit` reloads the table, re-applies the actions to whatever snapshot is now current, and builds its requirements from that snapshot (`iceberg/src/transaction/mod.rs:218-246`). An append computed against snapshot S1 is committed onto S2 with a valid S2 requirement. Two runs on the same receipts would both commit, and the table would hold the rows twice. Setting `commit.retry.num-retries` to 0 does not prevent this, because the rebase happens before any retry. What does prevent it today is docspec-rs's `GuardedCatalog`. Its `load_table` refuses when the table moved (`ds/catalog.rs:1334-1345`), and `append` goes through it (`ds/storage.rs:858-870`). A spec reader using plain iceberg-rust would meet the clause as written and still produce duplicates.

**Fix.** A §8.1: "Every commit MUST assert the table UUID and the snapshot its work list was read at, so it never rebases onto a newer snapshot." DM §6: delete the `commit.retry.num-retries` clause. Its stated reason is not the mechanism. B §3.3 C2: replace "detached mode must not drop commit requirements" with "every append goes through `GuardedCatalog` with its requirements (detached mode drops them, `ds/catalog.rs:1347-1356`)".

### SF2. Columns added inside a list's element struct cannot be read on the pinned stack

**Location:** DM §6, "Schema growth"; P §5.1 item 4; B §3.3 C1.

**Failure.** Three layers each refuse:

- **docspec-rs.** `read_schema` (`ds/storage/schema.rs:17-60`) refuses any root field whose type differs from any historical schema, and any non-primitive addition.
- **iceberg-rust 0.10.1.** It reads a changed column with arrow `cast` (`arrow/record_batch_transformer.rs:610-613`).
- **arrow 58.** It refuses struct-to-struct casts with different field counts (`arrow-cast/src/cast/mod.rs:198-201`). DataFusion's nested cast handles bare structs, not `list<struct>`.

`read_schema` walks every schema in the metadata, so one nested addition breaks `readings` for good, even after the field is removed. The only repair is a rebuild: about 1.04M sniff reads plus about 5 GB of HTML and XML (docs).

**Fix.** DM §6: "gain a column only as an optional one at the root". Delete "or inside a list's element struct". New display-only facts already have the fold. P §5.1 item 4: drop the list-element case. B §3.3 C1 work: "accept optional root additions of any type in `read_schema`". It refuses non-primitive ones today, and iceberg-rust fills absent root columns with nulls.

### SF3. "One plan with no intermediate tables" is not a shape DataFusion can run

**Location:** A §9.1; A §13 items 3 and 7; B §3.3 C7.

**Failure.**

- **CTEs.** DataFusion inlines non-recursive CTEs (`datafusion-sql/src/cte.rs`: the CTE's plan is substituted at each reference).
- **Multiple outputs.** DataFusion has no multi-output plan.
- **Connected components.** Grouping is not a SQL operator. It must take the edge relation's result and hand components back, so the job runs as at least two plans with a relation between them.

As written, each of the six component-dependent release files would re-evaluate the edges, link resolution, grouping and documents: about ×6 the model's work *(est.)*. The outputs would still agree, since determinism holds, but A §16.1's "seconds" assumes the work is done once. `DataFrame::cache()` keeps results outside the memory pool (`datafusion/src/dataframe/mod.rs:2387-2402`, `collect_partitioned` into a `MemTable`). DataFusion's `cache_factory` hook is the place to keep them inside it.

**Fix.** A §9.1, second sentence: "One engine job registers … evaluates the edges, groups them in memory (§13.4), holds the components and documents once in the memory pool (spilling to scratch), and writes every release file from them; nothing is written to the lake." B §3.3 C7: "the declarative job spec, which names the relations evaluated once".

### SF4. Nothing pins which side of a hash join is built

**Location:** A §13 item 6; P §6.3 C6.

**Failure.** DataFusion 53's `JoinSelection` swaps join inputs by statistics: byte size when known, otherwise row count (`datafusion-physical-optimizer/src/join_selection.rs:59-77`). docspec-rs's provider reports row counts only ("Decoded byte sizes stay unknown", `ds/query.rs:365-369`). The side with fewer rows becomes the non-spilling build side, and that is often the wide one. One example: the saved file's reading with its fold (about 288k HTML and XML bodies, docs) attached to about 0.65M documents (docs). After aggregates the statistics become Absent and the choice depends on SQL order. "Keep wide columns off the build side" cannot be held by plan authors.

**Fix.** A §13 item 6: "Hash-join builds do not spill, so the engine builds the side the plan names, never swapping by row count, and plans keep wide columns off it …". docspec-rs already drops one optimizer rule (`ds/budget.rs:112-117`). Here the swap must go while partition-mode resolution stays. P C6 contract test: "M2's build sides, asserted from EXPLAIN".

### SF5. The provider prunes nothing, so reads of `readings` grow with every retained version

**Location:** B §3.3 C1; A §16.1, the list of accepted repeated work.

**Failure.** For lake tables, `NativeTable` drops pushed filters. Its `Table` branch calls `read_projected_batches` with no predicate (`ds/query.rs:413-419`). `plan_selected_files` builds `table.scan()` without `with_filter` (`ds/storage/schema.rs:100-104`), and files are read serially in one partition. `readings` keeps "every version produced" (DM §6). Every model run and every completeness-gate anti-join therefore decodes all versions of all parsers. That cost grows with versions × bodies, and A §16.1 does not name it. iceberg-datafusion **0.10.1** pins the same DataFusion 53.1.0 and parquet 58 and is already in the local registry. Its `IcebergStaticTableProvider::try_new_from_table_snapshot` scans a pinned snapshot and pushes filters into iceberg-rust's planning (`iceberg-datafusion/src/physical_plan/scan.rs:213-228`). iceberg-rust then prunes partitions and row groups and reads files concurrently.

**Fix.** B §3.3 C1: replace "multi-partition scans or a maintained provider (decided in M2)" with "scan the pinned snapshot with the partition filter pushed into iceberg-rust's planning; measure iceberg-datafusion 0.10.1's static provider against `ds/query.rs` in M2".

### SF6. Basin does not read the table properties the data model sets for it

**Location:** DM §6, "Table properties" and "Writer settings"; A §8.7; P §6.4 D6.

**Failure.** Basin's compaction target is a maintenance setting (`--target-size`, 64–512 MB, default 128), set per catalog or per table (Basin docs). It is not `write.target-file-size-bytes`. Nothing in Basin's docs says compacted files follow `write.parquet.*` or the engine's row-group sizes, so "Files Basin compacts follow the table properties" is unsupported. Catalog-level maintenance "applies retroactively to all existing tables" (Basin docs). That covers each new `captures` table without a per-table enablement step.

**Fix.** DM §6: delete `write.target-file-size-bytes` and the sentence "Files Basin compacts follow the table properties". A §8.7, first sentence: "Basin Catalog's catalog-level maintenance compacts every table (target 128 MB) and expires snapshots (older than 30 days, keeping the last 5)". Delete "with maintenance enabled at creation". P D6 becomes "Enable Basin's catalog-level compaction and snapshot expiration."

## Minor

- **MN1. Sort clause on `readings` (DM §6.2).** "sorted by `body_sha`" buys nothing. The keys are random, every join is a hash join, and Basin bin-packs. Delete it, and keep `captures`' `(url, retrieved_at)` sort: 108 MB, against 134 MB in receipt order, for the compact columns available in the snapshot *(measured, −19%)*.
- **MN2. A §13 last paragraph.** "Iceberg is used only to read and append" contradicts the schema update (DM §6) and table create and drop (A §8.7). Rewrite as "only to read, append, add optional columns, and create and drop tables".
- **MN3. Dropping old `captures` tables (A §8.7).** Name the drop: iceberg-rust 0.10.1's `purge_table` sends `purgeRequested=true` (`iceberg-catalog-rest/src/catalog.rs:879-881`). Files Basin leaves behind then show in the orphan report.
- **MN4. `list` size (DM §8.1).** The `filename` column alone is 2.37 MB at 650,000 rows with `DELTA_BYTE_ARRAY` and no dictionary, and 3.53 MB with one *(measured)*. That confirms the encoding choice, but the whole file is about 4–5 MB *(est.)*, not 2–3 MB. At 10× today's rows it is about 45 MB *(est.)*, not 40 MB (A §10.1).
- **MN5. Offset-index fetch (A §10.1, "Detail reads").** parquet-rs writes every row group's page indexes contiguously before the footer. hyparquet's 512 KB tail read for metadata (`hyparquet/src/metadata.js:11,46`) usually holds them already. "Fetches each needed row group's offset index once per session" can become "reads the offset indexes with the footer".
- **MN6. M1 item 1 (P §5.1).** A race with Basin cannot be timed, because maintenance runs on Basin's scheduler and manual queueing is rate-limited. Race against a second client's commit: any snapshot change exercises the same guarded path.
- **MN7. A §8.7, "Fallback".** This is a contingency, and decisions.md says the specifications describe the target only. P §5.1 already carries the decision, so delete the paragraph from A.
- **MN8. C5 Content-MD5 (B §3.3).** opendal 0.57's S3 setting `checksum_algorithm = "md5"` adds Content-MD5 to each PUT (`opendal-service-s3/src/backend.rs:801-803`, `core.rs:273`). The binding can be configuration, not code.

## Evidence that held

- **Lake facts.** The snapshot's `captures` has 3,909,134 rows, 1,041,865 of them bodiless, and 2,717,129 without a time *(measured)*. That matches DM §6.1's 1,041,863 lines without a body and A §5's "2.7M without a time" (docs). `readings` has 491,710 rows (docs and measured), held today in 721 files of under 1 MB each, with 8,047 row groups averaging 61 rows *(measured)*. That is the small-file shape M1 item 3 expects the caps to cause.
- **B §3.3 line references.** Spot-checked against `d9c6719`, and they hold: `storage.rs:132-141`, `376-391`, `526-530`; `catalog.rs:1162-1163`, `1344-1352`; `pipeline.rs:605-616`, `672-699`; `export.rs:36-38`; `engine/export.rs:658-697`; `objects.rs:534-541`, `555-636`; `write/tests.rs:487`; the union-find at `topology.rs:31-75`. `stop_after(` has 57 call lines by grep, against 56 stated.
- **A §13 on the pinned versions.**
  - iceberg-rust 0.10.1 has `UpdateSchemaAction`, including nested parents (`transaction/update_schema.rs:137`), plus `purge_table`, a partitioned `FanoutWriter` (already used, `storage.rs:679-692`) and snapshot-pinned scans.
  - DataFusion 53's hash-join build grows its reservation and never spills (`joins/hash_join/exec.rs:1871-1874`), as A §13 item 6 says.
  - parquet-rs 58 supports every per-file setting C3 needs.
  - hyparquet decodes `DELTA_BYTE_ARRAY` only in V2 pages (`datapage.js:53-63` against `:195`). DM's V2 pin is therefore load-bearing for `list.filename`.
  - hyparquet's binary min and max comparison (`filter.js:242-257`) makes the `links` column-index lookup work.
- **Detail size.** One real 65,536-row group with folded facts is about 7.2 MB *(measured)*, about 72 MB for 0.65M rows *(est.)*. That is consistent with DM's 55–70 MB.

## Which steps scale with history

| Step | Grows with | Named in A §16.1? |
|---|---|---|
| Model and export (recomputed each publish) | all rows | yes |
| Completeness gate: `fingerprint` work list (re-runs the real-file rule), filename work list (effective filename over every capture row) | all capture rows | partly ("anti-joins scan the keys") |
| Any read of `readings` through today's provider | parser versions × bodies | **no** (SF5) |
| Lake file and manifest count, if Basin never merges compacted files | maintenance runs | **no** (MF1) |
| Weekly LIST of `bodies/` | all bodies (metadata only) | yes |
| Release upload | release size, on any day with a change | yes |
