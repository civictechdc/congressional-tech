# Engine-first architecture

Status: proposed, revision 5, 2026-10-24. Owner: Mike Deeb. This document describes the
target system as it should be, independent of how the current code works. The path from
today is in `docs/plans/simplification-plan-20261024.md`, and the appendix summarizes it.

## Summary

congressional-tech captures congressional source documents, keeps them forever, and
publishes a fast public explorer over them. The ideal system has three layers, and only
the first is precious:

1. **Raw log.** An append-only, content-addressed record of every fetch attempt, every
   body and every human decision. It is never rewritten.
2. **Lake.** Three append-only engine tables derived from the log: what was captured,
   what each body says, and what each filename says. Each row is computed once.
3. **Releases.** Immutable Parquet produced by one deterministic SQL job over the lake. A
   single pointer selects the live release.

docspec-rs does all the data work. congressional-tech supplies fetchers, parsers,
declarative SQL and the site.

## 1. Principles

1. **Raw is the only truth.** Everything else is a pure function of raw data plus
   versioned code, SQL and engine, and can be rebuilt at any time.
2. **Append or replace, never update.** Logs only grow. Derived outputs are recomputed and
   swapped atomically. No row is edited in place. (Catalog compaction rewrites files, not
   rows.)
3. **Do each thing once.** Every body is fetched, stored, hashed and parsed once per
   parser version. Every per-item computation, such as parsing a body or reading a
   filename, has a lake table keyed by its inputs, so it never runs twice. Platform
   primitives (content addressing, conditional writes, Content-MD5, ETags, catalog
   commits) replace hand-built bookkeeping.
4. **Cost grows with change, not with history.** Recurring jobs do work in proportion to
   what is new. Where a whole-collection pass is unavoidable, it reads listings or
   metadata, never bodies.
5. **Engine first.** Data movement, joins, grouping, aggregation and export live in
   docspec-rs. Application policy is passed in as SQL and specs, never compiled into the
   engine.
6. **Nothing reaches users unverified.** A release goes live only after the site's own
   reader code has loaded it.
7. **Small bytes.** Store keys and facts once, as typed columns, with hashes as binary.
   Never copy provenance into derived rows, and never store what can be derived. Browser
   files are the one place shape follows the reader instead (section 6.2).

## 2. Scale

Measured on the Oct 19 snapshot (CS300 review, section 0):

| Quantity | Measured |
|---|---|
| Fetch attempts (capture rows) | 3.9M, in 2,289 receipt files |
| Distinct bodies | 1.04M, 0.70 TB stored (PDF 365 GB, ZIP 286 GB, untyped 37 GB, HTML 4.5 GB, XML 0.8 GB) |
| Distinct URLs | 1.16M |
| Source files, documents, occurrences | 1.68M, 1.24M, 4.7M |
| Normal day | 270–3,553 attempts, 258–1,595 new bodies |
| Import day | up to 745k attempts, 547k new bodies |
| Largest body | 1.19 GB; none above 5 GB |

At this scale, recomputing the model from the lake is cheaper and simpler than
maintaining it incrementally. A DuckDB proxy of the narrow relational plan ran in 3.7 s
with 1.75 GB of memory, and connected components over the real 4M-node graph took 1–2 s
in plain Python. The proxy left out the wide data (filename readings, occurrences), so the
week-one measurement includes it (appendix, step 1). The only per-item work that must not
be repeated is fetching, parsing bodies and reading filenames.

## 3. System overview

```
fetchers, recovery imports, review tools
        │  create-only writes
        ▼
RAW LOG (one bucket; locked prefixes)
  bodies/sha256/<aa>/<sha>                    stored bytes, keyed by SHA-256 of the original
  receipts/<family>/<write-date>/<run>.jsonl.gz   one line per fetch attempt
  provenance/<kind>/<ts>.jsonl                human and reviewed decisions
        │
        ▼  docspec-rs, Basin Catalog
LAKE (Iceberg, append-only)
  captures           one row per attempt                        O(new receipts)
  readings           one row per (body, parser, version)        O(new bodies in scope)
  filename_readings  one row per (filename, URL, catalog)       O(new pairs)
        │
        ▼  docspec-rs: one SQL plan, deterministic export
RELEASE (immutable)
  viewer-publications/releases/<release_id>/<file>.parquet
  viewer-publications/releases/<release_id>/manifest.json
  viewer-publications/manifest.json   ← If-Match pointer, flipped after the canary
        │
        ▼
SITE (static) → pointer → release → list (whole) / detail, links, occurrences (ranges)
```

