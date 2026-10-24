# Engine-first architecture

Status: proposed, revision 4, 2026-10-24. Owner: Mike Deeb. This document describes the
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
   swapped atomically. No row is edited in place.
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
   Never copy provenance into derived rows, never store what can be derived, and shape
   browser files around how the site reads.

## 2. Scale

Measured on the Oct 19 snapshot (CS300 review, section 0):

| Quantity | Measured |
|---|---|
| Fetch attempts (capture rows) | 3.9M, in 2,289 receipt files |
| Distinct bodies | 1.04M, 0.70 TB stored (PDF 365 GB, ZIP 286 GB, HTML 4.5 GB, XML 0.8 GB) |
| Distinct URLs | 1.16M |
| Source files, documents, occurrences | 1.68M, 1.24M, 4.7M |
| Normal day | 270–3,553 attempts, 258–1,595 new bodies |
| Import day | up to 745k attempts, 547k new bodies |
| Largest body | 1.19 GB; none above 5 GB |

At this scale, recomputing the model from the lake is cheaper and simpler than
maintaining it incrementally. A DuckDB proxy of the whole relational plan ran in 3.7 s
with 1.75 GB of memory, and connected components over the real 4M-node graph took 1–2 s
in plain Python. The only per-item work that must not be repeated is fetching, parsing
bodies and reading filenames.

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
SITE (static) → pointer → release → list (whole) / detail, ids, occurrences (ranges)
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
  body comes near the 5 GB single-PUT limit. A 412 means the body exists; the writer checks the
  ETag against its MD5 and moves on.

### 4.2 Receipts
- One immutable file per fetch run, keyed by its UTC write date. Each line records:
  - requested URL, final URL, time, HTTP status and outcome (stored, unchanged, failed,
    retry-later);
  - body SHA-256, stored MD5 and stored size, media type;
  - an allowlisted set of response headers (never cookies or authorization);
  - writer identity: job, code commit and lockfile digest.
- Receipts are the authoritative history of what was captured and when.
- Written create-only after the run's bodies, so every receipt line points at a body that
  exists.

### 4.3 Provenance
- **Contents:** every decision a person or a reviewed process makes about sources, such as
  accepted URL variants, recovery bases and document review decisions, as append-only,
  timestamped records.
- **Corrections are new records** that supersede old ones by ID. Old records are never
  edited.

### 4.4 Protection and verification
- **Lock.** An R2 bucket lock (indefinite) on `bodies/`, `receipts/` and `provenance/`.
  Writers hold only create permission in practice.
- **Weekly check.** One LIST of `bodies/`, joined to `captures` on key, size and ETag:
  every receipt-referenced body exists with the size and MD5 its receipt recorded. That is
  about 1,000 list requests and no body bytes. HEADs would add a million requests a week
  and find nothing the ETag doesn't already show.
- **Sample.** The weekly job also downloads 25 random bodies and checks their SHA-256 end
  to end, which exercises the read and decode path. There is no daily re-hash: at 0.5% a
  day it re-read 1.8 times the corpus per year to catch what R2 already verified.
- **Full re-hash** is an explicit job. It runs once for bodies written before receipts
  carried an MD5, and records their ETags as a verification baseline under
  `provenance/verification/`. After that it runs only before a migration.

## 5. Lake

All three tables are Iceberg tables in the bucket's Basin Catalog (formerly R2 Data
Catalog), the managed Iceberg REST catalog the engine already uses. Every commit carries
its requirements (table UUID and current snapshot), so concurrent writers fail rather than
overwrite each other.

### 5.1 `captures`
- **Rows:** one per fetch attempt. Unique on `(receipt_key, receipt_line)`, sorted by
  `(url, attempt_seq)`, with hashes as binary. No derivable columns. A compact form
  measured 157 MB for all 3.9M rows and 315 KB for a normal day.
- **Ingest:** for each receipt family, LIST from the newest date already ingested
  (`StartAfter`), anti-join against ingested receipt keys, and append the missing ones in
  one commit. Listing cost grows with new receipts, not with all of them. The weekly check
  lists everything and appends anything a late receipt left behind. A retried append
  cannot duplicate.
- **Rebuild check:** rebuilding from all receipts reproduces the same set of rows.

### 5.2 `readings`
- **Rows:** one per `(body_sha256, parser, parser_version)`, partitioned by parser, sorted
  by body hash. Each media family has its own parser and version, so a new HTML parser
  never re-reads a PDF.
- **Columns:** a narrow typed core (title, page count, format) plus one folded
  `List<Struct<field, values>>` for everything else. Large text goes in its own table if
  it's needed.
