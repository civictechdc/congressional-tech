# Engine-first architecture

Status: proposed, revision 2, 2026-10-24. Owner: Mike Deeb. Revision 2 folds in two
independent reviews, both verified against the code and listed at the end. It replaces
the raw-index, incremental catalog and viewer-preparation layers once accepted.

## Summary

The raw source data stays an append-only, content-addressed log. docspec-rs keeps two
append-only Iceberg tables over that log: what was captured, and what each body says.
Each run, one DataFusion job recomputes the domain model from those two tables and writes
it directly as lean, browser-ready Parquet files named by their own SHA-256. A release
manifest names those files and their inputs, and one conditionally updated pointer makes
a release live, after a browser canary passes.

The model is not stored as Iceberg tables. Iceberg suits append-only data, which the
engine's library supports (`fast_append`). It cannot safely replace a table's contents
(see section 6). Content-addressed Parquet plus a manifest gives the model everything it
needs: immutability, history and an atomic switch.

The data is small by row count (about 8M rows) but bloated by bytes today: about 400
mostly empty columns and repeated 64-character hashes. The relational recompute measures
in seconds. The cost lies in wide, nested readings, document grouping and engine
defaults, so those are the first things to measure (section 9).

## 1. Context

On 2026-10-24 the explorer was down. The hosted viewer publish had not succeeded in its
last 60 runs (`gh run list`), and the last release was published by hand on Oct 20. The
causes are documented in `docs/reviews/2026-10-24-ticket-audit/` and
`docs/plans/simplification-plan-20261024.md`. In short, four layers of custom Python sit
between the raw files and the browser:

| Layer | What it does today | Cost per run |
|---|---|---|
| Raw index | Re-derives about 1.30M URL-state rows and 2.07M body-index rows from receipts, hash-spreads them over 512 leaves (each its own engine dataset), plus about 141k routing objects | Rewrites nearly every leaf (≈1.3 GB, ≈512 new datasets); never reclaims |
| Incremental catalog | About 9.2k lines (27.8k across `retention/`) that turn the raw index into document groups, as component-chunk releases plus SQLite staging, adoption and proofs | 75 pytest-only production branches; fingerprints facade files |
| Viewer preparation | Reads the catalog component by component (reasoned at about one read per component, ~1.24M), writes rows into SQLite one at a time, renders Parquet and page trees | Any code change in `congress_api`/`congress_shared` forces a full re-render; over 180 min on the hosted runner |
| Publication | Write-ahead journal, resume descriptors, GitHub-artifact custody, release fingerprint | About 1,560 lines to protect rebuildable output |

## 2. Goals and non-goals

**Goals**
1. Raw source data can never be lost, overwritten or silently changed.
2. Every derived artifact is a deterministic function of raw data plus versioned code and
   SQL, and can be rebuilt.
3. A daily update, from capture to live explorer, finishes well inside one hosted job
   (target under 45 minutes; most of that is polite capture).
4. Each item is read, written, parsed, hashed and validated once per run, using platform
   primitives.
5. congressional-tech holds little or no code that overlaps docspec-rs ("engine first").
6. A broken release can never become the live one.

**Non-goals**
- Sub-daily freshness.
- Concurrency beyond one scheduled pipeline plus occasional manual runs.
- Preserving any derived format, path or reader for compatibility.

## 3. Constraints and decisions in force

These are the owner decisions recorded in the audit README:
- One R2 bucket, `congressional-tech-raw`, with a bucket lock on `receipts/`, `bodies/` and
  `provenance/`. `r2.dev` stays open; everything is public records.
- docspec-rs commits durably after every step.
- Engine first: missing primitives are added to docspec-rs generically.
- Publishing is a content-addressed export plus one pointer flip.
- news_lake keeps its DocSpec backend. The engine surfaces it uses stay until news_lake
  migrates (section 6).
- Recovery imports refuse uncommitted code and record the git commit plus `uv.lock`.

## 4. Architecture