## 4. Raw log

### 4.1 Bodies
- **Key:** `bodies/sha256/<aa>/<sha>`, where `sha` is the SHA-256 of the original response
  bytes.
- **Stored bytes.** Media types that compress (HTML, XML, JSON, text) are stored
  gzip-compressed, with `Content-Encoding: gzip` and the original `Content-Type`. Already
  compressed types (PDF, images, archives) are stored as-is. Either way, any HTTP client,
  including a browser opening a saved copy, receives the original bytes.
- **Two digests, each with one job.** The original's SHA-256 is the identity; anyone who
  decodes the body can check it. The stored bytes' MD5 is the integrity check; R2 verifies
  it on upload and returns it as the ETag. A third digest of the stored bytes would add
  nothing.
- **Write:** one create-only PUT (`If-None-Match: *`) with Content-MD5. Never multipart:
  R2 documents conditional writes for single PUTs, multipart ETags aren't MD5s, and no
  body comes near the 5 GB single-PUT limit.
- **A 412 means the body already exists.** The writer records the attempt as `unchanged`
  and moves on, with no HEAD and no comparison. The object was verified when it was
  created, and the weekly check compares it with the receipt line that created it. Over
  half of body-bearing attempts hit an existing body, so this path must cost nothing.

### 4.2 Receipts
- One immutable file per fetch run, keyed by its UTC write date. Each line records:
  - requested URL, final URL, time, HTTP status and outcome (stored, unchanged, failed,
    retry-later);
  - body SHA-256, the server's media type, the format sniffed from the body's first
    bytes, and, for `stored` lines, the stored MD5 and size;
  - an allowlisted set of response headers (never cookies or authorization);
  - writer identity: job, code commit and lockfile digest.
- Receipts are the authoritative history of what was captured and when.
- Written create-only after the run's bodies, so every receipt line points at a body that
  exists.
- **Older receipts** also sit under non-date segments (`undated/`, `mixed-dates/`; 49
  files, 2.2M rows). New writers never use them.

### 4.3 Provenance
- **Contents:** every decision a person or a reviewed process makes about sources, such as
  accepted URL variants, recovery bases and document review decisions, as append-only,
  timestamped records.
- **Corrections are new records** that supersede old ones by ID. Old records are never
  edited.

### 4.4 Protection and verification
- **Lock.** An R2 bucket lock (indefinite) on `bodies/`, `receipts/` and `provenance/`.
  Writers hold only create permission in practice.
- **Weekly check.** One LIST of `bodies/`, joined to `captures` on key, size and ETag for
  the line that stored each body: every receipt-referenced body exists, and every stored
  body has the size and MD5 its creating line recorded. That is about 1,000 list requests
  and no body bytes. HEADs would add a million requests a week and find nothing the ETag
  doesn't already show.
- **Sample.** The weekly job also downloads 25 random bodies and checks their SHA-256 end
  to end, which exercises the read and decode path. There is no daily re-hash: at 0.5% a
  day it re-read 1.8 times the corpus per year to catch what R2 already verified.
- **Full re-hash** is an explicit job. It runs once for bodies written before receipts
  carried an MD5, and records their ETags as a verification baseline under
  `provenance/verification/`. After that it runs only before a migration.

## 5. Lake

All three tables are Iceberg tables in the bucket's Basin Catalog (formerly R2 Data
Catalog), the managed Iceberg REST catalog. Every commit carries its requirements (table
UUID and current snapshot), so concurrent writers fail rather than overwrite each other.

**Conflicts are retried by recomputing, never by re-sending.** Basin's own maintenance
commits to the same tables, so an append can lose a race. On a conflict the writer reloads
the table, recomputes its work list (the anti-join) against the new snapshot, writes only
what is still missing, and retries a bounded number of times. Re-sending the losing files
could duplicate rows when two runs ingest the same receipts. Files from a losing attempt
become orphans (5.4).

