# CS 300 design review: is the engine-first architecture an efficient design?

Reviewer role: systems / data-intensive software engineering, capstone design review.
Date: 2026-10-24. Reviewed: `docs/engine-first-architecture.md` (revision 3; cited as **D:line**)
and `docs/plans/simplification-plan-20261024.md` (cited as **P:line**). Not read, by instruction:
pipeline code, engine source, prior reviews, tickets.

Every number below is one of: a **measurement** on the real data snapshot (DuckDB 1.5.5 / PyArrow
25.0.1 from the project venv, `/Users/mikewolfd/Work/wt/ct-viewer-publish/.venv/bin/python -I`),
a **public-doc fact** (Cloudflare R2 docs fetched today), or an **estimate** (marked). Scripts and
raw outputs are in the session scratchpad
(`/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/`):
`profile_captures.py`, `inspect_schemas.py`, `build_list.py`, `cc_and_occurrences.py`,
`model_proxy.py`, `size_occ_captures.py`, `time_house_naming.py`, `public-samples/`.

## 0. The data the design must handle (measured)

Snapshot: `output/incremental-updates-20261019/adoption-inputs/` (captures sha256 `db033173…`,
catalog generation `596f08fa…`).

| Quantity | Measured | Design assumption |
|---|---|---|
| Fetch attempts (captures rows) | 3,909,134 in 2,289 receipt files | ~4M (D:46) ✓ |
| Distinct bodies / stored bytes | 1,036,256 / ≈0.70 TB (PDF 365 GB, ZIP 286 GB, untyped 37 GB, HTML ≈4.5 GB, WARC 2.4 GB, XML 0.76 GB, VTT 0.21 GB) | ~1M, 0.7 TB (D:47) ✓ |
| Distinct URLs | 1,158,426 | ~1.3M (D:48) ✓ |
| Source files / documents (today's model) | 1,683,430 / 1,241,157 | ~1.7M / ~1.2M (D:49) ✓ |
| Source occurrences | 4,727,694 (median 4 per document, p99 26, max 33,479) | not stated |
| Daily change, normal days (Oct 13–16) | 270–3,553 attempts, 258–1,595 new bodies, 6–59 receipt files | "thousands" (D:50) ✓ |
| Daily change, import days (Sep 29, Oct 5, 6, 12) | 166k–745k attempts, 69k–547k new bodies, up to 482 receipts | not stated |
| Receipt lines per file | median 199, mean 1,708, max 909,916 | — |
| Receipt line size (fetched samples) | 480–980 B gzipped, 6–9 KB plain JSON per line | — |
| Bodies shared by several URLs | 241,054 (max 87,161 URLs for one body: an error/placeholder page) | — |
| Largest body | 1.19 GB; 3 bodies > 1 GB; 579 > 100 MB; none > 5 GB | — |
| Today's model outputs | filenames.parquet 547 MB / 353 columns; documents.parquet 541 MB / 356 columns; readings 491,710 rows / 54 MB / 721 files | — |

Public origin (`congressional-data.spicygov.ai`, 6 GETs + 1 Range probe): bodies are served as
`content-type: application/gzip` with **no** `Content-Encoding`; `accept-ranges: bytes`, `206`
on Range, `access-control-allow-origin: *`, ETag is the MD5 of the stored bytes (verified against
my own MD5 of the download). Hashes of the three decompressed bodies matched the `sha256` column.

## 1. Grades per axis

| # | Axis | Letter | Score | Rationale |
|---|---|---|---|---|
| 1 | Asymptotic cost per run / backfill | B+ | 87 | Ingest, readings and publish are O(change); daily model recompute is O(N log N) and measured at 3.7 s, so recompute beats incremental here. Hidden O(history): receipt LIST (O(R)), weekly body verification (O(B) HEADs as written), the daily 0.5 % re-hash (O(0.005·B)), Iceberg manifest/file counts O(commits), and an unplaced O(N) Python filename-extraction pass. |
| 2 | I/O and network | B | 82 | ~1.5k object ops and ~2 GB moved per normal day: trivially inside R2's free tier at 1× and 10×. The weak spot is raw verification: 1.04M HEADs/week and 3.5 GB/day of re-reads buy little that `LIST`+ETag does not. File-level dedupe at publish saves 0 bytes on any day with a change. |
| 3 | Do-once compliance | B | 80 | Bodies fetched/hashed/parsed once ✓, releases uploaded once ✓, idempotent steps ✓. Violations: re-hash by design, three digests per body (fine if one pass), the house-naming extraction has no home and would be recomputed per run (8.7 CPU-min), and the full release re-uploads daily (cheap, justified). Daily recompute of the model is justified by measurement. |
| 4 | Bytes | B+ | 85 | Binary hashes, no derived columns and folded sparse fields are the right calls (hex IDs are 160 of 187 MB in an 8-column detail file; 187 near-empty list columns cost 22 MB today). But "`list.parquet` (a few MB)" is only true without the id in the file (4.0 MB vs 15.8 MB with an 8-byte id, 45.9 MB with hex). Per-detail reads are ~140 KB over 8 requests; one folded column would make it one. Whole-list download has a ceiling near 10×. |
| 5 | Compute and memory (16 GB runner) | A− | 90 | Entire relational plan: 3.7 s, 1.75 GB in DuckDB, 3.9 GB RSS, byte-identical across thread counts. Connected components: 3.96M nodes / 4.3M edges in 1.1–2.1 s of *pure Python*, 16 MB of arrays. The spilling/partitioned CC (D:255) is over-engineering; the real CC risk is giant components from shared error bodies (87k–174k source files), not memory. |
| 6 | Simplicity as efficiency | B− | 78 | Three layers and one pointer flip are clean. Over-engineered: CC spilling, daily re-hash, weekly metadata-level verification, canary via the production site. Under-engineered: Iceberg has no compaction policy and no named catalog; "source file" has no defined key; the Python extraction layer is missing from the picture; five items are "to confirm". |
| 7 | The plan | C+ | 70 | Ordering and front-loaded validation (D:305–309) are right; the plan document contradicts revision 3 in five places, carries ~1 workstream (WS7/E1) that revision 3 deletes, has no per-workstream estimates, and 2.5–4 weeks (D:350) is not credible for the engine work in D:249–262 plus a parity check against a 353-column catalog. Reader and canary could be built now against a fixture release but are sequenced last. |

**Architecture: B+ (84). Plan: C+ (70).** Overall: the design is efficient where it matters
(O(change) raw path, a seconds-long model, small browser files) and inefficient in the places
that run forever regardless of change (verification, Iceberg growth) and in the one per-item
step it forgot (filename extraction).

## 2. Findings ranked by efficiency impact

Severity: **High** = changes a cost class or blocks the "seconds" story; **Medium** = recurring
waste or a scale ceiling within 10×; **Low** = tidy-up.

### F1. Filename extraction has no home in the design (High)
- **Evidence.** The required output is defined by `packages/house-naming`: 314 extraction rules,
  56 kinds, 106 field names in a 1.0 MB JSON catalog, applied by Python `re` with catalog-selected
  processors (README "How extraction works"; `guide.json` counts measured). Readings are keyed by
  `(body_sha256, parser_version)` (D:136); filename metadata is a function of
  `(filename, source_url)` (README "Optional source context"), not of body bytes: 564,604 distinct
  filenames across 1,683,430 source files, 241k bodies shared by several URLs. The model is "one
  SQL plan" in docspec-rs (D:155–157); 314 Python-regex rules with processors cannot be expressed
  as DataFusion SQL (different regex engine, no processors).
- **Cost.** Measured `Engine.extract(name, source_url)` on 2,742 real filenames: mean 0.31 ms,
  p99 0.71 ms. Recomputed every run: 1.68M × 0.31 ms = **8.7 CPU-min** (2.2 min on 4 vCPU),
  per day, forever, growing O(N) — the only per-item step the design would repeat. It also
  breaks "engine first": a Python pass must run between lake and model.
- **Fix.** Add a third lake table, `filename_readings (filename, source_host, catalog_version) →
  folded fields`, filled by the same anti-join work list as `readings` (D:142–143). Backfill is
  one 9-minute job; daily cost is O(new filenames) ≈ 0.3 s. The model SQL joins it like
  `readings`. This keeps Python out of the model job and the engine free of application policy.

### F2. Raw verification is O(history) work that `LIST` already answers (High)
- **Evidence.** D:116–119: weekly `LIST` of raw prefixes checking "size and digest metadata";
  daily end-to-end re-hash of 0.5 % of bodies. `LIST` returns key, size and ETag but not custom
  metadata; checking the recorded digest therefore needs a `HEAD` per object, or a receipt field
  that equals the ETag. Public doc: R2 single-part ETag is the MD5; `PutObject` verifies
  Content-MD5 atomically (R2 docs fetched today; sample ETags matched my MD5s).
- **Cost (R2 pricing: Class A $4.50/M for LIST/PUT, Class B $0.36/M for GET/HEAD, egress free).**
  Weekly LIST of 1.04M bodies: ~1,037 pages, $0.005, ~150 MB of listings — fine. Weekly HEAD per
  body: 1.04M Class B = $0.37/week and 15–30 min at 64-way concurrency (estimate); at 10×:
  $3.7/week and 2.5–5 h. Daily 0.5 % re-hash: 5.2k GETs, **3.5 GB/day = 1.3 TB/year of re-reads
  (1.8× the corpus per year)**; at 10×: 35 GB/day. Neither detects anything that a byte-exact
  ETag comparison would miss, because R2 verified the bytes at upload.
- **Fix.** Record the stored bytes' MD5 in the receipt line (it is computed anyway for
  Content-MD5, D:92). The weekly job becomes `LIST` ⟕ receipts on (key, size, ETag): zero HEADs,
  zero body bytes, O(B/1000) requests. Drop the daily re-hash to a monthly 0.01 % sample, or
  delete it. Keep the full re-hash as the explicit occasional job (D:118–119) only.