```
fetchers / recovery imports ──► RAW (append-only, create-only, bucket-locked)
               bodies/sha256/<aa>/<sha>.<ext>              stored bytes
               receipts/<family>/<date>/<run>.jsonl.gz    every attempt
               provenance/<kind>/<ts>.jsonl               manual and reviewed decisions
                 │
                 ▼  docspec-rs, one pipeline, durable commit per step
   Iceberg  1. raw.captures      receipts → append           O(new receipts)
   Iceberg  2. derived.readings  new bodies → parse → append  O(new bodies)
            3. model + export    one DataFusion job:
                                 captures + readings + provenance
                                 → lean Parquet, content-addressed   O(N)
                 │
                 ▼
            viewer-publications/objects/<sha>.parquet   create-only, only new files
            viewer-publications/releases/<id>.json      release manifest (names inputs)
            viewer-publications/manifest.json           If-Match flip, after canary
                 │
                 ▼
            static site → manifest → list.parquet (whole) / detail and ids (ranges)
```

### 4.1 Raw layer

| Prefix | Content | Writer rule |
|---|---|---|
| `bodies/sha256/<aa>/<sha>.<ext>` | Response bytes, keyed by the SHA-256 of the original bytes | Create-only PUT (`If-None-Match: *`), Content-MD5, `x-amz-meta-sha256` (original) and the stored-bytes digest. A 412 means the body already exists. |
| `receipts/<family>/<date>/<run>.jsonl.gz` | One line per attempt: URL, requested URL, time, HTTP status, outcome, original and stored SHA-256 and bytes, media type, an allowlisted set of response headers, writer identity (job, commit) | Create-only, written after the run's bodies |
| `provenance/<kind>/<ts>.jsonl` | Manual and reviewed decisions: accepted URL variants, recovery bases, document review decisions | Create-only, append-only |

**Rules**
- **Writers.** Every writer of raw data follows the same rule: `source-fetch` capture,
  corpus-recovery imports, and anything added later.
- **Body encoding.** Existing bodies stay exactly as stored (raw data is never rewritten):
  `.gz`, gzip of the original bytes, keyed by the original SHA-256. New bodies keep the same
  convention so there is one encoding. Saved-copy links need the right media type in the
  browser; that is solved at the edge, not by rewriting objects (open question 4).
- **Provenance is raw.** `viewer-publications/recoveries/accepted.json` holds 12,431
  decisions found in no receipt. It moves into `provenance/` as append-only records
  (backed up Oct 24) and is reconciled against receipts (ticket ct-st8m). Document review
  decisions, which today live in the repo, move there too.
- **Protection.** R2 bucket lock (indefinite) on the three prefixes, in place before any
  new writer runs (section 11, phase 0).
- **Verification.** Weekly: LIST the raw prefixes and check that every receipt-referenced
  body exists with the stored size and digest metadata the receipt recorded. Daily: re-hash
  a rolling 0.5% sample of bodies end to end. A full re-hash of about 696 GB stays an
  explicit, occasional job.

### 4.2 Step 1: `raw.captures` (Iceberg, append-only)

- One row per attempt, sorted by `(url, attempt_seq)`. Hashes are stored as 32-byte binary,
  and `body_key` is not stored because it derives from `sha256`.
- **Ingest.** LIST `receipts/`, anti-join against the receipt keys already present, and
  append only missing receipts. Rows are unique on `(receipt_key, receipt_line)`, so a
  retried append can't duplicate. Late or out-of-order receipts are picked up; there is no
  high-water mark.
- **Commit.** `fast_append` with the commit requirements sent (section 6).
- **Recovery.** Rebuilding from all receipts must reproduce the table, compared as the set
  of `(receipt_key, receipt_line)` rows.
- **Fields.** Receipt-level fields that today's legacy capture schema drops (requested URL,
  outcome, attempts) are kept, so `url_state` can be computed.

### 4.3 Step 2: `derived.readings` (Iceberg, append-only)

- One row per `(body_sha256, parser_version)`, partitioned by `parser_version` and sorted
  by `body_sha256`. A narrow typed core (filename, title, page count, format) plus one
  folded `readings List<Struct<field, values>>` replaces today's 337 sparse columns. Large
  text spans, if kept, go in their own table.
