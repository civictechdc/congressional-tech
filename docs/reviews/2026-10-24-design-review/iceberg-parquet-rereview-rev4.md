# Re-review: engine-first architecture rev 4 and simplification plan rev 2

Reviewed: `docs/engine-first-architecture.md` (revision 4) and
`docs/plans/simplification-plan-20261024.md` (revision 2), at `cfa1c7c2` in `wt/ct-ticket-audit`.
The lens is the same as in `iceberg-parquet-review.md`: Iceberg, Parquet, query plans and the
browser reader. Checked against docspec-rs `d9c6719`, iceberg 0.10.1, hyparquet 1.31.2 and the
CS300 measurement scripts now in `docs/reviews/2026-10-24-design-review/measurements/`.

## Verdict

Revision 4 resolves the earlier blocker and most of the majors:
- no Iceberg model tables, so no replace and no tags (design §6.1, §9);
- sizes come from table properties, and the 2 MiB cap gets measured or removed (§9.5, plan M1.3);
- bounded memory pools (§8, §9.6);
- in-memory integer grouping with placeholder bodies excluded (§6.1);
- narrow browser files with binary hashes, no ID in `list`, and no Bloom filters (§6.2).

What remains is mostly gaps in the specification, not flaws in the design:
- appends will collide with Basin Catalog's own maintenance commits;
- the browser file set has no per-source detail, and its sizes leave out the readings;
- the engine's export settings would disable the row-level reads the reader depends on;
- the week-one measurement leaves out the widest data.

None of these blocks week one. Fold R1 and R3 into M1 and M2 before they run.

## Owner decisions (2026-10-24, after this re-review)

1. **Document pages only (option C).** No per-copy pages, no copy links, and no `sources.parquet`.
   Per-copy filename readings stay in the lake (`filename_readings`) and out of releases.
   Today's source-ID deep links (`catalog-v6.ts:111`) are retired. This is a recorded product
   change, not a regression.
2. **Short public IDs:** a 16-hex prefix of the SHA-256 `document_id` (design §14.1). `ids` is
   about 14 MB, and the export refuses a release on a prefix collision.
3. **Desktop and mid-range phones at launch.** This makes R10 a requirement: decode `list`
   column by column in the worker, and give the canary a heap budget.
4. **One representative saved file per document page.** The page links one stored body
   (`bodies/sha256/…` on the public domain) beside the original URL. On the Oct 19 catalog,
   39,851 documents (3.2%) have 2–5 distinct bodies and 2 have more than 5; their other
   versions stay in R2 but are not linked from the site. `document_id` still hashes the full
   body set. The representative rule belongs in the written grouping rule (plan E1): a
   deterministic SQL choice with logical tie-breaks only, never a physical file order (R9).
5. **Only successful real files count as a document's files.** That means a 2xx response of the
   document's own media type (PDF, ZIP, XML, JSON, video playlist; HTML only for documents that
   are web pages). Error and retry pages stay in raw as evidence but never enter a document's
   body set, ID, representative download or file-to-document link lookup.
   - Measured on the Oct 19 catalog: of 39,853 documents with 2+ bodies, 26,178 were ZIP plus
     HTML and 4,125 PDF plus HTML. The HTML was mostly HTTP 503 "retry later" pages: 25,236
     bodies, about 14 KB each, unique bytes per URL.
   - About 3,600 more HTML bodies were 404, 503 request-failed, 522 and 410 pages.
   - Real multi-version documents (two distinct PDFs, ZIPs or JSON files) number about 320.
   - Decision 4 (one representative file) therefore affects about 320 documents, not 40k.
   - Scripts: `multi_bodies.py` and `html_status.py` in this session's scratchpad. Reproduce them
     before citing in the repo.

Effect on the findings below:
- R2 is resolved by decision 1. `detail` carries typed, document-level facts only (kind,
  family, congress, committee, date, URLs, body hash, occurrence range), so the CS300 estimate
  of about 100 MB is roughly right, provided no folded reading lists go in.
- R3 narrows. The model still joins `filename_readings` to derive document facts, so M2 should
  still measure that join, projecting typed fields rather than carrying folded lists.
- R10 is now required (decision 3).

## Findings

### R1 (major): appends will conflict with Basin's maintenance commits, and the design says conflicts fail