### F3. Iceberg without compaction grows O(commits) in files and manifests (High)
- **Evidence.** D:270–271: "Iceberg is used only for append and expiry"; D:143 commits one
  append per readings batch; D:130 one append per ingest run. P:962 (E7): the engine's
  iceberg-rust 0.10.1 has `fast_append` only. A fast append adds one manifest per commit and never
  merges them; snapshot expiry removes old snapshots, not the current snapshot's manifests.
- **Cost.** One day's captures append measured at **315 KB / 3,553 rows**. After one year:
  ~365 data files and ~365 manifests for `captures`, plus (batches/day × 365) for `readings`;
  every model run then opens metadata + all manifests + all data files: ~1k–3k GETs/run after
  3 years (estimate; ~10–30 s with parallelism), and O(files) bytes of footer reads. Harmless
  this year, a real tax by year three or at 10×. Manifest rewrite and data-file compaction in
  iceberg-rust: **unverified (needs engine check)**.
- **Fix.** Either (a) add a compaction/rewrite-manifests step to §5.3 and verify iceberg-rust can
  do it, or (b) write fewer, larger files (one readings commit per run, not per batch; resume via
  a local spool) and bound manifests by a periodic full rewrite, or (c) drop Iceberg for these two
  append-only logs (see §3, alternative A). Any of the three keeps "grows with change".