### 5.1 `captures`
- **Rows:** one per fetch attempt. Unique on `(receipt_key, receipt_line)`, sorted by
  `(url, attempt_seq)`, with hashes as binary. No derivable columns. A compact form
  measured 157 MB for all 3.9M rows and 315 KB for a normal day.
- **Ingest:** for each receipt family, list only date-shaped prefixes, starting from the
  newest date already ingested; anti-join against ingested receipt keys; append the
  missing ones in one commit. Listing cost grows with new receipts, not with all of them.
- **Backfill and late receipts.** The non-date segments are read once by the backfill.
  The weekly check lists everything and appends anything a late receipt left behind.
- **Rebuild check:** rebuilding from all receipts reproduces the same set of rows.

### 5.2 `readings`
- **Rows:** one per `(body_sha256, parser, parser_version)`, partitioned by
  `(parser, parser_version)` and sorted by body hash. Each media family has its own parser
  and version, so a new HTML parser never re-reads a PDF, and the model prunes other
  versions from the manifests.
- **Columns:** a narrow typed core (title, page count, format) plus one folded
  `List<Struct<field, values>>` for everything else. Large text goes in its own table if
  it's needed.
- **Scope**, declared in the model SQL:
  - HTML, XML and JSON: full readings. A backfill reads about 5 GB.
  - PDF: only the fields the browser shows (title, page count). A backfill reads about
    335 GB, so the PDF parser changes rarely and backfills run in the background.
  - ZIP containers, captions and untyped bodies (74k bodies, 37 GB): none. ZIP members are
    captured as their own attempts.
  - Every body has a sniffed format: the one its receipt or older capture row recorded,
    or, where none was recorded, one ranged read of its first bytes during the backfill.
    The grouping rule (6.1) depends on it.
- **Work list:** an anti-join on `(sha, parser, parser_version)`. A daily run appends once.
  A backfill appends once per batch, so it always resumes.
- **New parser versions** are backfilled in background batches. A version is complete when
  its work list is empty. The live release uses the newest complete version of each
  parser.

### 5.3 `filename_readings`
- **Rows:** one per `(filename, source_url, catalog_version)`, holding the folded fields
  that `packages/house-naming` extracts.
- **Why a table.** Filename readings depend on the filename and the source URL, not on the
  body, so they can't live in `readings`. Recomputing them every run would cost about 9
  CPU-minutes a day (0.31 ms each over 1.68M source files) and put a Python pass inside the
  model.
- **Key.** The full source URL, not the host, because the catalog qualifies 71 exact
  mirror URLs. The filename is part of the key because 32,574 source files have a filename
  that isn't their URL's last segment. `catalog_version` covers every vocabulary the
  producer passes in, such as member surnames if they are ever used.
- **Work list:** pairs in `captures` that have no row for the current catalog version.
  Daily cost is under a second. A new catalog version is one background job of about 7
  minutes over 1.39M pairs.
- **Scope in releases.** The model uses each document's representative reading. Per-copy
  readings stay in the lake.

### 5.4 Maintenance
- **Basin Catalog maintains the tables:** compaction (target 128 MB) and snapshot
  expiration (older than 30 days, keep the last 5), enabled per table. Expiration also
  deletes the data files that only expired snapshots referenced. Compaction is a paid Basin
  feature; at about 315 KB of appends a day, its volume is a few GB a month at most.
- **Orphans.** Basin doesn't remove files that no snapshot ever referenced, such as the
  data file of a lost commit race. Those are rare and small. The weekly check reports their
  bytes; cleanup waits until that number matters.
- **To confirm before building on it:** that compaction keeps the number of manifests in
  the current snapshot bounded (appendix, step 1). If it doesn't, the logs move to the
  fallback in section 13.

## 6. Model and release

### 6.1 Model
- The domain model is versioned SQL in the application repo.
- One docspec-rs job registers `captures`, `readings`, `filename_readings` and the
  provenance records, evaluates the plan, and writes every output as a release file.
  There are no intermediate tables.

| Output | Content |
|---|---|
| `url_state` | Latest outcome and retry schedule per URL |
| `filenames` | One row per source file: a `(body, filename, source URL)` triple, whose SHA-256 is `source_id` |
| `documents` | Source files grouped by the engine's ConnectedComponents; `document_id` is the SHA-256 of the sorted body set, or of the sorted source IDs when there is no body |
| `members` | `(document_id, source_id)` |
| `recoveries`, `reviews` | Resolved from provenance and captures |