**Evidence**
- §5 says every commit carries its requirements "so concurrent writers fail rather than
  overwrite" (lines 147-148).
- §5.4 enables Basin compaction and snapshot expiration (lines 192-194). Both commit new
  snapshots to the same tables, so a daily append can lose the race to a maintenance commit and
  fail the job.
- Plain appends already send `UuidMatch` and `RefSnapshotIdMatch` (iceberg
  `transaction/snapshot.rs:518-526`), and docspec passes them through outside the detached path
  (`catalog.rs:1355-1362`). So plan M1.1's test, where the second of two appending writers is
  refused, passes today. ss-om9p fixes `replace_baseline_snapshot`, which belongs to the
  lifecycle store the target deletes.

**What is missing is retry, and it must not be blind.** If two ingest runs (scheduled and
manual) append the same receipts, re-applying the same files after a conflict duplicates rows.
That breaks §5.1's "a retried append cannot duplicate".

**Recommendation**
- On a commit conflict, reload the table, recompute the work list (the anti-join) from the new
  snapshot, write only what is still missing, and retry a bounded number of times.
- Files from the losing attempt become orphans, which §5.4 already reports.
- Re-aim M1.1 at this. Run one test with an append racing a Basin compaction, and one with two
  ingest runs on the same receipts that must end with exactly one copy of the rows.

### R2 (major): no per-source detail in the browser files, and the `detail` size leaves out the readings

**Evidence**
- §6.2 defines four files keyed by document (lines 232-237). `detail` is meant to hold "readings
  fields", but the 100 MB figure comes from `measurements/build_list.py`. Its detail query
  selects only IDs, URLs and body keys: no readings, no `fact_alternatives`.
- The site today has a per-source detail view with filename readings: `exportDetail` reads a
  source row (`catalog-v6.ts:322-326`), and deep links carry 64-hex source IDs
  (`catalog-v6.ts:111`). §6.2 routes deep links through `document_id` only.
- Filename readings are the largest data. My earlier measurement found 39.6M non-null reading
  cells, 385 MB in long form (that included copied provenance columns).

**Recommendation**
- Decide whether per-source pages survive. If they do, add `sources.parquet`: 1.68M rows,
  ordered by document list row so each document's sources are contiguous, with
  `src_start`/`src_count` in `detail` as for occurrences. It carries the folded filename readings
  and per-source fields, and has its own small ID file if source deep links stay.
- Measure it, with readings, in F0 and M2. If source links go, that is a product change; record
  it as one.

### R3 (major): the week-one performance decision rests on a proxy that leaves out the widest data

**Evidence.** §2 and §12 cite "3.7 s proxy" and "Seconds" (lines 61-63, 400). `model_proxy.py`
computes `url_state` with 6 columns and readings with 7 typed columns. It has no filename
readings, no 4.7M occurrences and no per-source rows. In my earlier run, unpivoting and sorting
the filename readings took 30.6 s with about 10 GB peak footprint in DuckDB.

In DataFusion, joining source rows to `filename_readings` builds a hash table holding the folded
lists. A hash-join build does not spill, so §9.6's "spill or fail clearly" will mean "fail".

**Recommendation.** M2 should export `detail` (with readings), `occurrences` and `sources` from
the pinned snapshot on `ubuntu-24.04` with an explicit pool, and report the join's build size.
Join on keys first, then attach the folded column, or put `filename_readings` on the probe side.
The 3.7 s figure should not decide track C's size on its own.

### R4 (major): the engine's export would disable the page reads `detail` and `ids` depend on

**Evidence.** `build_writer_properties` disables the offset index whenever no page-index columns
are named, and writes page-level statistics only for named columns, with 16 KiB pages
(`docspec-rs/src/engine/export/pipeline.rs:687-697`). Without an offset index on every column it
reads, hyparquet falls back to reading whole column chunks (`hyparquet/src/plan.js:143-153`). The
CS300 `detail` variants used 1M-row row groups, so a fallback would read tens of MB per view.

**Recommendation.** State the per-file writer settings in C3, and have the F0 converter use the
same settings, so the reader is not tuned on files the engine won't produce:

| File | Offset index | Column index (page statistics) | Pages |
|---|---|---|---|
| `detail` | every column | not needed | row limit about 256, with `write_batch_size` ≤ that |
| `ids` | yes | page statistics on the ID column | small pages |
| `list` | not needed | not needed | default |