### F4. The catalog that makes commits atomic is not named (Medium)
- **Evidence.** D:123–125 relies on "full commit requirements (table UUID and current snapshot)"
  so concurrent writers fail. That is a *catalog* feature (REST catalog `UpdateTable`
  requirements), not a bucket feature; R2 only offers atomic conditional `PutObject`
  (`If-Match`/`If-None-Match`, verified in R2 docs today). The design names no catalog.
- **Cost.** A managed REST catalog is one more moving part and credential; a hand-rolled
  metadata pointer needs `If-Match` and is exactly what the release pointer already does
  (D:206–207). Either way it must be designed before step 3 of the appendix.
- **Fix.** Name it. If a managed catalog is used, add it to §8 and §10. If not, state that the
  table metadata pointer is a conditional PUT and that the engine sends the expected ETag.

### F5. `list.parquet` is "a few MB" only if the id stays out of it (Medium)
- **Evidence.** D:172 sorts `list` by `(filename, document_id)` and says "a few MB". Measured
  candidates built from `documents.parquet` (1,241,157 rows; filename + kind + family + committee
  + congress + role + date + extension; ZSTD, Parquet 2.0 pages, dictionaries):
  **no id: 4.05 MB (zstd-3) / 3.60 MB (zstd-9)**; 8-byte id: 15.8 MB; 32-byte binary id:
  42.5 MB; hex id: 45.9 MB. The filename column alone is 2.9–3.4 MB; the facets together are
  0.7 MB. `ids.parquet`: 14.2 MB with 8-byte ids vs 42.7 MB with 32 bytes (3.0×, confirming
  D:323–324).