- **ID formulas** keep today's exact inputs, including the logical body key string
  `bodies/sha256/<aa>/<sha>.gz`, whatever the physical key. IDs then match the pinned
  catalog wherever the grouping agrees.

- **A document is a group of source files** the model treats as one document. Source files
  connect through identical document bodies and through shared canonical endpoints
  (filename plus URL); connections chain.
- **A document's files are real files only:** 2xx responses whose sniffed format is the
  document's own type (PDF, ZIP, XML, JSON or video playlist, and HTML only for documents
  that are web pages). The classification uses the sniffed format and the receipt's HTTP
  status and outcome, never the server's `Content-Type`, which mislabels error pages.
  Error and "retry later" pages stay in raw and `captures` as evidence. They never enter a
  document's body set, so they never change its ID, its saved file or its links. On the
  Oct 19 data, most documents with several bodies were a real ZIP or PDF beside a govinfo
  503 page (25,236 such pages, unique bytes per URL); real multi-version documents number
  about 320.
- **Grouping rule.** The edge set is SQL and is written down before anything is compared
  with the old catalog. Only real files connect, and two kinds of real file connect
  nothing:
  - placeholders: any body seen at more than *k* = 100 URLs. One error page sits at 87,161
    URLs and, unchecked, glues together 174,323 source files. Measured: any *k* from 50 to
    200 excludes the same dozen placeholder bodies;
  - HTML bodies. HTML is pages, not files. Shared listing and landing pages glue unrelated
    sources, so identical HTML at two URLs stays two documents, by intent.

  With these rules the real graph gives about 1.26M documents, and the largest has 456
  source files.
- **Representative file.** Each document names one representative saved file, chosen in
  SQL by a fixed rule with logical tie-breaks only, never physical file order, so every run
  picks the same one. The page links that file. The other versions of the roughly 320
  multi-version documents stay in R2, unlinked; `document_id` still covers them all.
- **Grouping runs in memory** over 32-bit IDs and refuses above a configured node count.
  The parent array is 16 MB at 4M nodes. Assigning dense IDs to the node keys is a hash
  aggregation of a few hundred MB, which sizes the memory pool. Spilling would be wasted
  machinery below about 100 times today's scale.

### 6.2 Release files
They're derived from the model outputs in the same job. The site reads four of them, and
the list row number links them.

| File | Order | Contents | Read pattern | Writer settings |
|---|---|---|---|---|
| `list.parquet` (about 4 MB) | `(filename, document_id)` | Display name and facet fields; no ID | Downloaded whole, decoded column by column in a Web Worker | Defaults; no page index |
| `detail.parquet` | Same row order as `list` | One folded `List<Struct<field, value>>` per row of document-level facts: representative original URL, representative saved file (key, media type), the document's readings, occurrence row range | One page per leaf column, located by the offset index | Offset index on every column; pages of about 16 KB or 256 rows, with the write batch no larger |
| `links.parquet` (about 14 MB) | `link_key` | 8-byte link key and list row | Point lookup via the column index | Offset index and page statistics on `link_key`; small pages |
| `occurrences.parquet` (about 30 MB) | `(list_row, ordinal)` | Where each copy was seen: URL, filename, capture date | The range named in `detail` | Offset index on every column |
| `url_state.parquet` (about 40 MB) | `url` | Latest outcome and retry schedule per URL | Read whole by the capture job, not the site | Defaults |

- **Documents only.** There are no per-copy pages. A document page shows its
  representative file, its readings and where each copy was seen.
- **Links point at a file.** A document's ID changes whenever a version joins its group.
  A file's fingerprint never changes. So a public link carries `link_key`: the first 8
  bytes (16 hex characters) of a body's SHA-256. `links.parquet` maps every real file of
  every document to that document's row, so old links keep resolving when the group or its
  representative changes. Error pages are never keys. A document with no saved file uses a prefix of its
  `document_id`. An HTML body shared by two documents resolves to the first in list order.
  The export refuses if two keys collide.
