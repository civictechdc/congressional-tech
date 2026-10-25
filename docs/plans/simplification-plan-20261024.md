# Congressional Document Archive: Implementation Plan

**Note, 2026-10-24**

## Abstract

This Note describes how to move the current congressional-tech and docspec-rs code to the system specified in [[ARCHITECTURE]] and [[DATA-MODEL]]. It gives the strategy, the constraints, the order of work and its dependencies, and what is built, changed and deleted. It has no schedule and no effort estimates: the work runs in dependency order.

## Status of This Document

This is a Note, not a specification. It implements the two companion specifications and carries no normative requirements of its own. It cites their rules rather than restating them, and lists only the work. Comments should be directed to the editor.

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

**What survives** and is fixed now: fetchers and raw writers, recovery imports, the review forms (rebound to link keys), `house-naming`, the site, and docspec-rs. The code inventory (`docs/reviews/2026-10-24-design-review/package-inventory.md`) maps every package to keep, repurpose or replace, and lists the knowledge (K1–K34) the target must carry forward.

**What goes** at the switch, with no new work before then: the Python catalog (incremental and rebuild), the raw index and its routing, capture's replay mode, the viewer-publication journal route, the v6 preparer, and the shims around them.

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

1. Before and after each merge that touches raw writers, list `receipts/` and `bodies/` read-only. Every earlier key is still there with the same size and ETag; only additions are allowed. B0's one-time receipt cleanup is the single exception, and its verification records account for every change.
2. Every receipt-referenced body exists.
3. After the bucket lock: read the lock rules back after any infrastructure change.

**Other settled points:** no exclusion list will exist; wrong `stored_sha256` index rows are repaired in place; recovery imports refuse uncommitted code.

## 4. Order of Work

1. The writers' header, URL and path rules (the receipt part of B2), so no new receipt records a cookie, a credential or a local path; then the receipt cleanup (B0); then the bucket lock (owner). The cut-off re-fetch (B14) beside them.
2. The two measurements (M1, M2) and the semantic checkpoint (S).
3. The converted first release (F0) and the hand-built fixture; the first engine moves (C0); tracks A and B, with B13 after B1 and B3, and B10 after B13.
4. Track C.
5. Track D.
6. Track E, with E1 already written in S.
7. Track F.

| Track | What | Depends on |
|---|---|---|
| A | Site reader and canary | F0 and the hand-built fixture |
| B | Raw writers and protection | B2's receipt rules, then B0, then the bucket lock; the lock for B13 |
| C | Engine capabilities | M1, M2, S |
| D | Lake tables and backfills | C2, B2; B16 for D4 and D5 |
| E | Model SQL and parity | S, C1, C3, C4, D |
| F | Switch and delete | A, E, B13 |

A and B can run beside C. The widest uncertainty is E: it stays bounded unless parity finds facts that only derived tables hold (§9).

## 5. First Steps

### 5.1 M1: Basin Catalog Commits Under Maintenance (docspec-rs)

All three run on a scratch table with the table properties of [[DATA-MODEL]] §6.

1. **Conflict retry.** Plain appends already send their commit requirements. M1 tests what is new ([[ARCHITECTURE]] §8.1): an append that races a Basin compaction recomputes its work list and lands within three retries, and two ingest runs on the same receipts leave exactly one copy of each row.
2. **Manifest growth and expiration.** Append 400 day-sized batches (about 315 KB each) with Basin compaction and snapshot expiration enabled. Count data files and manifests in the current snapshot before and after maintenance runs, and confirm that expiration deletes the data files only expired snapshots referenced, and whether dropping a table purges its files (a new ingest mapping drops the old `captures` table).
3. **The engine's remote write caps.** Measure scan and commit cost with and without the engine's 2 MiB file and 2,048-row group caps. [[DATA-MODEL]] §6 assumes they go; if they measurably help, that section changes instead.

**Decides:** Iceberg stays (manifests bounded), or the lake tables move to dated Parquet with an `If-Match` manifest ([[ARCHITECTURE]] §8.7). The fallback changes the scope of C1, C2 and D.

### 5.2 M2: Wide Joins and Grouping in a Throwaway DataFusion Harness

The engine cannot run the full export until C1, C3 and C4 exist, so a short standalone DataFusion program measures first, using S's draft rules.