- **Scope.** Only bodies the model needs, by media type and family, get readings. The
  current system reads about 24k objects, not all 1.04M bodies. The SQL declares the scope.
- **Work list.** An anti-join on `(sha, parser_version)` lists missing work. Parsing runs in
  batches, and each batch is appended and committed, so the step resumes after a failure.
- **Backfill.** The first fill, and any parser-version bump, is a separate batched job
  outside the daily budget. Daily runs parse only new bodies.

### 4.4 Step 3: model and export, one job

The domain model is versioned SQL in this repo. One DataFusion job registers
`raw.captures`, `derived.readings` and the provenance records, evaluates the model, and
writes the outputs straight to Parquet. It doesn't keep intermediate tables.

**Model outputs.** Each is sorted by a unique key, uses 131,072-row row groups and
ZSTD(3), stores hashes as 32-byte binary, and carries no copied provenance columns:

| Output | Content |
|---|---|
| `url_state` | Latest outcome per URL, with the retry schedule (about 1.3M rows, about 12 columns) |
| `filenames` | One row per observed source file; reading data joined by `body_sha256`, not copied |
| `documents` | Grouped with the engine's ConnectedComponents; the `document_id` expression is supplied by SQL |
| `members` | `(document_id, source_id)` member list as its own table, not nested |
| `recoveries`, `reviews` | From provenance and receipts |

**Browser exports** (hyparquet 1.31.2; measured sizes for 1.24M documents):

| File | Row order | Shape | Read pattern |
|---|---|---|---|
| `list.parquet` (≈4 MB) | `(filename, document_id)` | filename, congress, kind, family, format; facets as dictionary strings; flags `int8` | Fetched whole, cached, searched and counted in a worker |
| `detail.parquet` | Same as `list`; the row number is the join | Full ID, URL, body hash, folded readings, `occ_start`, `occ_count`; 8,192-row groups; 256-row pages; offset index | Row ranges with `useOffsetIndex` |
| `ids.parquet` | `id` | ID and list row; column index; dictionary off | `filter {id: $eq}` with `usePageIndex` |
| `occurrences.parquet` | `(list_row, ordinal)` | Occurrence fields; offset index | Ranges from `detail.occ_*` |

All browser files share these settings:
- writer `PARQUET_2_0`, so V2 pages that hyparquet decodes;
- ZSTD(3), decoded with the site's existing fzstd;
- chunk-level statistics;
- no Bloom filters (hyparquet does not use them);
- footer under 512 KB, so hyparquet's first fetch covers it.

Unfiltered facet counts go in the release manifest; filtered counts are computed
client-side from `list.parquet`.

**Determinism, built in rather than assumed.**
- The export refuses if a sort key is not unique.
- The final write uses a fixed partition order.
- Writer properties are pinned and the `created_by` string is fixed per engine version.
- No timestamps or run-specific values go into file content.
- Tests run the same inputs with different thread counts and input file orders, and compare
  bytes.

### 4.5 Publish

- **Upload.** Files go to `viewer-publications/objects/<sha>.parquet` with a create-only
  PUT and Content-MD5. A file already named in the live release manifest is skipped
  without a HEAD.
- **Manifest.** The release manifest lists each file (path, sha256, bytes, rows, schema
  version) and the facet counts. It names its inputs exactly: the `raw.captures` and
  `derived.readings` snapshot IDs, the count and digest of ingested receipt keys, and the
  digests of the provenance files, SQL, engine and parser versions. `release_id` is the
  SHA-256 of the manifest body, which contains no publish time.
- **Skipping.** If a run's input identity matches the live release's, the run stops after
  step 2.
- **Canary.** The production site, loaded with `?release=<id>`, runs list, search and
  detail checks against the candidate release before the pointer moves.
- **Flip.** `viewer-publications/manifest.json` is updated with `If-Match` on its current
  ETag. A lost race or a failed canary leaves the old release live.