- **No ID in `list`.** Measured on the real documents: 4.05 MB without an ID, 15.8 MB with
  an 8-byte ID and 45.9 MB with hex IDs.
- **Detail reads.** hyparquet reads single pages when a file has an offset index
  (`useOffsetIndex`, 1.31.2). The reader fetches `detail`'s offset index once per session.
  After that, a detail view is one round trip of about 3 page reads, about 20–30 KB. A flat
  layout would be about 9 page reads and about 82 KB, because Parquet stores each column,
  and each field of a flat struct, as its own chunk; the folded list has only a few leaf
  columns.
- **Binary keys** everywhere else. Hex hashes were 160 of 187 MB in a measured flat detail
  file.
- **Shards.** `detail` and `occurrences` can be split into fixed row-range files, which
  the manifest lists with their row ranges. There is one shard today. The export adds
  shards when an offset index outgrows a quick first fetch, at roughly 10 times today's
  rows.
- **Ceiling.** At about 10 times today's documents, `list` reaches 40 MB and downloading
  it whole stops being reasonable. Then `list` is sharded by facet, or search moves to
  DuckDB-WASM or a server.

All release files share these settings:
- Parquet 2.0 data pages and ZSTD;
- fixed row counts per row group, flushed on row count only;
- chunk statistics;
- footers under 512 KB, so one request reads metadata;
- no Bloom filters.

Unfiltered facet counts go in the release manifest.

### 6.3 Determinism
- Identical inputs produce byte-identical files. That makes reruns idempotent and the
  "nothing changed" check exact.
- **The engine enforces it:**
  - every sort key must be unique, or the export refuses;
  - partition order is fixed;
  - row groups hold fixed row counts, whatever the batch sizes or spills;
  - writer properties and the `created_by` string are pinned;
  - no timestamps or run-specific values go into content.
- **Tests:** compare bytes across thread counts, input orders and batch sizes, and with a
  forced spill.
- **Not a dedupe mechanism.** One new document shifts every later row number, so on any
  day with a change, every file changes. That is about 150 MB of uploads a day, which is
  fine.

### 6.4 Release and publish
- **Input identity.** Every publish run computes it before doing any work:
  - the digest of ingested receipt keys;
  - row counts per `(parser, parser_version)` and per filename catalog version;
  - the provenance digest;
  - the SQL, engine, parser and catalog versions.

  It uses content high-water marks, not snapshot IDs, because a Basin compaction changes
  snapshot IDs without changing content.
- **Early skip.** If the input identity equals the live release's, publish stops before
  the model runs. A review decision or a SQL change therefore publishes without waiting
  for a capture.
- **Release ID.** The SHA-256 of the file list (name, SHA-256, size, rows) and the schema
  version. It is computed after export and before upload. If it equals the live release's,
  publish records the new input identity and stops.
- **Files.** Uploaded to `viewer-publications/releases/<release_id>/` with a create-only
  PUT and Content-MD5. A 412 on a rerun is checked against the expected MD5.
- **Manifest.** `releases/<release_id>/manifest.json` holds only content: each file (name,
  SHA-256, MD5, size, rows, row range, schema version) and the facet counts. It is
  deterministic, so a release that re-emerges writes identical bytes.
- **Inputs.** `releases/<release_id>/inputs/<input_digest>.json` records the input
  identity, the last snapshot IDs and the run. A release produced from several input sets
  has several input records.
- **Canary.** The site's own reader module runs in Node against the uploaded candidate over
  HTTPS, so Range reads and caching headers are real. It decodes `list` within a heap
  budget for a mid-range phone, runs a search and a facet count, reads the first, last and
  a random detail, resolves a link, reads an occurrence range, opens one saved copy, and
  checks that `url_state` decodes. It takes under a minute and needs no headless browser.
- **Flip.** `viewer-publications/manifest.json` is updated with `If-Match` on its current
  ETag. A failed canary or a lost race leaves the previous release live.
- **Caching.** Release files and manifests are cached as immutable; the pointer is
  `no-store`.
- **Retention.** Keep the last 10 releases plus any listed in
  `viewer-publications/pinned.json`. The weekly job deletes older release prefixes.
  Releases share no files, so nothing needs reference counting.

## 7. Site