- **Scope**, declared in the model SQL:
  - HTML, XML and JSON: full readings. A backfill reads about 5 GB.
  - PDF: only the fields the browser shows (title, page count). A backfill reads about
    335 GB, so the PDF parser changes rarely and backfills run in the background.
  - ZIP containers and captions: none. ZIP members are captured as their own attempts.
- **Work list:** an anti-join on `(sha, parser, parser_version)`. A daily run appends once.
  A backfill appends once per batch, so it always resumes.
- **New parser versions** are backfilled in background batches. The live release uses the
  newest complete version of each parser.

### 5.3 `filename_readings`
- **Rows:** one per `(filename, source_url, catalog_version)`, holding the folded fields
  that `packages/house-naming` extracts.
- **Why a table.** Filename readings depend on the filename and the source URL, not on the
  body, so they can't live in `readings`. Recomputing them every run would cost about 9
  CPU-minutes a day (0.31 ms each over 1.68M source files) and put a Python pass inside the
  model.
- **Key.** The full source URL, not the host, because reviewed mirror URLs qualify
  readings individually.
- **Work list:** pairs in `captures` that have no row for the current catalog version.
  Daily cost is under a second. A new catalog version is one background job of about 7
  minutes over at most 1.35M pairs.

### 5.4 Maintenance
- **Basin Catalog maintains the tables:** compaction (target 128 MB) and snapshot
  expiration (older than 30 days, keep the last 5), enabled per table. Expiration also
  deletes the data files that only expired snapshots referenced.
- **Orphans.** Basin doesn't remove files that no snapshot ever referenced, such as the
  data file of a failed commit. Those are rare and small. The weekly check reports their
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

- **Grouping rule.** The edge set is SQL and is written down before anything is compared
  with the old catalog. Source files connect through shared document bodies and shared
  canonical endpoints (filename plus URL). HTML bodies, error responses and placeholder
  bodies don't connect anything. A placeholder is any body seen at more than *k* URLs: one
  error page sits at 87,161 URLs, and without this rule it glues together a component of
  174,323 source files.
- **Grouping runs in memory** over 32-bit IDs and refuses above a configured node count.
  At 4M nodes it needs 16 MB, so spilling would be wasted machinery below about 100 times
  today's scale.

### 6.2 Browser files
They're derived from the model outputs in the same job and shaped around the reader. The
list row number is the key that links them.

| File | Order | Contents | Read pattern |
|---|---|---|---|
| `list.parquet` (about 4 MB) | `(filename, document_id)` | Display name and facet fields; no ID | Downloaded whole, cached, searched and counted in a Web Worker |
| `detail.parquet` (about 100 MB) | Same row order as `list` | Full `document_id`, source IDs, URLs, body hash, readings fields, occurrence row range | One page per column, located by the page index and fetched concurrently |
| `ids.parquet` (about 43 MB) | `document_id` | ID and list row | Point lookup via the column index |
| `occurrences.parquet` (about 30 MB) | `(list_row, ordinal)` | Where each file was seen | The range named in `detail` |

- **No ID in `list`.** Measured on the real documents: 4.05 MB without an ID, 15.8 MB with
  an 8-byte ID and 45.9 MB with hex IDs. Deep links carry the `document_id`, and the
  reader resolves it to a row through `ids`.
- **Binary hashes everywhere.** Hex hashes were 160 of 187 MB in a measured `detail`.
- **Detail reads.** One detail view reads one page from each column: about 8 concurrent
  range requests, roughly 80 KB, in one round trip. Folding the columns into one struct
  would not reduce that, because Parquet stores each struct field as its own column chunk.
- **Shards.** `detail` and `occurrences` can be split into fixed row-range files, which
  the manifest lists with their row ranges. There is one shard today. The export adds
  shards when a footer would exceed 512 KB, at roughly 10 times today's rows, so pages
  never have to grow.
- **Ceiling.** At about 10 times today's documents, `list` reaches 40 MB and downloading
  it whole stops being reasonable. Then `list` is sharded by facet, or search moves to
  DuckDB-WASM or a server.

All browser files share these settings:
- Parquet 2.0 data pages and ZSTD;
- chunk statistics and the page index;
- footers under 512 KB, so one request reads metadata;
- no Bloom filters.

Unfiltered facet counts go in the release manifest.

### 6.3 Determinism
- Identical inputs produce byte-identical files. That makes reruns idempotent and the
  "nothing changed" check exact.
- **The engine enforces it:**
  - every sort key must be unique, or the export refuses;
  - partition order is fixed;
  - writer properties and the `created_by` string are pinned;
  - no timestamps or run-specific values go into content.
- **Tests:** compare bytes across thread counts and input orders.
- **Not a dedupe mechanism.** One new document shifts every later row number, so on any
  day with a change, every file changes. That is about 150 MB of uploads a day, which is
  fine.