- **Caching.** Objects and release manifests are immutable (`max-age=31536000, immutable`).
  The pointer is `no-store`.

### 4.6 Site contract

- **Reads.** The site reads the pointer, then the release manifest, then the files listed
  in section 4.4. That is a new reader version, replacing `catalog-v6.ts`'s page-tree
  traversal.
- **Versioning.** The manifest has a `schema_version`. The reader accepts the current and
  the previous one. A format change ships reader-first, then publisher.
- **CI.** CI publishes a fixed real sample (about 1% of receipts) and loads it through the
  real reader in a headless browser.
- **Saved copies.** Saved-copy links resolve through the body key plus metadata (open
  question 4).
- **Origin.** `https://congressional-data.spicygov.ai`, which serves the bucket directly,
  with the bucket CORS policy from `infra/cloudflare/congressional-data-r2-edge.json`.
- **Committee Explorer.** It publishes from the `pipeline-data` git branch and is
  unaffected.

### 4.7 Retention

- **Releases.** Keep the last 10 releases plus anything referenced by a pinned link.
  A weekly sweep deletes `objects/` files that no kept release names, after a 7-day grace
  period.
- **Iceberg.** One owner, the engine, expires `raw.captures` and `derived.readings`
  snapshots older than 30 days. Then it removes orphan files not referenced by any live
  snapshot.

## 5. Orchestration

```
capture workflow:  source-fetch → receipts and bodies
publish workflow:  captures → readings (new only) → model and export → canary → flip → status
```

- **Two workflows.** Capture and publish are separate. Publish runs after capture or on
  demand, and never shares its credentials.
- **Identity.** Each step is keyed by its input identity (section 4.5). A finished step is a
  no-op on re-run. There are no journals; the engine commits each step durably.
- **Pinned engine.** The engine binary is pinned by revision and digest before any R2
  access (shipped Oct 24).
- **Runner settings.** `compute_threads` 4, `memory_bytes` about 10 GiB, `batch_rows`
  8,192, scan concurrency 4. Today's default (24 GiB) overcommits the 16 GB hosted runner.
- **Status.** Each run writes `viewer-publications/status.json`: input identity, rows per
  output, durations, bytes and the live release ID.
- **Concurrency.** One concurrency group per workflow. Iceberg commits carry their
  requirements, and the pointer uses `If-Match`.
- **Local runs.** The same steps run locally with the same commands; correctness never
  depends on GitHub artifacts.

## 6. Changes to docspec-rs

**Add**
1. **Multi-input SQL.** Register several Iceberg tables and Parquet files in one DataFusion
   context and run one SQL plan. Today `RunSpec` takes one input file
   (`src/model/operations.rs:46-62`), and general SQL is listed as deferred in
   `docs/STATUS.md`. This is the main new primitive.
2. **Multi-file export from that plan** with the determinism rules in section 4.4 and
   SHA-256 computed while writing.
3. **Correct commits.** Every commit sends its requirements (`assert-table-uuid`,
   `assert-ref-snapshot-id`). Today `replace_baseline_snapshot` discards them
   (`let _ = commit.take_requirements();`, `src/catalog.rs:1354`), so on the R2 REST catalog
   a concurrent commit can silently replace a newer snapshot. This is a bug today.
4. **Remote I/O.** Remove the unmeasured 2 MiB file and 2,048-row caps
   (`src/storage.rs:376-388`) and take sizes from table properties. Scan more than one data
   file at a time (`storage.rs:211`). Hash while writing; no GET or HEAD of just-written or
   immutable files.
5. **ConnectedComponents.** Make its memory accounting honest. String headers, hash-map
   overhead and the final maps aren't counted today (`connected_components/topology.rs`).
   Use compact IDs instead of per-row strings. Measure before parallelizing.

**Remove** (after the replaced application layers are gone):
1. The lifecycle-record families no consumer writes. news_lake's `release` and
   `compact_lifecycle` surfaces stay until news_lake migrates.
