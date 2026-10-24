# Engine-first architecture

Status: proposed, revision 3, 2026-10-24. Owner: Mike Deeb. This document describes the
target system as it should be, independent of how the current code works. The path from
today is in `docs/plans/simplification-plan-20261024.md` and the appendix.

## Summary

congressional-tech captures congressional source documents, keeps them forever, and
publishes a fast public explorer over them. The ideal system has three layers, and only
the first is precious:

1. **Raw log.** An append-only, content-addressed record of every fetch attempt, every
   body and every human decision. It is never rewritten.
2. **Lake.** Two append-only engine tables derived from the log: what was captured, and
   what each body says. Each is computed once per new item.
3. **Releases.** Immutable, content-addressed Parquet produced by one deterministic SQL job
   over the lake. A single pointer selects the live release.

docspec-rs does all the data work. congressional-tech supplies fetchers, parsers,
declarative SQL and the site.

## 1. Principles

1. **Raw is the only truth.** Everything else is a pure function of raw data plus
   versioned code, SQL and engine, and can be rebuilt at any time.
2. **Append or replace, never update.** Logs only grow. Derived outputs are recomputed and
   swapped atomically. No row is edited in place.
3. **Do each thing once.** Every body is fetched, stored, hashed and parsed once per
   parser version. Every published file is written and uploaded once. Platform primitives
   (content addressing, conditional writes, Content-MD5, snapshot commits) replace
   hand-built bookkeeping.
4. **Engine first.** Data movement, joins, grouping, aggregation, export and retention
   live in docspec-rs. Application policy is passed in as SQL and specs, never compiled
   into the engine.
5. **Nothing reaches users unverified.** A release goes live only after the real site
   reader has loaded it.
6. **Small bytes.** Store keys and facts once, as typed columns. Never copy provenance into
   derived rows, never store what can be derived, and shape browser files around how the
   site reads.

## 2. Scale assumptions

| Quantity | Order of magnitude |
|---|---|
| Fetch attempts (capture rows) | ~4M, growing ~0.1–1% per day |
| Distinct bodies | ~1M, about 0.7 TB stored |
| Distinct URLs | ~1.3M |
| Source files and documents | ~1.7M and ~1.2M |
| Daily change | Thousands of attempts and bodies |

At this scale, recomputing the model from the lake is cheaper and simpler than
maintaining it incrementally. The only per-item work that must not be repeated is fetching
and parsing bodies.

## 3. System overview