- Inputs: the pinned 2026-10-19 snapshot (captures `db033173…`, catalog generation `596f08fa…`), including today's filename readings and links parsed from a sample of pages.
- Run the model's joins, including `url_key`, link resolution and the link join (about 4.2M links, scaled from the sample, against 1.31M source URLs), filename readings, the folded `detail` and the 1.7M `occurrences`. Report every intermediate join's row count and bytes and every hash-join build's size, as well as time and peak memory. The links are sampled, so this tests mechanisms and memory; D2's full link backfill repeats the join on real data.
- Group the graph with the specified rule, using the sampled links; D2 repeats the grouping on real links. Record time, peak memory and the largest components.
- Run on `ubuntu-24.04` (4 vCPU, 16 GB), the smallest runner class.

**Decides:** the size of track C, and whether DataFusion handles the wide joins within the pool. The harness is deleted afterwards. Byte-for-byte determinism becomes C3's acceptance test.

### 5.3 S: The Semantic Checkpoint

E1 is written here, before track C, because M2 and the engine work depend on it:

- every derivation of [[DATA-MODEL]] §7 as SQL, and the reference model profile: every registry as a versioned file with its first contents and sample tests, seeded from the code inventory's carry-forward list (K1–K34), which names the file and line each entry comes from today;
- adversarial fixtures:
  - a PDF replaced while its XML stays, and historical pages linking both;
  - two mirrors that pair each of two editions with the same XML, and re-packaged copies of each edition paired with one XML;
  - several same-format files listed together, and unrelated files on one page outside any list item;
  - a recovery at an edition-ambiguous link; a recovery-only link that later downloads; a recovery import for a URL never fetched; two recoveries equal in kind, time and body;
  - one body under two filenames; a file named only by its download header; two archive members with one name and different bytes; an Office file that must stay whole; archive members, including a page whose relative links point at sibling members; a page with relative links saved in two directories; one page template under two hearings, where only hearing A's PDF and hearing B's XML were captured; a relative `<base href>`; a placeholder page at thousands of addresses; URLs written with raw spaces and with `%20`;
  - recovery decisions that match one import row twice;
  - an incrementally maintained lake and a clean rebuild after a registry change, which must group identically;
  - two merged documents with different title overrides; two active merges on one document; a reviewer's hide and its withdrawal;
- a hand-labeled stratified sample of a few hundred files, starting from the 29 saved responses already labeled by hand (inventory K16), covering short real pages, challenge and soft-error pages, archive members, landing pages, listing pages, files listed together on one page and widely mirrored real documents. It measures how often the file-shape, error-sign, listing-page, placeholder and rendition rules wrongly include, exclude or join a file, and sets the listing thresholds and the final file-shape list. It includes a listing page captured in two places and pages whose links sit outside any list item. The labeling rubric: a file is a real document when its main content is the document itself (testimony, a report, a transcript, a bill, a hearing record), not a list of links to documents, a landing or error page, or metadata about a document. Two files are one document when they hold the same content: identical bytes, the same text at one address, or one text in different formats;
- a check that every rule can be computed from raw, with nothing borrowed from the old derived tables.

### 5.4 F0: The First Release, Converted From the Pinned Catalog

- Convert the pinned catalog pair into the release format ([[DATA-MODEL]] §8.1) with the final writer settings: offset indexes and page row limits, the folded `detail`, `links` keyed by body prefixes, `recoveries` as its own file. Use the engine's RunSpec where it can. Existing measurement scripts show the shape: `measurements/build_list.py` built `list`, `ids` and `detail` in 24 s, and `size_occ_captures.py` built `occurrences`.
- This release is the reader's fixture (track A). Its manifest records that it came from the pinned catalog. It does not go live: the explorer waits for the engine-built release.
- **It fills what it can:** meeting keys from URLs, document dates from the old metadata, link labels from the old occurrences, and committee names from today's committee file. It keeps all 1.24M of today's catalog rows, so it is about twice the target `list`.
- **It cannot show** format groups, meeting titles or the new recovery kinds, so a small hand-built fixture release covers them: one document with PDF and XML alternates, one titled hearing in `meetings`, one of each recovery kind and one hidden document. The contract test runs both.
- **It assumes nothing unique about old bodies:** 141,762 body keys appear in several old documents, so F0 resolves each link key to the first document in list order.
- The converter is a migration tool, deleted at the switch.