### 6.4 Release and publish
- **Early skip.** If ingest appended nothing and the work lists were empty, publish stops
  before the model runs.
- **Release ID.** The SHA-256 of the file list (name, SHA-256, size, rows) and the schema
  version. It is computed after export and before upload. If it equals the live release's,
  there is nothing to publish.
- **Files.** Uploaded to `viewer-publications/releases/<release_id>/` with a create-only
  PUT and Content-MD5. A 412 on a rerun is checked against the expected MD5.
- **Manifest.** `releases/<release_id>/manifest.json` lists each file (name, SHA-256, MD5,
  size, rows, row range, schema version) and the facet counts. It also records the inputs
  exactly: lake snapshot IDs, the provenance digest, and the SQL, engine, parser and
  catalog versions. The inputs are recorded but are not part of the ID, so a catalog
  compaction alone doesn't make a new release.
- **Canary.** The site's own reader module runs in Node against the candidate. It decodes
  `list`, runs a search and a facet count, reads the first, last and a random detail,
  resolves an ID, reads an occurrence range and HEADs one saved copy. It takes under a
  minute and needs no headless browser.
- **Flip.** `viewer-publications/manifest.json` is updated with `If-Match` on its current
  ETag. A failed canary or a lost race leaves the previous release live.
- **Caching.** Release files and manifests are cached as immutable; the pointer is
  `no-store`.
- **Retention.** Keep the last 10 releases plus any pinned ones. The weekly job deletes
  older release prefixes. Releases share no files, so nothing needs reference counting.

## 7. Site

- **Reads:** pointer → release manifest → the files in section 6.2. Search and facet
  filtering run in a Web Worker over `list.parquet`. Details and point lookups use HTTP
  Range reads.
- **One reader.** The reader is a plain module with no DOM dependency, so the canary runs
  the same code the site ships.
- **Contract:** the manifest carries a `schema_version`. The reader accepts the current and
  the previous version, so format changes ship reader-first, then publisher.
- **Saved copies** link to `bodies/...`. Because of section 4.1, the browser receives the
  original document with the right media type.
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
2. **Append** through the REST catalog, always sending commit requirements.
3. **Deterministic multi-file export,** with SHA-256 and MD5 computed while writing, row-range
   shards, and the rules in section 6.3.
4. **ConnectedComponents** in memory over 32-bit IDs, refusing above a configured node
   count.
5. **Streaming I/O.** No re-read of a just-written object and no HEAD of immutable files.
   File and row-group sizes come from table properties.
6. **Bounded resources** set by configuration: compute threads, memory pool and scratch
   space. Joins, sorts and aggregates either spill or fail clearly within the pool.
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

1. **Raw invariants:** the weekly LIST joined to `captures` (key, size, MD5), the weekly
   25-body sample, and the one-time baseline for older bodies.
2. **Lake rebuild equivalence:** `captures` rebuilt from all receipts equals the appended
   table.
3. **Determinism:** byte-identical exports across thread counts and input orders.
4. **Contract:** CI builds a release from a fixed sample of real receipts and loads it
   through the real site in a headless browser.
5. **Canary:** the reader module in Node, before every flip.
6. **Production parity:** no test-only branches in production code, enforced by a ratchet
   test.

## 12. Performance

| Step | Cost | Expected |
|---|---|---|
| Capture | O(new attempts), network | Bounded by politeness to sources |
| Captures ingest | O(new receipts) | Seconds |
| Readings | O(new bodies in scope × parse cost) | Minutes daily; backfills in background |
| Filename readings | O(new pairs) | Under a second daily; about 7 minutes per catalog version |
| Model + export | O(N log N) over about 8M narrow rows | Seconds (3.7 s proxy; grouping 1–2 s) |
| Publish | O(release size) | About 150 MB on a day with changes |
| Weekly check | O(bodies / 1,000) list requests | About 1,000 requests, no body bytes |

A normal day moves about 1,500 object operations and 2 GB, well inside R2's free tier at
today's scale and at 10 times it.

**Validate before building on it,** in docspec-rs on the smallest production runner class:
1. full model-and-export time and peak memory (the 3.7 s proxy used DuckDB, not
   DataFusion);
2. ConnectedComponents on the real graph, with the placeholder rule;
3. join behavior at the memory pool limit;
4. export determinism;
5. Basin Catalog: a stale commit is refused, and the manifest count stays bounded under
   compaction.

## 13. Alternatives considered

