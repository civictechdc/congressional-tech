# Congressional Document Archive: Implementation Plan

**Editor's Draft, 2026-10-24**

## Abstract

This Note describes how to move the current congressional-tech and docspec-rs code to the system specified in [[ARCHITECTURE]] and [[DATA-MODEL]]. It gives the strategy, the constraints, the order of work and its dependencies, and what is built, changed and deleted. It has no schedule and no effort estimates: the work runs in dependency order.

## Status of This Document

This is a Note, not a specification. It implements the two companion specifications and carries no normative requirements of its own; where it says "must", it restates a rule from them or a working rule for the project. Comments should be directed to the editor.

## Table of Contents

1. [Introduction](#1-introduction)
2. [Strategy](#2-strategy)
3. [Constraints and Rules](#3-constraints-and-rules)
4. [Order of Work](#4-order-of-work)
5. [First Steps](#5-first-steps)
6. [Tracks](#6-tracks)
7. [Parked](#7-parked)
8. [Keep List](#8-keep-list)
9. [Open Issue](#9-open-issue)
10. [References](#10-references)

## 1. Introduction

The raw log already exists: bodies, receipts and provenance in the R2 bucket `congressional-tech-raw`, backed up on 2026-10-24. It is preserved unchanged; existing bodies keep their stored form, and older gzip PDFs gain uncompressed copies. Everything above raw is rebuilt.

Already in place when this Note was written: the hosted setup refuses an engine revision other than the qualified one; the capture schema carries `stored_sha256` from the receipt and never derives it; `delete_gzip` is deleted; and the 12,431 recoveries that existed only in `accepted.json` have a write-once backup under `provenance/recoveries/`. The bucket lock is pending with the owner.

## 2. Strategy

Build the target beside the old pipeline, switch publishing to it, then delete the old layers whole. Refactoring the old pipeline piece by piece is wasted work, because the target replaces most of it.

**What survives** and is fixed now: fetchers and raw writers, recovery imports, review tools, `house-naming`, the site, and docspec-rs.

**What goes** at the switch, with no new work before then: the Python catalog (incremental and rebuild), the raw index and its routing, the viewer-publication journal route, the v6 preparer, and the shims around them.

**Until the switch,** the old capture job keeps writing raw data and reading the raw index. It gets raw-safety fixes only. Its whole-leaf index rewrites continue until then; that is accepted.

## 3. Constraints and Rules

**What must survive:** objects in `congressional-tech-raw` under `bodies/`, `receipts/` and `provenance/`. Everything else can be rebuilt, and nothing uses it yet.

**Rules for every step**

- One conceptual move per PR. Tests that pin behavior land before code moves. Behavior changes go in their own PRs.
- Run checks only through the project runners: `.venv/bin/python scripts/dev.py test <lane>` in congressional-tech and `scripts/check` in docspec-rs. Never use a tool from `PATH`. Say this in every agent and reviewer brief.
- Work in a separate worktree and venv. The primary checkout backs live recovery jobs.
- Report before and after `wc -l` in every PR that deletes code.
- Each step names its evidence: a test, or a measurement committed under `docs/`, never in the gitignored `output/`.
- Create the ticket before the first code commit. An epic closes only after its children. Acceptance criteria name an observable behavior and the test or measurement that shows it. Performance work records a baseline on real data and the decision rule first. A deletion closes only when the old path is gone.

**Raw check (R-check)**

1. Before and after each merge that touches raw writers, list `receipts/` and `bodies/` read-only. Every earlier key is still there with the same size and ETag; only additions are allowed.
2. Every receipt-referenced body exists.
3. After the bucket lock: read the lock rules back after any infrastructure change.

**Other settled points:** no exclusion list will exist; wrong `stored_sha256` index rows are repaired in place; recovery imports refuse uncommitted code.

## 4. Order of Work

1. The bucket lock (owner) and the cut-off re-fetch (B14).
2. The two measurements (M1, M2) and the semantic checkpoint (S).
3. The converted first release (F0) and the hand-built fixture; the first engine moves (C0); tracks A and B, with B13 after B1 and B3.
4. Track C.
5. Track D.
6. Track E, with E1 already written in S.
7. Track F.

| Track | What | Depends on |
|---|---|---|
| A | Site reader and canary | F0 and the hand-built fixture |
| B | Raw writers and protection | The bucket lock, for B1 and B13 |
| C | Engine capabilities | M1, M2, S |
| D | Lake tables and backfills | C2, B2; B16 for D5 and D6 |
| E | Model SQL and parity | S, C1, C3, C4, D, F0 |
| F | Switch and delete | A, E |

A and B can run beside C. The widest uncertainty is E: it stays bounded unless parity finds facts that only derived tables hold (§9).

## 5. First Steps

### 5.1 M1: Basin Catalog Commits Under Maintenance (docspec-rs)

1. **Conflict retry.** Plain appends already send their commit requirements. M1 tests what is new: an append that races a Basin compaction recomputes its work list and lands, and two ingest runs on the same receipts leave exactly one copy of each row ([[ARCHITECTURE]] §8.1).
2. **Manifest growth.** Append 400 day-sized batches (about 315 KB each) to a scratch table with Basin compaction and snapshot expiration enabled. Count data files and manifests in the current snapshot before and after maintenance runs.
3. **The remote write cap.** The engine caps every file it writes to R2 at 2 MiB and every row group at 2,048 rows, with no recorded reason. That splits a 150 MB table into about 70 files and weakens dictionary encoding. Measure scan and commit cost with and without it on the scratch table, and keep it only if it measurably helps.

**Decides:** Iceberg stays (manifests bounded), or the lake tables move to dated Parquet with an `If-Match` manifest ([[ARCHITECTURE]] §8.8). The fallback changes the scope of C1, C2 and D.

### 5.2 M2: Wide Joins and Grouping in a Throwaway DataFusion Harness

The engine cannot run the full export until C1, C3 and C4 exist, so a short standalone DataFusion program measures first, using S's draft grouping rule.

- Inputs: the pinned 2026-10-19 snapshot (captures `db033173…`, catalog generation `596f08fa…`), including today's filename readings.
- Run the model's joins, including filename readings, the folded `detail` and the 4.7M `occurrences`, and report the size of every hash-join build.
- Group the real graph with the specified rule. Record time, peak memory and the largest components.
- Run on `ubuntu-24.04` (4 vCPU, 16 GB), the smallest runner class.

**Decides:** the size of track C, and whether DataFusion handles the wide joins within the pool. The harness is deleted afterwards. Byte-for-byte determinism becomes C3's acceptance test.

### 5.3 S: The Semantic Checkpoint

E1 is written here, before track C, because M2 and the engine work depend on it:

- the grouping rule as SQL, with adversarial fixtures: a PDF replaced while its XML stays, historical pages linking both, archive members, a recovery-only link that later downloads, a reviewer's merge and hide;
- a hand-labeled stratified sample of a few hundred files, covering short real pages, archive members, landing pages, listing pages, files listed together on one page and widely mirrored real documents, measuring how often the page-shape, error-sign, listing-page, placeholder and rendition rules wrongly include, exclude or join a file. The labeling rubric: a file is a real document when its main content is the document itself (testimony, a report, a transcript, a bill, a hearing record), not a list of links to documents, a landing or error page, or metadata about a document; two files are one document only when they are the same text in different formats;
- a check that every rule can be computed from raw, with nothing borrowed from the old derived tables.

### 5.4 F0: The First Release, Converted From the Pinned Catalog

- Convert the pinned catalog pair into the release format ([[ARCHITECTURE]] §10.1) with the final writer settings: offset indexes, the folded `detail`, `links` keyed by body prefixes. Use the engine's RunSpec where it can. Existing measurement scripts show the shape: `measurements/build_list.py` built `list`, `ids` and `detail` in 24 s, and `size_occ_captures.py` built `occurrences`.
- This release is the reader's fixture (track A) and the parity oracle (E4). Its manifest records that it came from the pinned catalog. It does not go live: the explorer waits for the engine-built release.
- **It fills what it can:** meeting keys from URLs, document dates from the old metadata, link labels from the old occurrences, and committee names from today's committee file. It keeps all 1.24M of today's catalog rows, so it is about twice the target `list`.
- **It cannot show** format groups, meeting titles or the new recovery kinds, so a small hand-built fixture release covers them: one document with PDF and XML alternates, one titled hearing, one of each recovery kind and one hidden document. The contract test runs both.
- **It assumes nothing unique about old bodies:** 141,762 body keys appear in several old documents, so F0 resolves each link key to the first document in list order. Correctness is checked by E4's comparison, keyed by source evidence.
- The converter is a migration tool, deleted at the switch.

## 6. Tracks

### 6.1 Track A: Site Reader and Canary

1. **A reader module for the release format:** pointer → manifest → `list` in a Web Worker, decoded column by column into arrays and dictionary codes; `detail` by row with hyparquet's `useOffsetIndex`, its offset index fetched once per session and cached; `links`; `occurrences`; shards. No DOM dependency. Accepts the current and previous `schema_version`. On a 404 for a release file, it re-reads the pointer and reloads.
2. **Links** carry a 16-hex file fingerprint and resolve through `links` to whichever document holds that file now.
3. **The Node canary** ([[ARCHITECTURE]] §10.4.5), run by the publish job against the uploaded candidate, with a heap budget for a mid-range phone and the 404 reload.
4. **A CI contract test:** the real site in a headless browser against F0 and the hand-built fixture, within the heap budget. It moves to a release built from a fixed sample of real receipts once track E exists.
5. **Saved copies:** link the saved file ([[ARCHITECTURE]] §9.4), with other formats as alternates. Older gzip PDFs open their `.pdf` copy (B13). Other older gzip bodies are fetched, unpacked with `DecompressionStream`, and opened with the media type from `detail`. Those over 100 MB (579) are offered as a labeled compressed download.
6. **Dates:** the document date and the capture date in list rows, so same-filename editions read apart, and on the document page the document date with its source and the first and last capture dates, with the labels of [[ARCHITECTURE]] §9.4.
7. **Recoveries:** each one on the page the attachment rule gives it ([[ARCHITECTURE]] §9.6), labeled by kind, with its recovered URL, match basis, evidence digest and identity note, and a link to the recovered file.
8. **Link context:** "where each copy was seen" names the page that linked it and the link's label.
9. **Meetings, dates and record links:** filter and sort by document date; list every document for a hearing under its title, date, type and committee; link out to the GPO record, the bill and the member.
10. **Removed by review:** a hidden document's link opens a note with the reason and date.
11. **Speed, measured then fixed:** measure startup, search, detail and heap on real phones and desktops with F0, then write those targets into the canary and contract test. F0 is about twice the size of the target `list`, so these targets are conservative; re-measure once track E produces a real release.

**Done when:** the site loads F0 locally on desktop and in a phone-sized profile, and the canary passes against F0 in under a minute. Opening older gzip PDFs through their `.pdf` copies waits for B13.

**Replaces at the switch:** `catalog-v6.ts` and its v6 and ExportPin branches, the v6 paths in `worker.ts`, and `verify-live-publication.mjs`. `cache.ts`, `withVerifiedJson` and `startup.ts` stay where they fit.

### 6.2 Track B: Raw Writers and Protection

This code survives, so it is fixed now.

1. **Bucket lock** (owner) on `bodies/`, `receipts/` and `provenance/`. The single most protective step; it gates B13.
2. **Receipts and bodies to [[ARCHITECTURE]] §7.1–7.2:** every receipt line records the sniffed format beside the server's media type and the HTTP status; `stored` lines record the stored MD5 and size; new compressible bodies are stored with `Content-Encoding: gzip` and the original `Content-Type`, new PDFs as-is; one create-only PUT per body with Content-MD5, never multipart; a 412 is recorded as `unchanged` with no HEAD and no comparison; the fetcher spools each body to a temporary file and never cuts one off, and a `size_limit` or `request_failed` outcome is retried; receipt keys use the UTC write date; lines carry the run ID and writer identity, one entry per referenced body with its path inside an archive, and the links found with their labels, and drop the provider metadata, duplicated headers and old raw-index row ([[DATA-MODEL]] §5.2).
3. **One namespace policy for raw keys.** Write the refusal matrix first: every writer (`R2Store.put`, `put_file`, `put_pdf_body`, `AsyncBodies.put`, `LocalStore.put`) refuses a write that is not create-only under `bodies/`, `receipts/` or `provenance/`, before any I/O. Then delete the `immutable` flag.
4. **Ingest policy set once,** where capture builds its store. Delete the exclusion gate (`raw_storage.py:75-236`, 162 lines).
5. **Body existence by key:** a create-only PUT and its 412, plus an in-run set. No index lookup.
6. **One body layout.** The hand-written layout writers call `put_body`: `committee_explorer/parquet.py:406-428`, senate `seed_fetch`, and the e2e harness.
7. **Code identity for recovery imports:** the git tree hash plus the `uv.lock` digest, refusing uncommitted changes under `packages/` or `scripts/`.
8. **Reconcile `accepted.json` with the receipts,** so recoveries become provenance records the model reads.
9. **The weekly maintenance job** ([[ARCHITECTURE]] §7.4, §10.4.7): LIST joined to each body's creating receipt line, a one-time re-hash of any body with no creating line, the 25-body sample, the orphan report and release retention. It joins to the old capture index until D1 exists.
10. **The one-time full re-hash** of bodies written before receipts carried an MD5, with their ETags recorded under `provenance/verification/`.
11. **A ratchet test:** `PYTEST_CURRENT_TEST` may not appear in surviving packages. Delete the raw-adjacent substitution in `raw_storage.py:655-672` now; the other sites (75 in all) go with the old layers.
12. **Owed while the old capture path runs:** repair wrong `stored_sha256` index rows in place, and confirm the daily capture writes correct values. The target reads receipts, so these matter only until the switch.
13. **Uncompressed copies of older gzip PDFs** (after B1 and B3; track A's saved copies need them). The largest raw write in the plan, so the lock and the refusal matrix come first. First fold `migrate_pdf_bodies_to_uncompressed` into `backfill_uncompressed_pdfs` (`pdf_backfill.py`), so one path remains. Then run it over every older gzip PDF: create-only to `bodies/sha256/<aa>/<sha>.pdf`, with Content-MD5, and the decompressed SHA-256 checked before upload. About 261,055 uploads and 403 GB once decompressed (about $72 a year of storage under the lock). Copies that already exist return 412 and are skipped.
14. **Re-fetch the cut-off files** (first, in today's capture path): the 62 URLs whose only copy was cut off at 64 MiB. The cut-off copies stay in raw.
15. **The 2026-10-15 recovery run needs no correction.** All 5,587 lines of `receipts/documents/2026-10-15/download-filename-recovery-all-*` are `retained_import` recoveries with a synthetic HTTP 200 (5,154 recovered copies, 341 hearing-record excerpts, 92 official substitutes). The old capture index had flattened them into fetches. What remains is in D1 and E1.
16. **Committee and meeting fetches through the raw writer:** `acquisition/committees.py` and `acquisition/meetings.py` stop writing their own output files and fetch through the raw writer like every other fetch.

**Done when:** the refusal matrix passes, the lock is on, one capture run's `stored` lines carry MD5s that match the stored ETags, every older gzip PDF has its copy, and the 62 cut-off URLs have complete copies or a recorded reason.

### 6.3 Track C: Engine Capabilities (docspec-rs)

**C0, first moves on engine main** (beside M1): revert the deferred-commit mode and delete the dataset-name predicates; both came after congressional-tech's pin, so nothing depends on them. Hash while writing, and stop HEADing and re-downloading immutable files (also C5).

**Then the capabilities of [[ARCHITECTURE]] §13:**

| # | Capability | Evidence |
|---|---|---|
| C1 | Multi-input SQL plans over Basin tables and Parquet files in one context | A plan joining two tables and a file |
| C2 | Append through the REST catalog, with the conflict retry | M1's two tests |
| C3 | Deterministic multi-file export: SHA-256 and MD5 while writing; per-file writer settings, including offset and column indexes, page sizes and row limits, and per-column encodings such as delta-encoded filenames; fixed row counts per row group; unique sort keys; row-range shards | Byte equality across threads, input orders, batch sizes and a forced spill; hyparquet page reads on the output |
| C4 | ConnectedComponents in memory over 32-bit IDs, refusing above a node cap | M2's graph; a refusal test |
| C5 | Streaming I/O: no re-read or HEAD of immutable files | Request counts in a test |
| C6 | Bounded threads, memory pool and scratch; wide folded columns kept off hash-join build sides | A join at the pool limit fails clearly; M2's build sizes |
| C7 | A CLI that runs a declarative job spec and returns a machine-readable result | The M2 export as a job spec |

The engine's current export disables the offset index unless page-index columns are named (`export/pipeline.rs:687-697`), so C3's per-file settings are required, not optional.

**Not needed any more:** the lifecycle store's commit requirements, lifecycle-store compaction on R2, copy-on-write measurement and insert-if-absent. The target has no engine lifecycle store, no updates and no news_lake work. Close them unless another consumer needs them.

**Done when:** one CLI job runs the full export from Basin tables, byte-identical across threads, input orders and batch sizes and with a forced spill, on the smallest runner.

### 6.4 Track D: Lake Tables and Backfills

1. **`captures`** ([[ARCHITECTURE]] §8.2, [[DATA-MODEL]] §6.1):
   - ingest from date-shaped prefixes only, per family, from the newest ingested date;
   - backfill from all 2,289 receipts (1.08 GB compressed), including the non-date segments (`undated/`, `mixed-dates/`: 49 files, 2.2M rows); older receipt shapes are mapped in the ingest SQL, with a test sample of each shape;
   - the key is `(receipt_key, receipt_line, capture_index)`; each row carries `member_path` and `run_id`;
   - a line with no body still yields one line-only row, with the line's own fields on every row; the backfill restores the statuses today's index dropped for 1.04M bodiless lines;
   - recovery imports keep `mode`, `publisher_requested`, the recovery category and the original link as columns;
   - **`page_links`** is filled from each line's links, with its own work list and commit, and keeps each link's `source_xpath`; a receipt with no links gets a completion row; a lag shows as missing link context, not a failure;
   - the rebuild-equivalence test;
   - **compare with the pinned old capture index** (3,909,134 rows) on receipt-derived columns, with written transformation rules for the expected differences: statuses restored on bodiless lines, `stored_md5` new, `stored_sha256` gone. A row that exists only in the old index is a fact raw does not hold, and it blocks the switch until the owner decides (§9).
2. **`readings`** ([[ARCHITECTURE]] §8.3): one parser and version per media family; partitioned by `(parser, parser_version)`; a version is complete when its work list is empty. The scope in the model SQL excludes ZIPs and captions.
   - First the `sniff` parser runs once over every older body: one ranged read of its first bytes, about 1.04M GETs, under an hour. The real-file rule needs a sniffed format and record role for every body.
   - Then backfill HTML, XML and JSON (about 5 GB). There is no PDF parser for now.
   - The readings core carries what the rules read: format, record role (including `listing`), title, heading, visible-text size, link counts, content date, error signals and fingerprint. Formats with no parser take their record role from the sniffed format.
   - The `fingerprint` parser handles only the bodies at endpoints with two or more complete real files (148 endpoints, 297 bodies, about 1.4 GB): for ZIPs it digests member hashes from `captures`; for PDFs it extracts the text. It runs last in each publish, before the snapshots are pinned.
   - While a newer parser version backfills, the daily run applies the version the model reads to new bodies too.
   - The parser functions survive; the adoption machinery around them goes in F3.
3. **`filename_readings`** ([[ARCHITECTURE]] §8.4): a producer that runs `house-naming` over the work list and appends through the engine. It applies the effective-filename rule ([[DATA-MODEL]] §7.3) to choose its inputs, and writes the typed `filename_date`, `measure_keys`, `bioguide_ids` and `gpo_package_id`, so the model never unnests the field list. Multi-valued facets stay lists, an input house-naming cannot read gets a status row, and superseded catalog versions are kept. Backfill is 7–18 minutes over 1.39M pairs.
4. Enable Basin compaction and snapshot expiration on all six lake tables.
5. **`committee_records`** ([[ARCHITECTURE]] §8.6): the JSON parser reads each committee API response once, with a completion row for a response with no committees (needs B16).
6. **`meeting_records`** ([[ARCHITECTURE]] §8.7): the JSON and XML parsers read each meeting response once, with completion rows (needs B16).

**Done when:** all lake tables exist with complete backfills, and both `captures` comparisons pass.

### 6.5 Track E: Model SQL and Parity

1. **The grouping rule, written in S** as SQL with a short rationale ([[ARCHITECTURE]] §9, [[DATA-MODEL]] §7):
   - which responses are real files: record role `document`, any content format, and the web-page checks, with no listing pages. Formats with no parser take their record role from the sniffed format. The link-shape patterns are an exact list of regular expressions: start from the broader list (44,047 file-shaped bodies), sample the roughly 27k between it and the narrow list (16,775), then fix it;
   - the registries ([[DATA-MODEL]] §2): page shapes, error words, URL wrappers and strip-list, generic stems, recovery kinds, API endpoints and import runs, each a versioned table with sample tests;
   - which documents are listed: at least one real file or one recovery;
   - recovery imports are evidence for their original link, never real files, `url_state`, fingerprint candidates, link keys or capture dates; the written recovery-kind mapping, where an unmapped category fails the build;
   - import runs, listed in the import-run registry by run ID, never by date: their rows give an "in our archive since" date, never a capture date;
   - the committee mapping: House codes as `hs` plus the lowercased code, joined to `committee_records` by congress, with unmapped codes reported by count;
   - `real_body`: a body with at least one real capture row; a source file is a real file when at least one of its capture rows is real, and only real files join edges;
   - API responses: JSON fetched from the endpoint list, with a sample URL test per entry;
   - recovery attachment: a recovery joins the one listed document holding its original link; with none or several, it gets a document of its own from a bodiless source file;
   - total orders for every "earliest" pick (`linked_from`, `first_run`) and a fixed order for every list column;
   - the `url_state` recheck intervals, as a `(family, interval)` policy table;
   - `url_key` for every link join: the wrapper patterns and the strip-list, each entry with a real sample URL as a test;
   - the edge set: identical real files connect, web pages included; placeholders (more than *k* = 100 distinct context URLs) connect nothing; a shared endpoint connects two complete files only when their text fingerprints match; renditions connect through publisher groups or, failing that, same-directory same-stem files with document extensions and a list of generic stems to exclude, and a group joins only when its files all have different formats, one per format;
   - the saved file, in one total order: format preference (PDF first), then newest first fetch with undated files last, then body hash; the rest are alternates;
   - the document date: the filename date, else a content date, else the earliest meeting date, with its source recorded; kept separate from the capture date;
   - the ID formulas, byte for byte: today's compact-JSON serialization and inputs ([[DATA-MODEL]] §7.3–7.4);
   - `url_state`, keyed by requested URL and counted over receipt lines, not capture rows;
   - editions stay apart: no rendition edge at an edition-ambiguous endpoint;
   - archive members judged and named by their own path;
   - review semantics: supersession, `hide` with its note, `duplicate_of` as a merge edge, overrides;
   - each document's meetings joined to `meeting_records`.
2. **The model SQL,** with the 22 invariants of [[DATA-MODEL]] §10 as its test suite: `url_state`, `filenames`, `documents`, `members`, `recoveries`, `reviews`, and the release files, with `list` sorted by filename, document date and capture date (undated rows last within a filename), every recovery labeled by kind, and each document's meeting keys, document date and official record keys.
3. **Golden vectors** for `source_id` and `document_id`, generated from Python `source_identity` and `compute_document_id` (`retention/index/bipartite.py:165,197`) with their compact-JSON serialization, and checked in the engine's tests. The formulas keep the logical body key string `bodies/sha256/<aa>/<sha>.gz`.
4. **Parity against the old catalog,** on browser-visible fields, compared many-to-many and keyed by source evidence (the files and URLs each document holds), since old body keys can sit in several old documents. Expect large, explained changes: about 560k catalog rows leave the list (captions, metadata records, playlists, API responses), listing pages leave it, about 30k documents lose error pages from their body sets, about 4,900 lose Senate landing pages, cut-off copies and recovery imports drop out of body sets, and about 16k format groups merge (32,547 documents today).
   - **The comparison reports by cause, not by document:** each known cause with its count and a few sampled examples, and every difference that fits no known cause listed separately. Only that last group needs reading one by one.
   - Classify each unexplained difference: a rule change (fine, recorded with the rule); an old-pipeline error (the new model wins); or a fact that exists only in derived tables (a blocker, §9).

**Done when:** every known cause has its count and samples, every unexplained difference is classified with no blocker left, and the model runs as a CLI job on the smallest runner.

A full Python rebuild of the old catalog is not needed: the pinned catalog pair, converted in F0, is the oracle.

### 6.6 Track F: Switch and Delete

1. **Publish workflow** ([[ARCHITECTURE]] §12): the capture job; the publish job (ingest, readings, filename readings, committee and meeting records, fingerprints, then pin snapshots, input identity, early skip, model, export, canary, flip, status); the weekly maintenance job. Delete the disabled viewer workflow and its 30-minute cron.
2. **Capture reads `url_state` from the live release** and stops reading the raw index.
3. **Delete the old layers,** one PR per group, measured at cut. Earlier counts are the estimates:

| Group | Estimate (source + tests) |
|---|---|
| Python incremental catalog: 22 modules, the `catalog/` facade, `incremental_boundary_proof.py` | 9,509 + 6,744 |
| Python rebuild path, replaced by the model SQL: `catalog_staging`, `catalog_publication`, `catalog_cache`, `catalog_validation`, `index/*`, the oracle files | at cut |
| Raw index: `partition_routing`, `raw_state_routes`, `raw_changes`, the Python merge, the `raw.json` schema backfills, the retention planner (147) | at cut |
| Viewer publication: the journal, resume and attempt route | 2,786 + 2,005 |
| Viewer publication: the v6 preparer and the v6 reader branch | 1,695 + 1,112 |
| `docspec_client`'s HTTP custody path, with its fallbacks and the pure-Python `blake3`, if nothing else uses it | at cut |
| Shims and legacy formats | 2,064 + 1,058 |
| Measurement scripts for deleted subjects | 1,862 + 723 |
| The F0 converter and the one-off PDF copy job (after B13) | at cut |
| The custom-domain path allowlist and its tooling: `r2_edge_rules.py`, `apply_r2_edge_rules.py`; CORS, cache headers, CSP and the `?filename=` rule stay | at cut |
| docspec-rs: unused routes, lifecycle families, the Dagster adapter, provider suites, `cli_args.rs`, hand-written SHA-256, date transforms, legacy formats | 14,383 certain, up to 2,101 more |

The engine cuts apply only to code no consumer uses after the switch; check `spicysearch`, `spicyengine` and `DocSpec` as well as congressional-tech. The independent ones (`sha2`, date transforms, `cli_args.rs`, the Dagster adapter) can land any time.

**Done when:** the explorer serves an engine-built release, the old workflows are gone, and the deleted line counts are recorded.

## 7. Parked

- **news_lake** keeps the DocSpec backend. No work until it adopts the three layers.
- **The freeze:** no browser or engine performance work beyond this plan until there is a user or a measured failure on real data.
- **Committee explorer and weekly retention onto incremental tables:** the approach conflicts with the design. Re-scope it before starting.
- **Considered, not chosen,** so not re-proposed without new information: showing the original link's last status (36,137 documents' URLs last returned 404 or 410), showing saved-file size (3,042 over 50 MB), and witness links from House meeting XML.
- **Parquet variant for the folds:** revisit when all three hold: an iceberg-rust release writes variant through its Parquet writer (0.10.1, the pinned release, has none; 0.11 is expected to add it), Basin Catalog accepts format-version 3 tables, and DataFusion core or a maintained crate can query variant. The candidates are nested, mixed-type readings such as Congress.gov API JSON and MODS or meeting XML trees. House-naming metadata stays typed facets plus the fold regardless.
- **Full-text extraction of every PDF:** one later read of about 403 GB into `pdf_text` ([[DATA-MODEL]] §6.7). It gives page counts and text fingerprints for every PDF, which makes dedupe across sites cheap to revisit.

## 8. Keep List

These survive the switch unchanged:

- **Raw path:** create-only body and receipt writes, MD5-verified uploads; recovery `checked_put`; RecoveryGuard, the body-key shard check, recovery admission; `derive_body_key`, `physical_body_object_key` and their golden tests.
- **Site:** `cache.ts`, `withVerifiedJson`, `startup.ts`, and `--verify-publication`'s Chromium checks, retargeted to the contract test.
- **Engine:** `Strict<T>`, the remote scope boundary with create-only writes and the digest-verified delete actor, `BackendCapability`, `deny_unknown_fields`, ConnectedComponents, and export child tables.

## 9. Open Issue

**Only if needed:** if D1 or E4 finds facts that exist only in derived tables, the owner decides whether to record them as provenance first or accept losing them.

## 10. References

**[ARCHITECTURE]**
: *Congressional Document Archive: Architecture.* Editor's Draft, 2026-10-24. `docs/engine-first-architecture.md`.

**[DATA-MODEL]**
: *Congressional Document Archive: Data Model.* Editor's Draft, 2026-10-24. `docs/engine-first-data-model.md`.