## 6. Tracks

### 6.1 Track A: Site Reader and Canary

1. **A reader module for the release format** ([[ARCHITECTURE]] §11): pointer → manifest → `list` in a Web Worker, decoded column by column; `detail` by row with hyparquet's `useOffsetIndex`, each row group's offset index fetched once per session and cached; `links` with `usePageIndex`; the `occurrences` and `recoveries` ranges; `meetings`; shards. No DOM dependency. Accepts the current and previous `schema_version`. On a 404 for a release file, it re-reads the pointer and reloads.
2. **Links** carry a 16-hex link key and resolve through `links` to whichever document holds that file now; a key that no longer resolves opens a not-found notice.
3. **The Node canary** ([[ARCHITECTURE]] §10.3.5), run by the publish job against the uploaded candidate, with a heap budget for a mid-range phone and the 404 reload.
4. **A CI contract test:** the real site in a headless browser against F0 and the hand-built fixture, within the heap budget. It moves to a release built from a fixed sample of real receipts once track E exists.
5. **Saved copies** ([[ARCHITECTURE]] §11.5): open the saved file at its physical key, with alternates; unpack other `.gz` bodies with `DecompressionStream`; offer the 579 over 100 MB as a labeled compressed download.
6. **Dates:** the document date and capture date in list rows, so same-filename editions read apart; on the document page, the document date with its source and the first and last capture dates, with the labels of [[ARCHITECTURE]] §11.6.
7. **Recoveries:** each on the page the attachment rule gives it, labeled by kind, with its recovered URL, match basis, evidence digest and identity note, and a link to the recovered file.
8. **Link context:** "where each copy was seen" names the page that linked it and the link's label.
9. **Meetings and record links:** filter and sort by document date; list every document for a hearing under its title, date, type and committee; link out to the GPO record, the bill and the member.
10. **Removed by review:** a hidden document's link opens a note with the reason and date.
11. **Speed, measured then fixed:** measure startup, search, detail and heap on real phones and desktops with F0, then write those targets into the canary and contract test. F0's size makes these targets conservative; re-measure on the first engine-built release.

**Done when:** the site loads F0 locally on desktop and in a phone-sized profile, and the canary passes against F0 in under a minute.

**Replaces at the switch:** `catalog-v6.ts` and its v6 and ExportPin branches, the v6 paths in `worker.ts`, and `verify-live-publication.mjs`. `cache.ts`, `withVerifiedJson` and `startup.ts` stay where they fit.

### 6.2 Track B: Raw Writers and Protection

This code survives, so it is fixed now.

0. **Clean the older receipts, once, before the lock** ([[ARCHITECTURE]] §7.2). A sample of 150 of today's receipt files held 33,585 recorded cookies and 24,375 local file paths in 74,863 lines, and receipts are public. It runs after B2's receipt rules, so no new receipt adds more.
   - **The rule:** remove recorded `Set-Cookie`, `Cookie` and `Authorization` values, and replace every absolute local path with its last segment. Nothing else changes: keys, line order, every other field and every body.
   - **The run:** for each receipt, write the cleaned bytes to the same key with `If-Match` on the original ETag and `Content-MD5`; then re-read it, check that every line equals the original minus exactly those fields, and write a verification record (original and cleaned size and ETag, counts removed).
   - **The safety net:** keep the private 2026-10-24 backup until every receipt is verified, then clean the backup the same way.
   - **Done when:** every receipt under `receipts/` has a verification record and a re-scan finds no cookie or local path. Only then does the lock go on (B1).