- **Reads:** pointer → release manifest → `list`, `detail`, `links` and `occurrences`.
  Search and facet filtering run in a Web Worker over `list`, decoded column by column into
  arrays and dictionary codes, because objects would cost hundreds of MB of heap on a
  phone. Details and lookups use HTTP Range reads.
- **Devices:** desktop and mid-range phones. The contract test and the canary enforce the
  heap budget.
- **One reader.** The reader is a plain module with no DOM dependency, so the canary runs
  the same code the site ships.
- **Contract:** the manifest carries a `schema_version`. The reader accepts the current and
  the previous version, so format changes ship reader-first, then publisher.
- **Saved copies:**
  - bodies written to the design in section 4.1 open directly;
  - older gzip PDFs have a one-time uncompressed copy at `bodies/sha256/<aa>/<sha>.pdf`,
    which opens directly;
  - other older gzip bodies are fetched and unpacked by the site with the browser's
    `DecompressionStream`, then opened with the media type from `detail`.
- **Origin:** `congressional-data.spicygov.ai` serves the bucket directly, with a
  read-only, any-origin CORS policy (GET/HEAD, Range).

## 8. Orchestration

```
capture:     live url_state → fetchers → bodies → receipts           (daily; network-bound)
publish:     captures → readings, filename_readings → model + export
             → canary → flip → status                                 (after capture, or on demand)
maintenance: raw check and sample → release retention → orphan report (weekly)
backfill:    readings or filename_readings for a new version          (on demand)
```

- **Idempotent steps.** Each step is keyed by its input and is a no-op when that hasn't
  changed. Each step commits durably, so a failed run resumes by running again. There are
  no journals.
- **Capture reads the public release.** It builds its queue from the live release's
  `url_state`, so it needs no lake or release credentials. If a canary has failed, capture
  works from a slightly older schedule, which is safe because body writes are create-only.
- **Separate credentials.** Capture, publish and maintenance run as separate jobs with
  separate credentials.
- **Pinned engine.** The engine binary is pinned by revision and digest, checked before any
  storage access.
- **Resources.** Resource limits are explicit per runner class (threads, memory pool,
  scratch). The memory pool never exceeds the machine.
- **Status.** Every publish run writes `viewer-publications/status.json`: input identity,
  rows per output, durations, bytes and the live release.
- **Local runs.** The same commands run locally or in CI. Correctness never depends on a CI
  feature.

## 9. docspec-rs: the engine this needs

**Capabilities**
1. **Multi-input SQL plans** over Iceberg tables in Basin Catalog and Parquet files, in one
   DataFusion context.
2. **Append** through the REST catalog, always sending commit requirements, with the
   conflict retry in section 5.
3. **Deterministic multi-file export:** SHA-256 and MD5 computed while writing; per-file
   writer settings, including offset and column indexes and page sizes; fixed row counts per
   row group; row-range shards; and the rules in section 6.3.
4. **ConnectedComponents** in memory over 32-bit IDs, refusing above a configured node
   count.
5. **Streaming I/O.** No re-read of a just-written object and no HEAD of immutable files.
   File and row-group sizes come from table properties.
6. **Bounded resources** set by configuration: compute threads, memory pool and scratch
   space. Sorts and aggregates spill or fail clearly within the pool. Hash-join builds
   don't spill, so plans keep wide folded columns off the build side: join on keys first,
   then attach the wide column.
7. **A thin interface:** a library plus a CLI that runs a declarative job spec (inputs,
   SQL, outputs, export settings) and returns a machine-readable result.

**Non-capabilities.** These are deliberately out of scope:
- application policy (ID formulas, field names, the grouping rule);
- parsers, which belong to the application, whether for bodies or filenames;
- table maintenance, which Basin Catalog does;
- bookkeeping that duplicates Iceberg (Iceberg snapshots are the history);
- resume machinery beyond per-step commits;
- test-only production paths.

**Library.** Iceberg is used only to read and append. If replace or branching is ever
needed, add it upstream to iceberg-rust rather than working around it.

## 10. Security

- **Raw:** create-only writers, plus the bucket lock on raw prefixes.
- **Credentials:** capture holds raw create rights only. Publish holds raw read, lake write
  and release write. Maintenance holds raw read and release delete.