2. Phase-resume machinery beyond durable per-step commits.
3. The 60 `cfg(not(test-util))` production-only branches and the dataset-name
   verification skips.
4. congressional-tech policy compiled into the engine (the `document_id` formula, edge
   names).
5. Unused HTTP routes, `cli_args.rs`, the Dagster adapter, legacy formats, and the
   hand-rolled SHA-256 (use `sha2`).

**Library constraint.** iceberg 0.10.1 has no overwrite, replace or tag action, and its
`TransactionAction` trait is crate-private (`iceberg-0.10.1/src/transaction/mod.rs:135-170`,
`action.rs:37`). This design needs only `fast_append` and `expire_snapshots`. If a replace
is ever needed, upstream an `OverwriteAction` rather than working around the library.

**Hashes.** SHA-256 is the public content address for bodies and published files. BLAKE3
stays internal to the engine. No value is hashed with both for the same purpose.

## 7. Security and access

- **Raw.** Bucket lock on the raw prefixes, before any new writer. Writers create only.
- **Tokens.** R2 API tokens are scoped per bucket, not per prefix (to confirm against
  current Cloudflare docs). With one bucket, raw isolation rests on the lock plus code
  allowlists. Capture and publish use separate tokens. Measurements use a read-only token.
- **Receipts.** They record writer identity (job, commit) and only allowlisted response
  headers, never cookies or authorization headers.
- **Public reads.** Everything is public records, readable at `r2.dev`. The custom domain
  serves the same bucket with CORS for the site.

## 8. Verification

1. **Raw invariants** (section 4.1): existence plus metadata weekly, a rolling content
   sample daily.
2. **Determinism** (section 4.4): byte-identical output across thread counts and input
   orders.
3. **Rebuild equivalence:** `raw.captures` rebuilt from all receipts equals the appended
   table.
4. **Contract:** the CI sample is published and loaded through the real reader.
5. **Production parity:** a ratchet test fails on any `PYTEST_CURRENT_TEST` or
   `test-util`-only production branch.
6. **Canary before flip.**

## 9. Performance model

Variables: R receipts, B bodies (1.04M), N ≈ 8M total rows (3.9M capture rows, 1.30M URL
states, 1.68M filenames, 1.24M documents), C new attempts per run.

Measured on the real Oct 19 files, with DuckDB as a proxy, 4 threads, on a loaded machine:
- latest outcome per URL: 1.1 s;
- lean 14-column filenames written sorted: 2.4–3.1 s;
- unpivoting today's 337 reading columns: 30.6 s at about 10 GB peak.

| Step | Cost | Estimate |
|---|---|---|
| Capture | O(C) network | 10–30 min, bounded by politeness |
| Captures append | O(C) | seconds |
| Readings (daily) | O(new bodies) | minutes; backfill is a separate batched job |
| Model + export | O(N log N) | relational core in seconds; ConnectedComponents and readings joins **unmeasured** |
| Upload | O(changed files) | seconds |

**What phase 0 must measure,** in docspec-rs and not only in a proxy, on a 4-vCPU, 16 GB
machine with the runner settings in section 5:
1. the full model job over lean `raw.captures` and folded readings;
2. ConnectedComponents peak heap at 1.68M rows;
3. hash-join build sides against the memory pool (do they spill in DataFusion 53.1?);
4. export determinism across two thread counts.

Today's 2 MiB file caps would distort the results, so lift them first.

## 10. Alternatives considered

| Alternative | Why not |
|---|---|
| Keep the incremental Python layers and fix them | O(total) work per run in practice, 28k+ lines, and production paths the tests can't see |
| Engine-native keyed merges (`UpdateMergeSpec`) | Copy-on-write in iceberg 0.10.1 rewrites every touched file, and hash-spread keys touch nearly all files |
| Model as Iceberg tables replaced each run | The library can't replace safely, and the engine's current workaround drops commit requirements (section 6) |
| Plain Parquet plus a manifest for everything, no Iceberg | Viable. Iceberg is kept only where append-only snapshots and commit checks earn their keep (captures, readings). |
| DuckDB instead of docspec-rs | Comparable query power, but it discards the engine and the owner's engine-first decision |
| Separate derived bucket | Stronger isolation; declined by the owner for now |