- **Cost.** With the id in `list`, every visitor's daily first load is 4–11× larger than the
  design promises; at 10× scale "download whole" fails outright (40 MB without id, 160 MB with).
- **Fix.** Make the list row number the key everywhere: `list` carries no id; `detail` (same
  order) carries the full 32-byte id; `ids` maps id → row; `occurrences` is keyed by row. Sort by
  `(filename, document_id)` for determinism but do not store the id in `list`. State the 10×
  ceiling and the fallback (shard `list` by facet, or search server-side) in §7.

### F6. Point reads cost one page per column; the footer budget and the page size collide at 10× (Medium)
- **Evidence.** D:173–175 read detail/ids/occurrences by page via the offset/column index with
  "footers under 512 KB" (D:180). Measured detail file (8 columns, 1.24M rows, 64 KB pages):
  187 MB, of which document_id 41 MB, source_id 41 MB, body_key 38 MB, body_keys 39 MB — hex
  hashes are 160 MB. Estimated compressed page sizes at 64 KB uncompressed pages: ~33 KB for a
  hash column, ~5 KB for URLs, ~26 KB for the body-key list.
- **Cost.** One detail view ≈ 8 range requests ≈ 140 KB (≈80 KB with binary hashes); one id
  lookup ≈ 1 page ≈ 64 KB + manifest; one "where was this seen" ≈ 1 page (median 4 rows, max
  33,479 rows ≈ 3 MB for the pathological document). Page index for ~9k pages ≈ 150–300 KB
  (estimate), inside 512 KB today; at 10× it is 1.5–3 MB, so pages must grow 10× and each point
  read with them.
- **Fix.** Store the detail row as **one folded struct column** (D:139 already does this for
  readings): one request per detail view, ~30–60 KB. Shard `detail`/`occurrences` into fixed
  row-range files (e.g., 16 shards by list row) so each footer stays small at 10× without
  inflating pages. Binary hashes halve the hash bytes (D:129 already requires this for the lake;
  make it explicit for browser files).

### F7. Connected components: the problem is giant components, not memory (Medium)
- **Evidence.** D:255 asks for CC "with honest memory accounting and spilling or partitioning
  when large". Measured on the real graph from `filenames.parquet`: 3,960,005 nodes (source
  files + bodies + URLs + state bodies), 1.66M source–body edges, 1.31M source–state-body edges,
  1.35M source–URL edges. Union-find in pure Python: 1.1 s (body edges), 2.1 s (all edges);
  parent array = 16 MB. Components: 2.30M (body only), 951k (with URL edges) vs 1,241,157
  documents in today's model, so today's grouping rule is neither. Largest components: **87,162**
  (body only) and **174,323** (with URLs) — shared error/placeholder bodies glue unrelated
  source files together.