### R5 (minor): a cold detail read takes two round trips, not one

§6.2 says one round trip (lines 243-245). hyparquet fetches the offset index ranges first, then
the pages (`plan.js:143-163`). Have the reader fetch `detail`'s whole offset index once (about
150 KB at 10k pages) and pass `pageLocations`. Each later view is then one round trip. This
belongs in plan A1.

### R6 (minor): the early skip ignores provenance and code changes

§6.4 stops when "ingest appended nothing and the work lists were empty" (lines 276-277). A new
review decision, recovery or SQL change would then not publish until the next capture. Key the
skip on the inputs the manifest already records: lake contents, provenance digest, and SQL,
engine, parser and catalog versions. Describe lake contents by high-water marks or row counts,
not snapshot IDs: Basin compaction changes snapshot IDs without changing content.

### R7 (minor): releases cannot be reproduced after expiry

The manifest records lake snapshot IDs (lines 284-287), and Basin expires them after 30 days.
Also record the last receipt key per family and the row counts per parser version.

### R8 (minor): partition readings by parser and version, and define "complete"

§5.2 partitions by parser only (line 162) but serves "the newest complete version" while
backfills append a new one (lines 175-176). Partition by `(parser, parser_version)` so the model
prunes other versions at manifest level. Define "complete" in SQL: the version's work list is
empty.

### R9 (minor): the determinism list is missing the write chunking

§6.3 is good. Add one rule: rechunk the stream into fixed row counts and flush row groups on row
count only, since today's export also flushes on encoder memory (`pipeline.rs:607-616`). M2
varies threads and input order; it should also vary `batch_size` and force one spill.

### R10 (required by owner decision 3): decoding `list` costs browser memory before it costs download

The current reader decodes into objects (`parquetReadObjects`). For 1.24M rows, my rough
estimate is a few hundred MB of JS heap. That ceiling arrives before §6.2's 40 MB download
ceiling (lines 250-252). Decode column by column into arrays and dictionary codes in the worker.
The Node canary runs the same reader module, so have it record heap after decoding `list` and
fail above a budget. Set the budget from the first F0 measurement plus a margin, sized for a
mid-range phone.

### R11 (minor): the "16 MB" grouping figure understates the step

The parent array is 16 MB (lines 224-226). Assigning dense IDs to about 4M string or binary
node keys is a hash aggregation of a few hundred MB. That is still fine, but don't size the
pool from 16 MB.

## Verified as fine

- **Binary IDs work with hyparquet lookups.** `$eq` compares bytes (`utils.js:58-63`), and pruning
  uses unsigned byte order (`filter.js:200-213`), so `ids` with a binary key, `filter` and
  `usePageIndex` work.
- **Release caching.** Per-release prefixes are already marked immutable at the edge
  (`infra/cloudflare/congressional-data-r2-edge.json:71`), so my earlier m5 no longer applies.
- **Basin rewrites lose no rows.** docspec's retained-file filter is computed per run from the
  current snapshot (`engine/aggregation.rs:800-835`, `storage/occurrences.rs:119-123`), so
  Basin's rewritten files are not silently dropped.
- **Earlier review findings now in the design:** dropping replace and tags, sizes from table
  properties, no Bloom filters, footers under 512 KB, unique sort keys, and byte comparison
  across thread counts.

## Plan changes, in one place

| Step | Change |
|---|---|
| M1.1 | Test conflict-and-retry (R1), not refusal; ss-om9p goes with the lifecycle store |
| M2 | Include readings, occurrences and per-source rows; report the join build size; vary batch size and force a spill (R2, R3, R9) |
| F0 | Use C3's writer settings, including offset indexes (R4); short IDs in `ids`; typed document facts only in `detail` (decisions 1, 2) |
| A1 | Cache `detail`'s offset index; decode `list` column by column; canary heap budget (R5, R10, decision 3) |
| A2 | Deep links carry the 16-hex document ID; retire source-ID links (decisions 1, 2) |
| C3 | Per-file offset-index and page settings (R4); fixed-row rechunking (R9) |
| D2 | Partition `readings` by `(parser, parser_version)` (R8) |
| §6.4 | Early-skip key and input high-water marks (R6, R7) |