## 11. Migration

The raw data is untouched throughout. The new pipeline runs beside the old one, reading
the same raw prefixes.

| Phase | Work | Exit criterion |
|---|---|---|
| 0 | Bucket lock on raw prefixes; separate capture, publish and read-only tokens; the engine commit-requirements fix; lift the remote file caps; then the phase-0 measurements in section 9 | Lock rules read back; measurements recorded; go or no-go on the model job |
| 1 | `raw.captures` from receipts (LIST plus anti-join), `url_state` SQL | Rebuild equivalence; `url_state` matches today's state rows on outcome and retry fields |
| 2 | `derived.readings` with the folded layout, in batches; scope declared in SQL | Every in-scope body has a reading for the current parser version; daily run parses only new bodies |
| 3 | Multi-input SQL in the engine; model SQL (filenames, documents via ConnectedComponents, members, recoveries, reviews) | Differential check against the current catalog: every difference explained as a rule change or an old-path bug; facts held only in derived tables moved to `provenance/` |
| 4 | Export (determinism rules), content-addressed upload, release manifest, canary, `If-Match` flip; new site reader version | Live explorer on the new release; CI contract test green |
| 5 | Capture and publish workflows; status file; retention sweeps | Two consecutive scheduled runs within budget |
| 6 | Delete the old layers and the engine surfaces they used (except news_lake's) | Ratchet tests green; line counts recorded |

**Estimate:** 2.5–4 weeks of focused work, contingent on phase 0. The engine work in
section 6 and the site reader can proceed in parallel with phases 1–2. The readings
backfill runs as background batches.

## 12. Risks and open questions

1. **Unmeasured costs** (section 9): ConnectedComponents memory, join spill and the wide
   readings. Phase 0 settles these.
2. **Export determinism** must hold, or every run re-uploads everything; it is enforced by
   tests.
3. **Facts held only in derived tables.** Phase 3's differential check surfaces them, and
   they move to `provenance/` before deletion.
4. **Saved-copy media types.** Existing `.gz` bodies download as gzip. Options: an edge rule
   that serves `bodies/` with `Content-Encoding: gzip` and the receipt's media type, or a
   small read path. This is an owner decision; it is not a raw rewrite.
5. **Short public IDs** (a 16-hex prefix cuts ID-carrying files by about 3×, with no
   collisions today and refusal on collision). Owner decision.
6. **R2 token scoping**: to confirm.
7. **news_lake** follows the same pattern later. Its engine surfaces are kept until then.

## Reviews

Both reviews were checked against the code before being folded in. Both blockers were
confirmed directly: `RunSpec` takes a single input, and iceberg 0.10.1's `Transaction`
offers no overwrite.
- **General architecture:** `docs/reviews/2026-10-24-design-review/fable-review.md` (verdict:
  reconsider, then reshape; 2 blockers, 6 majors).
- **Iceberg, Parquet and query plans:** `docs/reviews/2026-10-24-design-review/iceberg-parquet-review.md`
  (1 blocker, 7 majors; measured file shapes and settings).

## Appendix: current components and their fate

| Component | Fate |
|---|---|
| `source-fetch`, receipt and body writers, corpus-recovery imports | Keep; adopt the raw writer rule |
| `raw_storage` leaves, `partition_routing`, `raw_state_routes`, `indexes/raw.json`, native-manifest routing objects | Replaced by `raw.captures` and `url_state` |
| `catalog_*`, `source_*`, `raw_adoption*` incremental modules | Replaced by the model SQL |
| `filename_native`, `filename_exports` local path, publication journal, resume, custody, `release_identity` | Replaced by the model and export job plus publish |
| `docspec_client` transport | Keep, reduced to the operations above |
| Site `catalog-v6.ts` page-tree reader | Replaced by the list, detail and ids reader (section 4.4) |
| Committee Explorer (`pipeline-data` branch) | Unaffected |