- **Cost.** Spilling CC is wasted engine work at any scale under ~100× (160 MB of int32 at
  10×). A giant component makes one "document" with 10⁵ occurrences, a 3+ MB range read and a
  useless detail page.
- **Fix.** Replace D:255 with "CC over int32 ids in memory; refuse above a configured node
  count". Define the edge set in the model SQL and exclude placeholder bodies (role
  `error-response`, bodies with > k URLs) from grouping; the grouping rule must be written down
  before parity can be checked (F11).

### F8. Readings backfill scope decides between gigabytes and half a terabyte (Medium)
- **Evidence.** D:141 scopes readings by media type and family (good). Today's readings cover
  231,320 PDFs (335 GB stored), 34,441 ZIPs (254 GB), ~104k XML (0.75 GB) and ~121k HTML
  (~3.3 GB). ZIP members are already captured as their own attempts (`pointer_json`
  `["archive_members", …]` rows, measured in samples).
- **Cost.** A new parser version over everything re-downloads ≈ 590 GB: 1.6–3.3 h of transfer at
  50–100 MB/s plus parse CPU, across several 6-hour jobs (estimate). Scoped to HTML+XML+VTT
  metadata: ≈ 5 GB, minutes. Daily steady state is O(new bodies) ≈ 0.5–1 GB either way.
- **Fix.** Write the scope rule into the model SQL now: no readings for ZIP containers and
  captions; PDFs only for the fields the browser shows (page count, title). Backfill in that
  order.

### F9. Content-addressed publishing dedupes nothing on a normal day (Low)
- **Evidence.** D:187 "unchanged files keep their names and are never re-uploaded"; D:196–197
  "files the live release already lists are skipped". All four browser files are globally sorted
  and row-number-linked; one new document shifts a row group and every downstream row number.
- **Cost.** 100 % of files re-upload on 100 % of days with any change: ≈ list 4 MB + ids 14 MB
  + detail ~100 MB (binary hashes) + occurrences 23–34 MB ≈ **140–150 MB and 5 PUTs per day**,
  ≈ $0.00002/day. The canary downloads the same again. Harmless; the text oversells it.
- **Fix.** Keep the mechanism (it gives atomicity and the "nothing changed" skip, D:203); reword
  D:187. Do not shard to chase dedupe: with ~1.5k new documents/day spread over 256 hash shards,
  every shard changes anyway.

### F10. Receipt `LIST` per run is O(R), not O(new) (Low)
- **Evidence.** D:130–132 lists `receipts/` and anti-joins every run; P:967 (E12) already
  flagged it. Today 2,289 keys = 3 pages; normal days add 6–59 files (mean 165/day across the
  import-heavy Oct 1–16).
- **Cost.** +18k–60k keys/year → 20–60 pages/day after a year, 100–300 after five: $0.0005–
  0.001/day and 5–30 s of sequential latency. Trivial in money, wrong in shape.
- **Fix.** List `receipts/<family>/<date>/` for the last N days per run and the whole prefix
  weekly (the rebuild check, D:133, already needs the full list).

### F11. Model parity against a 353-column catalog is open-ended (Medium, plan)
- **Evidence.** Appendix step 4: "checked against today's catalog until every difference is
  explained" (D:345). Today's pair has 353 + 356 columns, 187/195 of them near-empty lists
  (measured), hex-string ids and 47-field occurrence structs. The browser needs a few dozen
  fields (`view/` components; D:172–175).
- **Cost.** An unbounded step on the critical path; the plan's own Step 0 oracle costs 38–95 min
  per rebuild (P:90–94).
- **Fix.** Define parity on the browser-visible fields plus `document_id`/`source_id` golden
  vectors; use the existing catalog pair at `catalog-generations/596f08fa…` as the oracle (it is
  already on disk and pinned) instead of re-running the Python rebuild.