```
fetchers, recovery imports, review tools
        │  create-only writes
        ▼
RAW LOG (one bucket; locked prefixes)
  bodies/sha256/<aa>/<sha>            stored bytes, keyed by SHA-256 of the original
  receipts/<family>/<date>/<run>.jsonl.gz   one line per fetch attempt
  provenance/<kind>/<ts>.jsonl        human and reviewed decisions
        │
        ▼  docspec-rs
LAKE (Iceberg, append-only)
  captures   one row per attempt                     O(new receipts)
  readings   one row per (body, parser version)       O(new bodies)
        │
        ▼  docspec-rs: one SQL plan, deterministic export
RELEASE (immutable, content-addressed)
  viewer-publications/objects/<sha>.parquet
  viewer-publications/releases/<release_id>.json
  viewer-publications/manifest.json   ← If-Match pointer, flipped after canary
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
  including a browser opening a saved copy, receives the original bytes. Object metadata
  records the original SHA-256 and the stored bytes' SHA-256 and size.
- **Write:** create-only PUT (`If-None-Match: *`) with Content-MD5. A 412 means the body
  already exists and the writer moves on.

### 4.2 Receipts
- One immutable file per fetch run. Each line records:
  - requested URL, final URL, time, HTTP status and outcome (stored, unchanged, failed,
    retry-later);
  - body SHA-256, stored SHA-256 and size, media type;
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
- **Weekly check:** LIST the raw prefixes; every receipt-referenced body exists, with the
  size and digest metadata the receipt recorded.
- **Daily check:** re-hash a rolling sample (about 0.5%) of bodies end to end. A full
  re-hash is an explicit, occasional job.

## 5. Lake

Both tables are Iceberg tables owned by docspec-rs and committed with full commit
requirements (table UUID and current snapshot), so concurrent writers fail rather than
overwrite each other.

### 5.1 `captures`
- **Rows:** one per fetch attempt. Unique on `(receipt_key, receipt_line)`, sorted by
  `(url, attempt_seq)`, with hashes as 32-byte binary. No derivable columns.
- **Ingest:** LIST `receipts/`, anti-join against receipt keys already ingested, and append
  the missing ones. Late or out-of-order receipts are picked up, and a retried append
  cannot duplicate.
- **Rebuild check:** rebuilding from all receipts reproduces the same set of rows.

### 5.2 `readings`
- **Rows:** one per `(body_sha256, parser_version)`, partitioned by parser version, sorted
  by body hash.
- **Columns:** a narrow typed core (filename, title, page count, format) plus one folded
  `List<Struct<field, values>>` for everything else. Large text goes in its own table if
  it's needed.
- **Scope:** the model SQL declares which bodies need readings, by media type and family.
- **Work list:** an anti-join on `(sha, parser_version)`. Parsing runs in batches, and each
  batch is appended and committed, so the step always resumes.
- **New parser versions** are backfilled in background batches. The live release uses the
  newest complete version.

### 5.3 Maintenance
The engine expires snapshots older than 30 days and removes orphan files no live snapshot
references. One owner, one schedule.

## 6. Model and release

### 6.1 Model
- The domain model is versioned SQL in the application repo.
- One docspec-rs job registers `captures`, `readings` and the provenance records,
  evaluates the plan, and writes the outputs directly as Parquet. There are no
  intermediate tables.

| Output | Content |
|---|---|
| `url_state` | Latest outcome and retry schedule per URL |
| `filenames` | One row per observed source file, linked to readings by body hash |
| `documents` | Source files grouped by the engine's ConnectedComponents; the `document_id` expression comes from SQL |
| `members` | `(document_id, source_id)` |
| `recoveries`, `reviews` | Resolved from provenance and captures |

### 6.2 Browser files
They're derived from the model outputs in the same job and shaped around the reader:

| File | Order | Contents | Read pattern |
|---|---|---|---|
| `list.parquet` (a few MB) | `(filename, document_id)` | Display name and facet fields | Downloaded whole, cached, searched and counted in a Web Worker |
| `detail.parquet` | Same row order as `list` | Full identifiers, URLs, body hash, folded readings, occurrence range | Row ranges via the offset index |
| `ids.parquet` | `id` | ID and list row number | Point lookup via the column index |
| `occurrences.parquet` | `(list_row, ordinal)` | Where each file was seen | Ranges from `detail` |

All browser files share these settings:
- Parquet 2.0 data pages and ZSTD;
- chunk-level statistics;
- footers under 512 KB, so one request reads metadata;
- no Bloom filters.

Unfiltered facet counts go in the release manifest.

### 6.3 Determinism
- Identical inputs produce byte-identical files, so unchanged files keep their names and
  are never re-uploaded.
- **The engine enforces it:**
  - every sort key must be unique, or the export refuses;
  - partition order is fixed;
  - writer properties and the `created_by` string are pinned;
  - no timestamps or run-specific values go into content.
- **Tests:** compare bytes across thread counts and input orders.

### 6.4 Release and publish
- **Objects.** Files are uploaded to `viewer-publications/objects/<sha>.parquet` with a
  create-only PUT and Content-MD5. Files the live release already lists are skipped.
- **Manifest.** The release manifest lists each file (path, SHA-256, size, rows, schema
  version) and the facet counts. It names its inputs exactly: the lake snapshot IDs, the
  digest of ingested receipt keys, the provenance digest, and the SQL, engine and parser
  versions. `release_id` is the SHA-256 of the manifest, which contains no publish time.
- **Skipping.** If the input identity equals the live release's, there is nothing to
  publish.
- **Canary.** The production site loads the candidate with `?release=<id>` and runs list,
  search, detail and saved-copy checks.
- **Flip.** `viewer-publications/manifest.json` is updated with `If-Match` on its current
  ETag. A failed canary or a lost race leaves the previous release live.
- **Caching.** Objects and release manifests are cached as immutable; the pointer is
  `no-store`.
- **Retention.** Keep the last 10 releases plus any pinned ones. A weekly sweep removes
  unreferenced objects after a 7-day grace period.

## 7. Site

- **Reads:** pointer → release manifest → the files in section 6.2. Search and facet
  filtering run in a Web Worker over `list.parquet`. Details and point lookups use HTTP
  Range reads.
- **Contract:** the manifest carries a `schema_version`. The reader accepts the current and
  the previous version, so format changes ship reader-first, then publisher.
- **Saved copies** link to `bodies/...`. Because of section 4.1, the browser receives the
  original document with the right media type.
- **Origin:** `congressional-data.spicygov.ai` serves the bucket directly, with a
  read-only, any-origin CORS policy (GET/HEAD, Range).

## 8. Orchestration

```
capture:  fetchers → bodies → receipts                      (scheduled; network-bound)
publish:  captures → readings (new) → model + export → canary → flip → status
backfill: readings for a new parser version, in batches     (on demand)
```

- **Idempotent steps.** Each step is keyed by its input identity and is a no-op when that
  hasn't changed. Each step commits durably, so a failed run resumes by running again.
  There are no journals.
- **Separate credentials.** Capture and publish run as separate jobs with separate
  credentials. Publish follows capture, or runs on demand.
- **Pinned engine.** The engine binary is pinned by revision and digest, checked before any
  storage access.
- **Resources.** Resource limits are explicit per runner class (threads, memory pool,
  scratch). The memory pool never exceeds the machine.
- **Status.** Every run publishes `viewer-publications/status.json`: input identity, rows
  per output, durations, bytes and the live release.
- **Local runs.** The same commands run locally or in CI. Correctness never depends on a CI
  feature.

## 9. docspec-rs: the engine this needs

**Capabilities**
1. **Multi-input SQL plans** over Iceberg tables and Parquet files in one DataFusion
   context.
2. **Append** with commit requirements always sent; snapshot expiry; orphan cleanup.
3. **Deterministic multi-file export,** with SHA-256 computed while writing and the rules
   in section 6.3.
4. **ConnectedComponents** over compact integer IDs, with honest memory accounting and
   spilling or partitioning when large.
5. **Streaming I/O.** No re-read of a just-written object and no HEAD of immutable files.
   File and row-group sizes come from table properties.
6. **Bounded resources** set by configuration: compute threads, memory pool and scratch
   space. Joins, sorts and aggregates either spill or fail clearly within the pool.
7. **A thin interface:** a library plus a CLI that runs a declarative job spec (inputs,
   SQL, outputs, export settings) and returns a machine-readable result.

**Non-capabilities.** These are deliberately out of scope:
- application policy (ID formulas, field names);
- bookkeeping that duplicates Iceberg (Iceberg snapshots are the history);
- resume machinery beyond per-step commits;
- test-only production paths.

**Library.** Iceberg is used only for append and expiry. If replace or branching is ever
needed, add it upstream to iceberg-rust rather than working around it.

## 10. Security

- **Raw:** create-only writers, plus the bucket lock on raw prefixes.
- **Credentials:** capture, publish and read-only roles are separate.
- **One-bucket trade-off.** With one bucket, R2 tokens can't be scoped per prefix (to
  confirm), so raw isolation rests on the lock plus writer allowlists. A separate bucket
  for releases would add credential-level isolation; the owner chose one bucket.
- **Public data.** Everything stored is public records and is readable publicly.
- **Receipts:** allowlisted headers only.

## 11. Verification

1. **Raw invariants:** existence and metadata weekly, a rolling content sample daily.
2. **Lake rebuild equivalence:** `captures` rebuilt from all receipts equals the appended
   table.
3. **Determinism:** byte-identical exports across thread counts and input orders.
4. **Contract:** CI publishes a fixed sample of real receipts and loads it through the real
   reader in a headless browser.
5. **Canary** before every flip.
6. **Production parity:** no test-only branches in production code, enforced by a ratchet
   test.

## 12. Performance

| Step | Cost | Expected |
|---|---|---|
| Capture | O(new attempts), network | Bounded by politeness to sources |
| Captures ingest | O(new receipts) | Seconds |
| Readings | O(new bodies × parse cost) | Minutes daily; backfills in background |
| Model + export | O(N log N) over ~8M narrow rows | Relational work in seconds; grouping and readings joins dominate |
| Publish | O(changed files) | Seconds |

**Validate before building on it,** in docspec-rs on the smallest production runner class:
1. full model-and-export time and peak memory;
2. ConnectedComponents peak heap;
3. join behavior at the memory pool limit;
4. export determinism.

## 13. Alternatives considered

| Alternative | Why not |
|---|---|
| Incrementally maintained model (keyed merges) | Copy-on-write rewrites every touched file, and hashed keys touch nearly all of them. At this scale it is slower and far more complex than recompute. |
| Model as Iceberg tables replaced each run | It works only with a safe overwrite. Releases already give immutability, history and atomic switching without it. |
| No Iceberg at all (Parquet plus manifests everywhere) | Viable. Iceberg earns its place for the append-only logs: atomic, conflict-checked appends and snapshot history. |
| A general-purpose engine (DuckDB, Spark) in place of docspec-rs | Comparable query power, but it gives up the engine-first decision and docspec-rs's export and grouping operators. |
| Separate bucket for releases | Stronger isolation; declined by the owner. |

## 14. Open decisions

1. **Public document IDs:** full SHA-256, or a 16-hex prefix (about 3× smaller ID files;
   the export refuses on collision).
2. **Retention numbers:** releases kept, grace period, snapshot age.
3. **R2 token scoping:** confirm with current Cloudflare docs.
4. **news_lake** adopts the same three layers later; out of scope here.

## Reviews

Two independent reviews of revision 2 shaped this design. Both are in
`docs/reviews/2026-10-24-design-review/`: a general architecture review (`fable-review.md`)
and an Iceberg, Parquet and query-plan review (`iceberg-parquet-review.md`).

## Appendix: path from the current system

The raw log already exists (bodies, receipts, and provenance backed up on 2026-10-24) and
is preserved unchanged. Existing bodies keep their stored form. The target applies to new
writes; saved copies of existing gzip bodies need an edge rule to serve them with the right
encoding.

The order is:
1. bucket lock and credentials;
2. the engine capabilities in section 9, with the validation in section 12;
3. the lake tables;
4. the model SQL, checked against today's catalog until every difference is explained;
5. the release pipeline and the new site reader;
6. deleting the old layers.

Rough size: 2.5–4 weeks. Details and tickets are in the simplification plan and the
`ct-98sm` and `ss-oxg1` epics.