| Alternative | Why not |
|---|---|
| Incrementally maintained model (keyed merges) | Recompute measured in seconds. Copy-on-write rewrites every touched file, and hashed keys touch nearly all of them. |
| Model as Iceberg tables replaced each run | It works only with a safe overwrite. Releases already give immutability, history and atomic switching without it. |
| No Iceberg (dated Parquet plus an `If-Match` manifest per log) | **The fallback.** Same atomicity with fewer moving parts, but no time travel and new engine code. Iceberg stays because the engine already writes it and Basin Catalog maintains it. Switch if Basin's compaction leaves manifests growing. |
| A general-purpose engine (DuckDB, Spark) in place of docspec-rs | Comparable query power, but it gives up the engine-first decision and docspec-rs's export and grouping operators. |
| Content-addressed objects shared between releases | Saves nothing on a day with any change, since every file changes, and needs a reference-counting sweep. |
| Spilling or partitioned ConnectedComponents | 16 MB of memory today and about 160 MB at 10 times. The real risk is giant components, which the grouping rule handles. |
| HEAD-per-body verification and a daily re-hash | Work that grows with history (a million HEADs a week, 1.3 TB of re-reads a year) to find what an ETag comparison finds. |
| One combined browser file | Point reads need small pages and the whole download needs a small file; one file can't have both. |
| DuckDB-WASM in the browser | Several MB of runtime for no gain at today's size. Worth revisiting at 10 times, when `list` outgrows a whole download. |
| Separate bucket for releases | Stronger isolation; declined by the owner. |

## 14. Open decisions

1. **Public document IDs:** full SHA-256 or a 16-hex prefix. With no ID in `list`, this
   only changes `ids` and `detail` (14 MB against 43 MB for `ids`). The export refuses on a
   prefix collision.
2. **Placeholder threshold** *k* for the grouping rule.
3. **PDF readings:** title and page count, or nothing. Each new PDF parser version re-reads
   about 335 GB.
4. **Retention numbers:** releases kept and snapshot age.
5. **R2 token scoping:** confirm with current Cloudflare docs.
6. **news_lake** adopts the same three layers later; out of scope here.

## Reviews

Three independent reviews shaped this design. All are in
`docs/reviews/2026-10-24-design-review/`: a general architecture review
(`fable-review.md`) and an Iceberg, Parquet and query-plan review
(`iceberg-parquet-review.md`) of revision 2, and an efficiency review with measurements on
the real data (`cs300-efficiency-review.md`) of revision 3. Revision 4 applies the third:

| Finding | Change in revision 4 |
|---|---|
| F1 filename extraction had no home | `filename_readings` (5.3) |
| F2 raw verification grew with history | MD5 in receipts; weekly LIST joined to captures; no daily re-hash (4.4) |
| F3, F4 Iceberg growth; catalog unnamed | Basin Catalog named; its maintenance replaces engine expiry; fallback named (5, 5.4, 13) |
| F5 `list` size | No ID in `list`; row number links the files (6.2) |
| F6 point reads and footers | Binary hashes, concurrent page reads, row-range shards (6.2). Not a folded struct: Parquet stores struct fields as separate chunks. |
| F7 grouping | In-memory with a cap; placeholder bodies excluded; rule written down first (6.1) |
| F8 readings backfill | Per-media-family parser versions; scope declared (5.2) |
| F9 dedupe claim | Determinism kept for idempotence, not dedupe; per-release prefixes, no sweep (6.3, 6.4) |
| F10 receipt LIST | Per-family listing from the newest ingested date (5.1) |
| F11 parity | Browser-visible fields and ID vectors against the pinned catalog (plan) |
| F12 moving parts | Node canary instead of a production headless run; three scheduled jobs (6.4, 8) |

The key in 5.3 departs from the review, which proposed the host: house-naming qualifies
some readings by exact mirror URL.

## Appendix: path from the current system

The raw log already exists (bodies, receipts, and provenance backed up on 2026-10-24) and
is preserved unchanged. Existing bodies keep their stored form. The target applies to new
writes; saved copies of existing gzip bodies need an edge rule to serve them with the right
encoding.

The order is:
1. **Week one:** the bucket lock, and two measurements that decide the engine work: Basin
   Catalog commits and compaction, and deterministic export plus grouping on real data.
2. **Now, in parallel:** the release format, reader and canary, built against a release
   converted from the pinned Oct 19 catalog. That release is also the parity oracle, and it
   can go live first.
3. The raw writer changes (MD5 in receipts, encoding, write-date keys) and the weekly
   check.
4. The engine capabilities in section 9.
5. The lake tables and their backfills.
6. The model SQL, checked against the pinned catalog on browser-visible fields.
7. Switching publishing, then deleting the old layers.

Estimated at 8–16 weeks for one engineer. Steps, estimates and tickets are in the plan.