### F12. Verification and operations add moving parts without measured need (Low)
- Canary through the production site with `?release=` (D:204–205) is a headless-browser CI step
  with its own failure modes; a fixture-based reader test (D:289–290) plus a HEAD/size/row-count
  check of the uploaded objects covers the same risk at a fraction of the flakiness. Keep the
  canary if it stays under a minute; measure it.
- `status.json` per run, two retention sweeps (D:147–149, D:210–211), weekly check, daily
  re-hash: six scheduled jobs for a system whose daily change is ~300 KB of lake rows.

## 3. Alternatives evaluated

| Alternative | Measured / reasoned result | Beats the design? |
|---|---|---|
| **A. No Iceberg:** one dated Parquet file per ingest run plus a content-addressed manifest written with `If-Match`; readings the same per parser version. | Same atomicity (R2 conditional PUT is verified); 2 PUTs per commit vs 4+; no catalog; no manifest growth beyond the one manifest list; no expiry/orphan jobs (immutable files, a manifest rewrite compacts). Loses time travel and the engine's existing Iceberg code. | **Yes on moving parts, tie on cost.** Iceberg is justified only because the engine already has it (P:962). If F3/F4 cannot be closed cheaply, take A. |
| **B. Incremental model by partition** (plan WS7/E1: keyed merges, one dataset per kind, P:956, P:571–651). | Recompute measured at 3.7 s for the relational plan; CC 1–2 s; export of 1.4M rows 0.6 s. Incremental saves nothing measurable and adds merge specs, key pruning and copy-on-write files (P:962). | **No.** Revision 3 is right (D:52–54, D:315). Delete WS7's incremental prototype from the plan. |
| **C. DuckDB-WASM in the browser** over the same Parquet. | Adds ~5–10 MB of WASM (estimate), gives SQL and range-read pushdown, but the hot path (substring search over 1.24M names) still wants the whole filename column (3 MB). | **No at 1×**, worth revisiting at 10× where whole-list download fails (F5). |
| **D. One combined browser file** (list+detail+occurrences). | Point reads need small pages; whole download needs small files; one file forces one page size. Measured detail = 187 MB; combined ≈ 230 MB first load. | **No.** The four-file split is correct. |
| **E. Skip readings for most bodies.** | 400k caption/ZIP bodies carry no browser-visible body facts; skipping cuts a new-parser backfill from ≈590 GB to ≈5 GB (PDF metadata ≈335 GB is the real decision). | **Yes**, and D:141 already permits it; make it explicit (F8). |
| **F. Verify raw via `LIST`+ETag instead of HEAD/re-hash.** | 1,037 Class A/week, 0 bytes of bodies, vs 1.04M HEADs + 1.3 TB/yr of GETs. | **Yes** (F2). |
| **G. Row-number-keyed browser files (no id in `list`).** | 4.05 MB vs 15.8–45.9 MB; ids/detail/occurrences unchanged. | **Yes** (F5). |
| **H. Compute `filename_readings` once per (filename, host, catalog_version).** | 9 min backfill once vs 8.7 CPU-min per run. | **Yes** (F1). |
| **I. Partition releases to make dedupe real.** | Any key correlated with change (capture month) breaks "same row order as list"; hash sharding touches every shard daily. | **No.** Accept 150 MB/day (F9). |
| **J. Spilling/partitioned CC** (as designed, D:255). | 16 MB of int32 at today's scale; 160 MB at 10×. | **No.** In-memory CC with a hard cap (F7). |

## 4. Separate grades

**Architecture (revision 3): B+ (84).** Right shape: raw log → two append-only lake tables →
one deterministic job → one pointer flip; O(change) where it matters; small typed bytes; the
model really is seconds (3.7 s proxy at 1.75 GB; identical bytes across thread counts). Marked
down for the O(history) verification jobs (F2), Iceberg growth without compaction and an unnamed
catalog (F3, F4), the missing filename-extraction layer (F1), the over-stated `list` size (F5)
and CC machinery aimed at the wrong risk (F7).