- **One-bucket trade-off.** With one bucket, R2 tokens can't be scoped per prefix (to
  confirm), so raw isolation rests on the lock plus writer allowlists. A separate bucket
  for releases would add credential-level isolation; the owner chose one bucket.
- **Public data.** Everything stored is public records and is readable publicly.
- **Receipts:** allowlisted headers only.

## 11. Verification

1. **Raw invariants:** the weekly LIST joined to `captures` (key, size, MD5 of the creating
   line), the weekly 25-body sample, and the one-time baseline for older bodies.
2. **Lake rebuild equivalence:** `captures` rebuilt from all receipts equals the appended
   table.
3. **Determinism:** byte-identical exports across thread counts, input orders, batch sizes
   and a forced spill.
4. **Contract:** CI builds a release from a fixed sample of real receipts and loads it
   through the real site in a headless browser, within the heap budget.
5. **Canary:** the reader module in Node, against the uploaded candidate, before every
   flip.
6. **Production parity:** no test-only branches in production code, enforced by a ratchet
   test.

## 12. Performance

| Step | Cost | Expected |
|---|---|---|
| Capture | O(new attempts), network | Bounded by politeness to sources |
| Captures ingest | O(new receipts) | Seconds |
| Readings | O(new bodies in scope × parse cost) | Minutes daily; backfills in background |
| Filename readings | O(new pairs) | Under a second daily; about 7 minutes per catalog version |
| Model + export | O(N log N) over about 8M rows | Seconds for the narrow plan (3.7 s proxy; grouping 1–2 s); the wide joins are measured in week one |
| Publish | O(release size) | About 150 MB on a day with changes |
| Detail view | One page per leaf | About 20–30 KB in one round trip, after one offset-index fetch per session |
| Weekly check | O(bodies / 1,000) list requests | About 1,000 requests, no body bytes |

A normal day moves about 1,500 object operations and 2 GB, well inside R2's free tier at
today's scale and at 10 times it.

**Validate before building on it,** in docspec-rs on the smallest production runner class:
1. full model-and-export time and peak memory, including filename readings, the folded
   `detail` and `occurrences`, with the size of every hash-join build;
2. ConnectedComponents on the real graph, with the grouping rule;
3. join behavior at the memory pool limit;
4. export determinism, including batch sizes and a forced spill;
5. Basin Catalog: an append that races a compaction retries correctly, two ingest runs on
   the same receipts leave one copy of each row, and the manifest count stays bounded under
   compaction.

## 13. Alternatives considered

| Alternative | Why not |
|---|---|
| Incrementally maintained model (keyed merges) | Recompute measured in seconds. Copy-on-write rewrites every touched file, and hashed keys touch nearly all of them. |
| Model as Iceberg tables replaced each run | It works only with a safe overwrite. Releases already give immutability, history and atomic switching without it. |
| No Iceberg (dated Parquet plus an `If-Match` manifest per log) | **The fallback.** Same atomicity with fewer moving parts, but no time travel and new engine code. Iceberg stays because the engine already writes it and Basin Catalog maintains it. Switch if Basin's compaction leaves manifests growing. |
| A general-purpose engine (DuckDB, Spark) in place of docspec-rs | Comparable query power, but it gives up the engine-first decision and docspec-rs's export and grouping operators. |
| Per-copy pages with a `sources` file | Declined by the owner: documents only. |
| Links by `document_id` | The ID changes whenever a version joins the group, so links would rot. File fingerprints don't change. |
| Row-group-granular reads (small row groups, no page index) | The footer grows with the row-group count: under a 512 KB footer a single-file `detail` costs 0.6–1 MB per view. The offset index gives page reads. |
| Content-addressed objects shared between releases | Saves nothing on a day with any change, since every file changes, and needs a reference-counting sweep. |
| Spilling or partitioned ConnectedComponents | The parent array is 16 MB today and about 160 MB at 10 times. The real risk is giant components, which the grouping rule handles. |
| HEAD-per-body verification and a daily re-hash | Work that grows with history (a million HEADs a week, 1.3 TB of re-reads a year) to find what an ETag comparison finds. |
| Uncompressed copies of every older body, or an edge Worker | Copying all 0.70 TB would cost about $126 a year forever under the lock. Text-like bodies are small and unpack in the browser; only PDFs get copies. A Worker is one more deployed part. |
| One combined browser file | Point reads need small pages and the whole download needs a small file; one file can't have both. |
| DuckDB-WASM in the browser | Several MB of runtime for no gain at today's size. Worth revisiting at 10 times, when `list` outgrows a whole download. |
| Separate bucket for releases | Stronger isolation; declined by the owner. |