1. **Bucket lock** (owner) on `bodies/`, `receipts/` and `provenance/`, after B0. The single most protective step; it gates B13.
2. **Writers to [[ARCHITECTURE]] §7.1–7.2 and the receipt fields of [[DATA-MODEL]] §5.2.** What changes from today:
   - **Receipt lines record:** the sniffed format and sniff version, the stored suffix, the entry index for archive members, and on `stored` lines the stored MD5 and size.
   - **Headers:** only the allowlisted ones, with `Content-Disposition` and `Retry-After` added and cookies never.
   - **Recorded URLs:** credential parameters stripped (API keys go in a header), and no local paths.
   - **Bodies:** new compressible bodies are stored with `Content-Encoding: gzip`; a body is hashed after its transfer encoding is removed; one create-only PUT per body with Content-MD5, never multipart, after the older-copy check; a 412 is `unchanged` with no HEAD.
   - **Fetching:**
     - the fetcher spools bodies and never cuts one off (lift today's 64 MiB cap), and treats a 206 or `Content-Range` response as incomplete;
     - it keeps its scope, redirect, pacing and fallback rules (inventory K2–K7);
     - archives expand as A §7.2 says.
   - **Keys and dropped fields:** receipt keys use the UTC write date; lines drop `links`, the provider metadata, duplicated headers and the old raw-index row.
3. **One namespace policy for raw keys.** Write the refusal matrix first: every writer (`R2Store.put`, `put_file`, `put_pdf_body`, `AsyncBodies.put`, `LocalStore.put`) refuses a write that is not create-only under `bodies/`, `receipts/` or `provenance/`, and any receipt line with a credential parameter in a recorded URL, before any I/O. Then delete the `immutable` flag.
4. **Ingest policy set once,** where capture builds its store. Delete the exclusion gate (`raw_storage.py:75-236`, 162 lines).
5. **Body existence by key:** the in-run set, the older-copy check on `<sha>.gz`, then a create-only PUT and its 412. No index lookup.
6. **One body layout.** The hand-written layout writers call `put_body`: `committee_explorer/parquet.py:406-428`, senate `seed_fetch`, and the e2e harness.
7. **Code identity for recovery imports:** the git tree hash plus the `uv.lock` digest, refusing uncommitted changes under `packages/` or `scripts/`.
8. **Reconcile `accepted.json` with the receipts,** so recoveries become provenance records the model reads.
9. **The weekly maintenance job** ([[ARCHITECTURE]] §7.4, §10.3.7), in publish's CI concurrency group: the LIST joined to recorded keys and verification records, a one-time re-hash of any body with no creating line, the 25-body sample, the orphan report and release retention. It joins to the old capture index until D1 exists.
10. **The one-time full re-hash** of bodies written before receipts carried an MD5 (after B13), skipping the keys B13 verified.
11. **A ratchet test:** `PYTEST_CURRENT_TEST` may not appear in surviving packages, and neither may test-only input substitution such as `source_capture_inputs.py:61-74`. Delete the raw-adjacent substitution in `raw_storage.py:655-672` now; the other sites (75 in all) go with the old layers.
12. **Owed while the old capture path runs:** repair wrong `stored_sha256` index rows in place, and confirm the daily capture writes correct values. The target reads receipts, so these matter only until the switch.
13. **Uncompressed copies of older gzip PDFs** (after B1 and B3). The largest raw write in the plan, so the lock and the refusal matrix come first. First fold `migrate_pdf_bodies_to_uncompressed` into `backfill_uncompressed_pdfs` (`pdf_backfill.py`), so one path remains, and change it to take its candidates from capture rows rather than `accepted.json`, lift its 512 MiB cap (the largest body is 1.19 GB), and drop the HEAD it makes before every upload. Then run it over every older gzip PDF: create-only to `bodies/sha256/<aa>/<sha>.pdf`, with Content-MD5 and the decompressed SHA-256 checked before upload, writing a verification record for both the `.gz` source and the `.pdf` copy. About 261,055 uploads and 403 GB once decompressed (about $72 a year of storage under the lock). Copies that already exist return 412 and get their record. Running it before B10 saves B10 about 365 GB of reads.
14. **Re-fetch the cut-off files** (first, in today's capture path): every URL with a copy cut off at 64 MiB and no complete 2xx copy, 64 by the snapshot index, confirmed against the receipts. First fix the `streamed-recovery` call, which raises `TypeError` today (`cli/raw_sync.py:469`). The cut-off copies stay in raw.
15. **The 2026-10-15 recovery run needs no correction.** All 5,587 lines of `receipts/documents/2026-10-15/download-filename-recovery-all-*` are `retained_import` recoveries with a synthetic HTTP 200 (5,154 recovered copies, 341 hearing-record excerpts, 92 official substitutes). The old capture index had flattened them into fetches. What remains is in D1 and E1.
16. **Committee and meeting fetches through the raw writer:** `acquisition/committees.py` and `acquisition/meetings.py` stop writing their own output files and fetch through the raw writer like every other fetch. The API key moves to a request header, so it never reaches a recorded URL. Their Congress.gov and House meeting-XML rules carry over (inventory K11, K12).

**Done when:** every older receipt is cleaned and verified, the refusal matrix passes, the lock is on, one capture run's `stored` lines carry MD5s that match the stored ETags and every line carries its stored suffix, every older gzip PDF has a recorded copy, and every cut-off URL has a complete copy or a recorded reason.

### 6.3 Track C: Engine Capabilities (docspec-rs)

**C0, first moves on engine main** (beside M1): revert the deferred-commit mode and delete the dataset-name predicates; both came after congressional-tech's pin, so nothing depends on them. Hash while writing, and stop HEADing and re-downloading immutable files (also C5). Write the table properties of [[DATA-MODEL]] §6, and stop resetting `gc.enabled = false` on every commit (`src/catalog.rs:1163`). Remove the remote write caps unless M1 keeps them. Record the engine binary's digest for every runner OS, Linux included, in congressional-tech, and check against it rather than against the binary's own descriptor.

**Then the capabilities of [[ARCHITECTURE]] §13:**

| # | Capability | Evidence |
|---|---|---|
| C1 | Multi-input SQL plans over Basin tables and Parquet files in one context | A plan joining two tables and a file |
| C2 | Append through the REST catalog, with the conflict retry | M1's two tests |
| C3 | Deterministic multi-file export with the per-file writer settings of [[DATA-MODEL]] §8.1 | Byte equality across threads, input orders, batch sizes and a forced spill; hyparquet page reads on the output |
| C4 | ConnectedComponents in memory over 32-bit IDs, refusing above a node cap | M2's graph; a refusal test |
| C5 | Streaming I/O: no re-read or HEAD of immutable files beyond the two allowed | Request counts in a test |
| C6 | Bounded threads, memory pool and scratch; wide columns kept off hash-join build sides | A join at the pool limit fails clearly; M2's build sizes |
| C7 | A CLI that runs a declarative job spec and returns a machine-readable result | The M2 export as a job spec |
| C8 | Generic URL functions: RFC 3986 reference resolution and percent-encoding normalization, built on the `url` and `percent-encoding` crates already in the engine's lockfile | Conformance vectors from RFC 3986 §5.4, and golden vectors from today's fetcher's `http_url` (`document_links.py:66-95`); M2's `url_key` timing |

The engine's current export disables the offset index unless page-index columns are named (`export/pipeline.rs:687-697`), so C3's per-file settings are required, not optional.

**Not needed any more:** the lifecycle store's commit requirements, lifecycle-store compaction on R2, copy-on-write measurement and insert-if-absent. The target has no engine lifecycle store, no updates and no news_lake work. Close them unless another consumer needs them.

**Done when:** one CLI job runs the full export from Basin tables, byte-identical across threads, input orders and batch sizes and with a forced spill, on the smallest runner.

### 6.4 Track D: Lake Tables and Backfills

Each table is built to [[ARCHITECTURE]] §8 and [[DATA-MODEL]] §6.

1. **`captures`:**
   - ingest from date-shaped prefixes only, per family, from the newest ingested date;
   - backfill from all 2,289 receipts (1.08 GB compressed), including the non-date segments (`undated/`, `mixed-dates/`: 49 files, 2.2M rows); older receipt shapes are mapped in the ingest SQL, with a test sample of each shape, and every older row gets `stored_suffix = '.gz'`;
   - the backfill restores the statuses today's index dropped for 1.04M bodiless lines, and checks whether the undated receipts' JSON carries times the old index dropped (2.7M capture rows have none today);
   - the rebuild-equivalence test;
   - **compare with the pinned old capture index** (3,909,134 rows) on receipt-derived columns, with written transformation rules for the expected differences: statuses restored on bodiless lines, `stored_md5` and `stored_suffix` new, `stored_sha256` gone. A row that exists only in the old index is a fact raw does not hold, and it blocks the switch until the owner decides (§9).
2. **`readings`:**
   - first `sniff` over every older body: about 1.04M ranged GETs, timed in the run. The real-file rule needs a format for every body;
   - then HTML, XML and JSON (about 5 GB; 287,765 bodies the server labels HTML or XML), including each page's links as written, with their `group_path`, and the table's size with links measured; then M2's link join and grouping are repeated on these real links. There is no PDF parser for now;
   - then `fingerprint` for the candidates: about 300 bodies (1.4 GB) at contested endpoints, plus every rendition-group member (*est.* 20–45 GB of reads, mostly PDF text; measured in the run);
   - the parser functions survive; the adoption machinery around them goes in F3.
3. **`filename_readings`:** a producer that runs `house-naming` over its work list and appends through the engine. Backfill is 7–18 minutes over 1.39M pairs.
4. **`committee_records`** (needs B16): the JSON parser, once per response and version.
5. **`meeting_records`** (needs B16): the JSON and XML parsers, once per response and version.
6. Enable Basin compaction and snapshot expiration on all five tables.

**Done when:** all five tables exist with complete backfills at the pinned versions, and both `captures` comparisons pass.

### 6.5 Track E: Model SQL and Parity

1. **The rules, written in S** (§5.3). The file-shape list starts from the broader list (44,047 file-shaped bodies); the roughly 27k bodies between it and the narrow list (16,775) are sampled before it is fixed.
2. **The model SQL:** every relation and release file of [[DATA-MODEL]] §7–8, with the invariants of §10 as its test suite.
3. **Golden vectors** for `source_id` and `document_id`, generated from Python `source_identity` and `compute_document_id` (`retention/index/bipartite.py:165,197`) with their compact-JSON serialization, and checked in the engine's tests.
4. **Parity against the pinned catalog pair** (not F0, which picks one document per shared body), on browser-visible fields, compared many-to-many and keyed by source evidence: the files and URLs each document holds. Expected, explained changes:
   - about 560k catalog rows leave the list (captions, metadata records, playlists, API responses), and listing pages leave it too;
   - about 30k documents lose error pages from their body sets, and about 4,900 lose Senate landing pages;
   - cut-off copies and recovery imports drop out of body sets, and so do pages whose reading failed (reported by format and error type), while real web pages now count in body sets;
   - each file has one name, so the files today's catalog lists under several names (about 95,000 carry a download-header name) collapse to one, with different `source_id`s;
   - about 16k format groups merge (32,547 documents today);
   - link-label coverage changes, because labels now come from saved pages; labels that came only from scraper records inside receipts are their own cause;
   - capture dates change where receipts lack times.
   - **The comparison reports by cause, not by document:** each known cause has a checkable predicate, its count and a few reviewed examples, and every difference that fits no known cause is listed separately. Only that last group needs reading one by one.
   - Classify each unexplained difference: a rule change (fine, recorded with the rule); an old-pipeline error (the new model wins); or a fact that exists only in derived tables (a blocker, §9).

**Done when:** every known cause has its predicate, count and examples, every unexplained difference is classified with no blocker left, and the model runs as a CLI job on the smallest runner.

A full Python rebuild of the old catalog is not needed: the pinned catalog pair is the oracle.

### 6.6 Track F: Switch and Delete

1. **Workflows** ([[ARCHITECTURE]] §12): the capture job; the publish job; the weekly maintenance job in publish's CI concurrency group. Delete the disabled viewer workflow and its 30-minute cron.
2. **Capture reads `url_state` from the live release,** including its queue of linked-but-unfetched URLs, stops reading the raw index, and drops its replay mode (`acquisition/raw_sync.py:298`).
3. **Delete the old layers,** one PR per group, measured again at cut. The counts are the code inventory's `wc -l` at d9730967:

| Group | Source + tests |
|---|---|
| Python incremental catalog: 23 modules including `native_features.py`, the `catalog/` facade, `incremental_boundary_proof.py` | 10,336 + about 9,000 (tests shared with the next row) |
| Python rebuild path, its rules lifted into the model SQL first: `catalog_staging`, `catalog_publication`, `catalog_cache`, `catalog_validation`, `index/*`, the oracle files | 6,726 + about 11,000 shared |
| Raw index: `partition_routing`, `raw_state_routes`, `raw_changes`, the Python merge (also `docspec_client/specs.py:476-692`), the `raw.json` schema backfills, the retention planner (147); `LocalStore` stays | about 4,670 + 2,663 |
| Viewer publication: the journal, resume and attempt route, with its preflight, helpers and custody helpers, and their 233-line workflow | 3,417 + 4,066 |
| Viewer publication: the v6 preparer, the local viewer and the v6 reader branch | 5,458 + 3,622 |
| `docspec_client`'s archive-only lines (news_lake and the committee explorer keep the rest) | about 530 |
| The review tools' catalog binding (the 13 review forms survive as provenance verdicts) | 916 + 644 |
| corpus_recovery's coupling to the old catalog | about 1,280 + 1,586 |
| CLI catalog modes, `replay/`, `recovery_queue`, `retained_import`, the ExportPin route, the dormant compaction scripts and `verify-capture-run.py` | at cut |
| `tests/e2e` | 8,403 |
| Measurement scripts for deleted subjects (427 + 192 stay for the speed targets) | 2,725 + 531 |
| The F0 converter and the one-off PDF copy job (after B13) | at cut |
| The firewall path allowlist inside `r2_edge_rules.py` and `apply_r2_edge_rules.py`; the files stay for CORS, cache headers, CSP and the `?filename=` rule | about 150 + 60 |
| docspec-rs: unused routes, lifecycle families, the Dagster adapter, provider suites, `cli_args.rs`, hand-written SHA-256, date transforms, legacy formats | about 19,727; about 20,855 more in families not listed here (backfill, retirement, restore, succession) |

Shims and legacy formats sit inside the rows above. 27 test files (5,948 lines) mix old and surviving subjects and are split, not deleted. The engine cuts apply only to code no consumer uses after the switch; check `spicysearch`, `spicyengine` and `DocSpec` as well as congressional-tech. About half of them wait while news_lake uses the engine's lifecycle store. The independent ones (`sha2`, date transforms, `cli_args.rs`, the Dagster adapter) can land any time.

**Done when** the switch checklist holds:
- the explorer serves an engine-built release, and the reader opens saved files, alternates and recoveries from it;
- every older gzip PDF's copy is recorded (B13);
- the canary and contract test pass the speed targets set on real devices, against that release;
- a failed canary is shown to leave the previous release live;
- capture runs from `url_state` with no raw-index read;
- the old workflows are gone, and the deleted line counts are recorded.

## 7. Parked

- **news_lake** keeps the DocSpec backend. No work until it adopts the three layers.
- **The freeze:** no browser or engine performance work beyond this plan until there is a user or a measured failure on real data.
- **Committee explorer and weekly retention onto incremental tables:** the approach conflicts with the design. Re-scope it before starting.
- **Considered, not chosen,** so not re-proposed without new information: showing the original link's last status (36,137 documents' URLs last returned 404 or 410), showing saved-file size (3,042 over 50 MB), and witness links from House meeting XML.
- **Parquet variant for the folds:** revisit when all three hold: an iceberg-rust release writes variant through its Parquet writer (0.10.1, the pinned release, has none; 0.11 is expected to add it), Basin Catalog accepts format-version 3 tables, and DataFusion core or a maintained crate can query variant. The candidates are nested, mixed-type readings such as Congress.gov API JSON and MODS or meeting XML trees. House-naming metadata stays typed facets plus the fold regardless.
- **Full-text extraction of every PDF:** one later read of about 403 GB into `pdf_text` ([[DATA-MODEL]] §6.6). It gives page counts and text fingerprints for every PDF, which makes dedupe across sites cheap to revisit.

## 8. Keep List

These survive the switch unchanged:

- **Raw path:** create-only body and receipt writes, MD5-verified uploads; RecoveryGuard, the body-key shard check; `derive_body_key` and its golden tests. Three survive with a change: `physical_body_object_key` reads the recorded suffix instead of guessing `.pdf` from the format, and recovery `checked_put` and recovery admission write receipts and provenance (B8).
- **Site:** `cache.ts`, `withVerifiedJson`, `startup.ts`, and `--verify-publication`'s Chromium checks, retargeted to the contract test.
- **Engine:** `Strict<T>`, the remote scope boundary with create-only writes and the digest-verified delete actor, `BackendCapability`, `deny_unknown_fields`, ConnectedComponents, and export child tables.

## 9. Open Issue

**Only if needed:** if D1 or E4 finds facts that exist only in derived tables, including link labels found only in scraper records inside receipts, the owner decides whether to record them as provenance first or accept losing them.

## 10. References

**[ARCHITECTURE]**
: *Congressional Document Archive: Architecture.* Editor's Draft, 2026-10-24. `docs/engine-first-architecture.md`.

**[DATA-MODEL]**
: *Congressional Document Archive: Data Model.* Editor's Draft, 2026-10-24. `docs/engine-first-data-model.md`.