**Plan (simplification plan + appendix): C+ (70).** Strengths: dependency ordering, "tests
before cuts", measured line counts, the validation gate in D:305–309 before building. Weaknesses
that cost time, not just clarity:
1. It contradicts revision 3 in five places and nobody has reconciled them: (a) WS7/E1 keep
   engine-native *incremental* updates and keyed merges (P:579–581, P:602–605, P:956) while
   D:52–54 and D:315 recompute; (b) E1 migrates the raw *index* leaves to engine datasets
   (P:956) while revision 3 has no raw index at all (`captures` is the index, D:127–133);
   (c) WS6 lays releases out as `releases/<id>/…` (P:517) while D:196–197 uses shared
   content-addressed `objects/<sha>`; (d) WS8 reworks news_lake (P:653–718) while D:327 puts it
   out of scope; (e) WS9 is a deletion list (P:720–754) and contains none of the seven new engine
   capabilities in D:249–262, which are the critical path.
2. Step 0 (P:62–151) measures a Python rebuild that revision 3 makes irrelevant except as an
   oracle; the pinned catalog pair already serves as that oracle without a 95-minute run.
3. No per-workstream estimates anywhere; the only number is "2.5–4 weeks" (D:350). My
   estimate for one engineer: engine capabilities 3–6 weeks (Iceberg append/expiry/orphan
   against R2 with a catalog, deterministic multi-file export with hashing, CC, bounded pools,
   CLI), lake tables and backfills 1–2 weeks, model SQL and parity 2–4 weeks (open-ended as
   written, F11), release pipeline and reader 1–2 weeks, deletions 1–2 weeks: **8–16 weeks**.
   Parallelism exists but the plan does not use it: the reader, canary and release format can
   be built today against a fixture release (I produced list/ids/detail/occurrences from the
   pinned catalog in 24 s), and the two highest-risk measurements (iceberg-rust on R2, including
   E7's unmeasured 2 MiB cap; deterministic export + CC on real data) should run in week one.
4. Risk front-loading is half right: D:305–309 validates compute before building, but nothing
   validates the catalog/commit path, the filename-extraction placement, or the parity
   definition before the deletions in WS6/WS7 start.

## 5. The three changes that would most improve efficiency

1. **Make raw verification `LIST`-shaped.** Record the stored MD5 in receipts; weekly
   `LIST ⟕ receipts` on (key, size, ETag); no HEADs; retire the daily 0.5 % re-hash (1.3 TB/yr)
   in favor of a tiny monthly sample. Removes the only work in the system that grows with
   history instead of change, at every scale.
2. **Give every per-item computation a lake table, and key the browser by row number.** Add
   `filename_readings (filename, host, catalog_version)` next to `readings` (one 9-minute
   backfill instead of 8.7 CPU-min per run); keep ids out of `list.parquet` (4 MB, not 16–46 MB);
   store detail as one folded struct column (one range request per detail view); binary hashes
   everywhere; shard detail/occurrences by row range so footers stay small at 10×.
3. **Close the Iceberg questions or drop it, and re-cut the plan around revision 3.** Name the
   catalog and add a compaction/manifest-rewrite policy (or use dated Parquet + conditional
   manifest); define CC as in-memory int32 with placeholder bodies excluded; delete WS7's
   incremental prototype and E1's raw-index migration; define parity on browser-visible fields
   against the pinned catalog pair; build reader and canary against a fixture release now;
   replace "2.5–4 weeks" with per-step estimates and two week-one measurements (iceberg-rust on
   R2; deterministic export + CC on real data).

## Appendix A. Measurement log

| Measurement | Method | Result |
|---|---|---|
| Captures profile | DuckDB over `captures.parquet` (4 threads, 6 GB) | counts in §0; per-day table; receipts: 2,289, median 199 lines |
| Schema/compression dump | PyArrow metadata of 4 tables + 721 readings files | 353/356 columns; 187/195 near-empty list columns = 21.9/16.8 MB; hex-id columns dominate |
| Compact captures | DuckDB: `unhex` hashes, drop `body_key`, sort by URL, ZSTD | **157 MB vs 270 MB**; one day = 315 KB / 3,553 rows |
| Browser `list` candidates | PyArrow from `documents.parquet`, ZSTD 3/9, Parquet 2.0, page index | no id 4.05/3.60 MB; bin8 15.8 MB; bin32 42.5 MB; hex 45.9 MB; 8-byte prefix collisions: 0 |
| `ids` candidates | sorted (id, row) | bin8 14.2 MB; bin32 42.7 MB; hex 44.3 MB |
| `detail` candidate | 8 columns, pages 64/256/1024 KB | 187 MB; hashes 160 MB; FileMetaData 5 KB (page index extra) |
| `occurrences` candidates | flatten `source_occurrences` (projected before unnest) | 4,727,694 rows; 22.7–33.6 MB |
| Model relational proxy | DuckDB, 4 threads, 10 GB: url_state (1,158,426), sources (1,418,194), readings join, list-agg members, 3 sorted ZSTD exports | **3.7 s total**, 1.75 GB DuckDB, 3.9 GB RSS; byte-identical at 4 vs 2 threads |
| Connected components | DuckDB edge lists + pure-Python union-find | 3,960,005 nodes; 1.1–2.1 s; largest components 87,162 / 174,323 |
| Filename extraction | `house_naming.Engine.extract` on 2,742 sampled (filename, source_url) | mean 0.31 ms, p99 0.71 ms, max 7.6 ms; 8.7 CPU-min per 1.68M |
| Public origin | 6 GETs + 1 Range GET, UA `congressional-tech-review/1.0` | `application/gzip`, no `Content-Encoding`; 206 + CORS `*`; ETag = MD5; receipt lines 480–980 B gz |
| R2 facts | developers.cloudflare.com (pricing, bucket-locks, S3 extensions) | Class A $4.50/M, Class B $0.36/M, egress free, storage $0.015/GB-mo, free tier 1M A / 10M B; locks by prefix, indefinite, allow creates, ≤1,000 rules; `PutObject` `If-Match`/`If-None-Match` atomic (not on multipart) |
| Body size extremes | DuckDB max per sha | max 1.19 GB; 0 bodies > 5 GB (single conditional PUT suffices everywhere) |

What the proxies cannot show: DataFusion's memory-pool and spill behavior (DuckDB's differ);
readings parse CPU per body (not measured; PDF parsing dominates if in scope); iceberg-rust's
commit, expiry, orphan and compaction behavior against R2 (unverified, needs engine check);
hyparquet's decode speed for a 4 MB ZSTD list (the site already depends on `hyparquet 1.31.2` +
`hyparquet-compressors 1.1.2`, so ZSTD is readable in the browser).

## Appendix B. Daily and backfill I/O budget (estimates from measured sizes)

| Step | Requests / normal day | Bytes / normal day | Backfill once |
|---|---|---|---|
| Captures ingest | 3 LIST + ~50 GET + ~5 PUT (Iceberg commit) | ~50 KB in, 315 KB out | 2,289 GET, 1.08 GB gz (~30 GB JSON to parse: minutes in Rust) |
| Readings (scoped, F8) | ~1k GET + 1–5 commits | 0.5–1 GB in | ≈5 GB scoped; ≈590 GB if PDFs+ZIPs |
| Model + export | ~10–20 GET today; O(files) later (F3) | lake ≈160 MB in | — |
| Publish + canary | 5 PUT + 2 PUT (manifest, pointer) + canary GETs | ~150 MB out, ~150 MB in | — |
| Verification as designed | weekly 1,037 LIST + 1.04M HEAD; daily 5.2k GET | 3.5 GB/day in | — |
| Verification as proposed (F2) | weekly 1,037 LIST | ~150 MB/week | — |

At 1× every row is inside R2's free tier; at 10× the only line that leaves "trivial" is the
verification row as designed (10.4M HEADs/week, 35 GB/day), which F2 removes.