## 14. Open decisions

1. **PDF readings:** title and page count, or nothing. Each new PDF parser version re-reads
   about 335 GB.
2. **Representative file rule:** written with the grouping rule (plan, step E1).
3. **Retention numbers:** releases kept and snapshot age.
4. **R2 token scoping:** confirm with current Cloudflare docs.
5. **news_lake** adopts the same three layers later; out of scope here.

Decided by the owner on Oct 24: one bucket; `r2.dev` open; documents only; links by file
fingerprint; 16-hex public keys; desktop and mid-range phones; one representative saved
file per page; only real files count as a document's files; hyparquet in the browser;
uncompressed copies of older PDFs only; no early launch on the converted Oct 19 release.

## Reviews

Five reviews shaped this design. All are in `docs/reviews/2026-10-24-design-review/`:
- of revision 2: a general architecture review (`fable-review.md`) and an Iceberg, Parquet
  and query-plan review (`iceberg-parquet-review.md`);
- of revision 3: an efficiency review with measurements on the real data
  (`cs300-efficiency-review.md`);
- of revision 4: re-reviews by both specialists (`cs300-rereview-rev4.md`,
  `iceberg-parquet-rereview-rev4.md`). The efficiency reviewer graded revision 4 A− (89),
  up from B+ (84).

Revision 4 applied the efficiency review (F1–F12). Revision 5 applies the two re-reviews
and the owner's decisions:

| Finding | Change in revision 5 |
|---|---|
| Detail reads mis-stated; engine export disables the offset index | Offset indexes per file, folded detail, offset index cached per session (6.2, 9) |
| Receipt listing would skip 15 of 21 families on `undated/` keys | Date-shaped prefixes only; non-date segments read by the backfill (4.2, 5.1) |
| A 412 had no defined handling | Record `unchanged`, no HEAD; weekly check uses the creating line (4.1, 4.4) |
| Appends collide with Basin maintenance | Retry by recomputing the work list (5) |
| Early skip ignored provenance and code; manifest held run inputs | Input identity from content high-water marks; content-only manifest; separate input records (6.4) |
| `url_state` missing from the release | Listed, and checked by the canary (6.2, 6.4) |
| Week-one test left out the wide data; hash joins don't spill | Wide joins measured; folded columns kept off build sides (2, 9, 12) |
| Determinism missing chunking | Fixed row counts per row group; batch sizes and spills tested (6.3) |
| `list` decoded as objects | Column-by-column decode, heap budget in canary and contract test (7) |
| Grouping rule and untyped bodies unspecified | *k* = 100 from measurement, HTML reason, untyped bodies out of scope (5.2, 6.1) |
| Owner decisions | Documents only, file links, representative file, real files only, older-copy handling (4.2, 5.2, 6.1, 6.2, 7) |

## Appendix: path from the current system

The raw log already exists (bodies, receipts, and provenance backed up on 2026-10-24) and
is preserved unchanged. Existing bodies keep their stored form; older gzip PDFs get
uncompressed copies.

The order is:
1. **Week one:** the bucket lock, the older-PDF copy job, and two measurements that decide
   the engine work: Basin Catalog commits under maintenance, and deterministic export plus
   grouping on the wide real data.
2. **Now, in parallel:** the release format, reader and canary, built against a release
   converted from the pinned Oct 19 catalog with the final writer settings. That release
   is the reader's fixture and the parity oracle. It does not go live; the explorer waits
   for the engine-built release.
3. The raw writer changes (MD5 in receipts, 412 handling, encoding, write-date keys) and
   the weekly check.
4. The engine capabilities in section 9.
5. The lake tables and their backfills.
6. The model SQL, checked against the pinned catalog on browser-visible fields.
7. Switching publishing, then deleting the old layers.

Estimated at 8–16 weeks for one engineer. Steps, estimates and tickets are in the plan.
