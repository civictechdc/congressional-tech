# Congressional Document Archive: Implementation Plan

**Note, 2026-10-24**

## Abstract

This Note orders the work that builds the system specified in [[ARCHITECTURE]] and [[DATA-MODEL]] from today's congressional-tech and docspec-rs code. Work is organized by the target's components and their contracts. Which existing code stands behind each component, and what it must change to get there, is in [[BINDINGS]]. The plan has no schedule and no effort estimates: the work runs in dependency order.

## Status of This Document

This is a Note, not a specification. It carries no normative requirements of its own. It cites the specifications' contracts rather than restating them, and it names no existing files: those belong to [[BINDINGS]]. Comments should be directed to the editor.

## Table of Contents

1. [Introduction](#1-introduction)
2. [Strategy](#2-strategy)
3. [Constraints and Rules](#3-constraints-and-rules)
4. [Order of Work](#4-order-of-work)
5. [First Steps](#5-first-steps)
6. [Tracks](#6-tracks)
7. [Parked](#7-parked)
8. [Open Issue](#8-open-issue)
9. [References](#9-references)

## 1. Introduction

The raw log already exists: bodies, receipts and provenance in the R2 bucket `congressional-tech-raw`, backed up on 2026-10-24. Its bodies are preserved unchanged and keep their stored form; older gzip PDFs gain uncompressed copies; older receipts are cleaned once of cookies and local paths. Everything above raw is rebuilt.

Already in place: the hosted setup refuses an engine revision other than the qualified one; the capture schema carries `stored_sha256` from the receipt and never derives it; the gzip-deleting path is gone; and the 12,431 recoveries that existed only in `accepted.json` have a write-once backup under `provenance/recoveries/`. The bucket lock is pending with the owner.

## 2. Strategy

**Contracts first.** Every component in [[ARCHITECTURE]] §6 has a contract in the specifications. Its contract test suite is written from that contract before any code is bound to it, and any implementation that passes the suite may stand behind the component (principle 8).

**Bind, adapt or build.** For each component, [[BINDINGS]] records the existing code that implements it, the adapter work that closes the gap to the contract, or that it is built new. Existing code is lifted, not rewritten, where it already meets the contract; hard-won behavior in it becomes registry seeds and fixtures rather than code paths.

**One implementation per component.** Where today has several implementations of one component, the binding picks one and the rest are deleted. External systems are the only variation, and they are injected adapters: the object store and local disk, the direct and provider transports, the catalog.

**Switch, then delete.** The target components are built beside the old pipeline. At the switch the publish path binds to them; the old layers are then bound to nothing and are deleted whole, as [[BINDINGS]] §5 lists them. Until the switch, the old capture job keeps writing raw data and reading the raw index, and gets raw-safety fixes only; its whole-leaf index rewrites continue until then, which is accepted.

## 3. Constraints and Rules

**What must survive:** objects in `congressional-tech-raw` under `bodies/`, `receipts/` and `provenance/`. Everything else can be rebuilt, and nothing uses it yet.

**Rules for every step**

- One conceptual move per PR. Contract tests land before the code bound to them moves. Behavior changes go in their own PRs.
- Run checks only through the project runners: `.venv/bin/python scripts/dev.py test <lane>` in congressional-tech and `scripts/check` in docspec-rs. Never use a tool from `PATH`. Say this in every agent and reviewer brief.
- Work in a separate worktree and venv. The primary checkout backs live recovery jobs.
- Report before and after `wc -l` in every PR that deletes code.
- Each step names its evidence: a contract test, or a measurement committed under `docs/`, never in the gitignored `output/`.
- Create the ticket before the first code commit. An epic closes only after its children. Acceptance criteria name an observable behavior and the test or measurement that shows it. Performance work records a baseline on real data and the decision rule first. A deletion closes only when the old path is gone.

**Raw check (R-check)**

1. Before and after each merge that touches a raw-writer component, list `receipts/` and `bodies/` read-only. Every earlier key is still there with the same size and ETag; only additions are allowed. B0's one-time receipt cleanup is the single exception, and its verification records account for every change.
2. Every receipt-referenced body exists.
3. After the bucket lock: read the lock rules back after any infrastructure change.

**Other settled points:** no exclusion list will exist; wrong `stored_sha256` index rows are repaired in place; recovery imports refuse uncommitted code.

## 4. Order of Work

1. The bucket lock on `bodies/` and `provenance/` (owner, B1), at once. Then the receipt writer's header, URL and path rules (the receipt part of B2), so no new receipt records a cookie, a credential or a local path; then the receipt cleanup (B0); then the lock on `receipts/`. The cut-off re-fetch (B14) beside them.
2. The two measurements (M1, M2) and the semantic checkpoint (S).
3. The converted first release (F0) and the hand-built fixture; the first engine moves (C0); tracks A and B, with B13 after B1 and B3, and B10 after B13.
4. Track C.
5. Track D.
6. Track E, with E1 already written in S.
7. Track F.

| Track | Components | Depends on |
|---|---|---|
| A | Reader, canary and contract test, site | F0 and the hand-built fixture |
| B | Raw-writer components | The lock on `bodies/` and `provenance/` first; B2's receipt rules, then B0, then the lock on `receipts/` |
| C | Engine | M1, M2, S |
| D | Lake producers | C2, B2; B16 for D4 and D5 |
| E | Model | S, C1, C3, C4, D |
| F | Publish job, capture scheduler, switch | A, E, B13 |

A and B can run beside C. The widest uncertainty is E: it stays bounded unless parity finds facts that only derived tables hold (§8).

## 5. First Steps

### 5.1 M1: Basin Catalog Commits Under Maintenance

All three run on a scratch table with the table properties of [[DATA-MODEL]] §6.

1. **Conflict retry.** Plain appends already send their commit requirements. M1 tests what is new ([[ARCHITECTURE]] §8.1): an append that races a Basin compaction recomputes its work list and lands within three retries, and two ingest runs on the same receipts leave exactly one copy of each row.
2. **Manifest growth and expiration.** Append 400 day-sized batches (about 315 KB each) with Basin compaction and snapshot expiration enabled. Count data files and manifests in the current snapshot before and after maintenance runs, confirm that expiration deletes the data files only expired snapshots referenced, and find out whether dropping a table purges its files (a new ingest mapping drops the old `captures` table).
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

- every derivation of [[DATA-MODEL]] §7 as SQL, and the reference model profile: every registry as a versioned file with its first contents and sample tests, seeded as [[BINDINGS]] §4 lists;
- adversarial fixtures:
  - a PDF replaced while its XML stays, and historical pages linking both;
  - two mirrors that pair each of two editions with the same XML, and re-packaged copies of each edition paired with one XML;
  - several same-format files listed together, and unrelated files on one page outside any list item;
  - a recovery at an edition-ambiguous link; a recovery-only link that later downloads; a recovery import for a URL never fetched; two recoveries equal in kind, time and body; recovery decisions that match one import row twice;
  - one body under two filenames; a file named only by its download header; two archive members with one name and different bytes; an Office file that must stay whole; a page whose relative links point at sibling archive members;
  - a page with relative links saved in two directories; one page template under two hearings, where only hearing A's PDF and hearing B's XML were captured; a relative `<base href>`; a placeholder page at thousands of addresses; URLs written with raw spaces and with `%20`;
  - an incrementally maintained lake and a clean rebuild after a registry change, which must group identically;
  - a ZIP repacked so that `report.pdf` moves to another position, with mirrors pairing each edition with the same XML; two members with one name and different bytes;
  - a broken PDF, and a valid PDF with trailing bytes after its end marker; a committee-removed document; a `Retry-After` beyond the next run; a body assembled from ranges; files whose kind only the publisher's label gives; a meeting named only by a GovInfo MODS record;
  - two merged documents with different title overrides; two active merges on one document; a reviewer's hide and its withdrawal;
- a hand-labeled stratified sample of a few hundred files, starting from the responses already labeled by hand ([[BINDINGS]] §4), covering short real pages, challenge and soft-error pages, archive members, landing pages, listing pages, files listed together on one page and widely mirrored real documents. It measures how often the file-shape, error-sign, listing-page, placeholder and rendition rules wrongly include, exclude or join a file, and sets the listing thresholds and the final file-shape list. It includes a listing page captured in two places and pages whose links sit outside any list item. The labeling rubric: a file is a real document when its main content is the document itself (testimony, a report, a transcript, a bill, a hearing record), not a list of links to documents, a landing or error page, or metadata about a document. Two files are one document when they hold the same content: identical bytes, the same text at one address, or one text in different formats;
- a count of contested editions whose re-packaged copies sit in format groups without ever sharing an address. If the count matters, widen the fingerprint candidates to every rendition-group member (*est.* 8–45 GB of reads once); otherwise the narrow guard stands;
- a check that every rule can be computed from raw, with nothing borrowed from the old derived tables.

### 5.4 F0: The First Release, Converted From the Pinned Catalog

- A converter writes the pinned catalog pair in the release format ([[DATA-MODEL]] §8.1) with the final writer settings: offset indexes and page limits, the folded `detail`, `links` keyed by body prefixes, `recoveries` as its own file. It uses the engine's RunSpec where it can.
- This release is the reader's fixture (track A). Its manifest records that it came from the pinned catalog. It does not go live: the explorer waits for the engine-built release.
- **It fills what it can:** meeting keys from URLs, document dates from the old metadata, link labels from the old occurrences, and committee names from today's committee file. It keeps all 1.24M of today's catalog rows, so it is about twice the target `list`.
- **It cannot show** format groups, meeting titles or the new recovery kinds, so a small hand-built fixture release covers them: one document with PDF and XML alternates, one titled hearing in `meetings`, one of each recovery kind and one hidden document. The contract test runs both.
- **It assumes nothing unique about old bodies:** 141,762 body keys appear in several old documents, so F0 resolves each link key to the first document in list order.
- The converter is a migration tool, deleted at the switch.

## 6. Tracks

Each task names the component it builds or binds and the contract it must pass. [[BINDINGS]] §3 says which existing code is bound to each component and what changes.

### 6.1 Track A: Reader, Canary and Site

1. **Reader** ([[ARCHITECTURE]] §11): pointer → manifest → `list` in a Web Worker, decoded column by column; `detail` by row with hyparquet's `useOffsetIndex`, each row group's offset index fetched once per session and cached; `links` with `usePageIndex`; the `occurrences` and `recoveries` ranges; `meetings`; shards. No DOM dependency. Accepts the current and previous `schema_version`. On a 404 for a release file, it re-reads the pointer and reloads.
2. **Links** carry a 16-hex link key and resolve through `links` to whichever document holds that file now; a key that no longer resolves opens a not-found notice.
3. **Canary** ([[ARCHITECTURE]] §10.3.5), run by the publish job against the uploaded candidate, with a heap budget for a mid-range phone and the 404 reload.
4. **Contract test:** the real site in a headless browser against F0 and the hand-built fixture, within the heap budget. It moves to a release built from a fixed sample of real receipts once track E exists.
5. **Saved copies** ([[ARCHITECTURE]] §11.5): open the saved file at its physical key, with alternates; unpack other `.gz` bodies with `DecompressionStream`; offer the 579 over 100 MB as a labeled compressed download.
6. **Dates:** the document date and capture date in list rows, so same-filename editions read apart; on the document page, the document date with its source and the first and last capture dates, with the labels of [[ARCHITECTURE]] §11.6.
7. **Recoveries:** each on the page the attachment rule gives it, labeled by kind, with its recovered URL, match basis, evidence digest and identity note, and a link to the recovered file.
8. **Link context:** "where each copy was seen" names the page that linked it and the link's label.
9. **Meetings and record links:** filter and sort by document date; list every document for a hearing under its title, date, type and committee; link out to the GPO record, the bill and the member.
10. **Removed by review:** a hidden document's link opens a note with the reason and date.
11. **Speed, measured then fixed:** measure startup, search, detail and heap on real phones and desktops with F0, then write those targets into the canary and contract test. F0's size makes these targets conservative; re-measure on the first engine-built release.

**Done when:** the site loads F0 locally on desktop and in a phone-sized profile, and the canary passes against F0 in under a minute.

### 6.2 Track B: Raw-Writer Components

These components survive, so they are bound now.

0. **Clean the older receipts, once, before `receipts/` is locked** ([[DATA-MODEL]] §5.2). A sample of 150 of today's receipt files held 33,585 recorded cookies and 24,375 local file paths in 74,863 lines, and receipts are public. It runs after B2's receipt rules, so no new receipt adds more.
   - **The rule** is the one [[DATA-MODEL]] §5.2 states: cookie and authorization headers removed, absolute local paths cut to their last segment, credential parameters removed from recorded URLs; member paths, JSON pointers and URLs otherwise untouched. The path recognizer is a short prefix list with samples, checked against the 150-file sample before the run.
   - **The tool** is a one-off rewriter outside the body store, with its own credential, deleted once B0 is verified. The body store stays create-only throughout.
   - **The run:** for each receipt without a verification record, write the cleaned bytes to the same key with `If-Match` on the original ETag and `Content-MD5`; re-read it; check that every line equals the original minus exactly those fields; and record the result (original and cleaned size and ETag, counts removed) in a few batched verification files. A rerun skips receipts already recorded, and after a crash it verifies against the backup's original.
   - **The safety net:** the private 2026-10-24 backup keeps the originals, untouched.
   - **Done when:** every receipt under `receipts/` has a verification record and a re-scan finds no cookie, local path or credential parameter. Only then is `receipts/` locked.
1. **Bucket lock** (owner), per prefix: `bodies/` and `provenance/` at once, `receipts/` after B0. Creates stay allowed under it, so B13 is unaffected. The single most protective step.
2. **Fetcher and receipt writer** to [[ARCHITECTURE]] §7.1–7.2 and [[DATA-MODEL]] §5.2:
   - **Receipt lines record:** the sniffed format and sniff version, the stored suffix, the entry index for archive members, and on `stored` lines the stored MD5 and size.
   - **Headers:** only the allowlisted ones, with `Content-Disposition` and `Retry-After` included and cookies never.
   - **Recorded URLs:** credential parameters stripped (API keys go in a request header), and no local paths.
   - **Bodies:** compressible bodies are stored with `Content-Encoding: gzip`; a body is hashed after its transfer encoding is removed; one create-only PUT per body with Content-MD5, never multipart, after the older-copy check; a 412 is `unchanged` with no HEAD.
   - **Fetching:** the fetcher spools bodies and never cuts one off, and treats a 206 or `Content-Range` response as incomplete. Its scope, redirect, pacing and fallback rules come from the capture-scope and host-pacing registries, and the archive expander follows [[ARCHITECTURE]] §7.2.
   - **Keys and dropped fields:** receipt keys use the UTC write date; lines drop `links`, the provider metadata, duplicated headers and the old raw-index row.
3. **One body store.** Write the refusal matrix first, as the body store's contract test: a write that is not create-only under `bodies/`, `receipts/` or `provenance/`, or a receipt line with a credential parameter in a recorded URL, is refused before any I/O. Then bind one body store with an R2 adapter and a local-disk adapter, and route every raw write through it, including the writers that lay out bodies themselves.
4. **Ingest policy set once,** where capture builds its store. The raw-intake exclusion gate is deleted.
5. **Body existence by key:** the in-run set, the older-copy check on `<sha>.gz`, then a create-only PUT and its 412. No index lookup.
6. **Code identity for recovery imports:** the git tree hash plus the lockfile digest, refusing uncommitted application code.
7. **Recovery importer:** reconcile `accepted.json` with the receipts, so recoveries become provenance records the model reads, each with its kind; new imports write date-shaped receipts with their recovery category, and provenance, through the body store.
8. **Review recorder:** the review forms record provenance verdicts that target link keys ([[DATA-MODEL]] §5.3, §7.9). The 86 published assistant reviews of document kinds carry over as `kind_override` records on their files' link keys, with the assistant as reviewer.
9. **Raw verifier** ([[ARCHITECTURE]] §7.4, §10.3.7), in publish's CI concurrency group: the LIST joined to recorded keys and verification records, a one-time re-hash of any body with no creating line, the 25-body sample, the orphan report and release retention. It joins to the old capture index until D1 exists.
10. **The one-time full re-hash** of bodies written before receipts carried an MD5 (after B13), skipping the keys B13 verified.
11. **A ratchet test:** no test-only branch or test-only input substitution may appear in a surviving component; tests inject adapters instead ([[ARCHITECTURE]] §15, item 7).
12. **Owed while the old capture path runs:** repair wrong `stored_sha256` index rows in place, and confirm the daily capture writes correct values. The target reads receipts, so these matter only until the switch.
13. **Uncompressed copies of older gzip PDFs** (after B1 and B3), by one PDF copier bound as [[BINDINGS]] §3 says. The largest raw write in the plan, so the lock and the refusal matrix come first. It takes its candidates from capture rows, handles bodies of any size, makes no HEAD before an upload, writes create-only to `bodies/sha256/<aa>/<sha>.pdf` with Content-MD5 and the decompressed SHA-256 checked before upload, and writes a verification record for both the `.gz` source and the `.pdf` copy. About 261,055 uploads and 403 GB once decompressed (about $72 a year of storage under the lock). Copies that already exist return 412 and get their record. Running it before B10 saves B10 about 365 GB of reads.
14. **Re-fetch the cut-off files** (first, through today's capture path): every URL with a copy cut off at 64 MiB and no complete 2xx copy, 62 to 64 by the snapshot index depending on how a complete copy is counted; the receipts decide. The cut-off copies stay in raw.
15. **The 2026-10-15 recovery run needs no correction.** All 5,587 lines of `receipts/documents/2026-10-15/download-filename-recovery-all-*` are `retained_import` recoveries with a synthetic HTTP 200 (5,154 recovered copies, 341 hearing-record excerpts, 92 official substitutes). The old capture index had flattened them into fetches. What remains is in D1 and E1.
16. **Committee and meeting fetches through the fetcher** like every other fetch: the Congress.gov committee and meeting APIs, with the API key in a request header so it never reaches a recorded URL, and the House and Senate meeting inventories.

**Done when:** every older receipt is cleaned and verified, the refusal matrix passes, the lock is on all three prefixes, one capture run's `stored` lines carry MD5s that match the stored ETags and every line carries its stored suffix, every older gzip PDF has a recorded copy, and every cut-off URL has a complete copy or a recorded reason.

### 6.3 Track C: Engine

**C0, first moves on engine main** (beside M1): the engine changes [[BINDINGS]] §3 lists before any capability work, chiefly removing modes and predicates nothing depends on, writing the table properties of [[DATA-MODEL]] §6, hashing while writing, no HEAD or re-download of immutable files, and the remote write caps unless M1 keeps them. The engine's digest for every runner OS, Linux included, is recorded in congressional-tech and checked there.

**Then the capabilities of [[ARCHITECTURE]] §13, each with its contract test:**

| # | Capability | Contract test |
|---|---|---|
| C1 | Multi-input SQL plans over Basin tables and Parquet files in one context | A plan joining two tables and a file |
| C2 | Append through the REST catalog, with the conflict retry | M1's two tests |
| C3 | Deterministic multi-file export with the per-file writer settings of [[DATA-MODEL]] §8.1 | Byte equality across threads, input orders, batch sizes and a forced spill; hyparquet page reads on the output |
| C4 | ConnectedComponents in memory over dense integer IDs, refusing above a node cap, with no application logic in the engine | M2's graph; a refusal test |
| C5 | Streaming I/O: single create-only PUTs with no multipart, no re-read and no HEAD of immutable files beyond the two allowed | Request counts in a test |
| C6 | Bounded threads, memory pool and scratch; wide columns kept off hash-join build sides | A join at the pool limit fails clearly; M2's build sizes |
| C7 | A CLI that runs a declarative job spec and returns a machine-readable result | The M2 export as a job spec |
| C8 | Generic URL functions: RFC 3986 reference resolution and percent-encoding normalization | Conformance vectors from RFC 3986 §5.4, and golden vectors from today's fetcher's URL handling; M2's `url_key` timing |

**Not needed any more:** the lifecycle store's commit requirements, lifecycle-store compaction on R2, copy-on-write measurement and insert-if-absent. The target has no engine lifecycle store, no updates and no news_lake work. Close them unless another consumer needs them.

**Done when:** one CLI job runs the full export from Basin tables, byte-identical across threads, input orders and batch sizes and with a forced spill, on the smallest runner.

### 6.4 Track D: Lake Producers

Each producer is built to [[ARCHITECTURE]] §8 and [[DATA-MODEL]] §6.

1. **Captures ingest:**
   - ingest from date-shaped prefixes only, per family, from the newest ingested date;
   - backfill from all 2,289 receipts (1.08 GB compressed), including the non-date segments (`undated/`, `mixed-dates/`: 49 files, 2.2M rows); older receipt shapes are mapped in the versioned ingest mapping, with a test sample of each shape, and every older row gets `stored_suffix = '.gz'`;
   - the backfill restores the statuses today's index dropped for 1.04M bodiless lines, and checks whether the undated receipts' JSON carries times the old index dropped (2.7M capture rows have none today);
   - the rebuild-equivalence test;
   - **compare with the pinned old capture index** (3,909,134 rows) on receipt-derived columns, with written transformation rules for the expected differences: statuses restored on bodiless lines, `stored_md5` and `stored_suffix` new, `stored_sha256` gone. A row that exists only in the old index is a fact raw does not hold, and it blocks the switch until the owner decides (§8).
2. **Parsers:**
   - first `sniff` over every older body: about 1.04M ranged GETs, timed in the run. The real-file rule needs a format for every body;
   - then HTML, XML and JSON (about 5 GB; 287,765 bodies the server labels HTML or XML), including each page's links as written with their `group_path`, and each page's fingerprint, with the table's size (links and `text_head` included) measured. There is no PDF parser for now;
   - then `fingerprint` for the other candidates: about 300 bodies (1.4 GB) at contested endpoints;
   - then M2's link join and grouping, repeated on the real links and fingerprints.
3. **Filename reader:** a producer that runs the filename parser over its work list and appends through the engine. Backfill is 7–18 minutes over 1.39M pairs.
4. **Committee and meeting parsers, committees** (needs B16): the JSON parser, once per response and version.
5. **Committee and meeting parsers, meetings** (needs B16): the JSON and XML parsers, once per response and version.
6. Enable Basin compaction and snapshot expiration on all five tables, and on each new `captures` table when an ingest mapping version creates it.

**Done when:** all five tables exist with complete backfills at the pinned versions, and both `captures` comparisons pass.

### 6.5 Track E: Model

1. **The rules, written in S** (§5.3). The file-shape list starts from the broader list (44,047 file-shaped bodies); the roughly 27k bodies between it and the narrow list (16,775) are sampled before it is fixed.
2. **The model SQL:** every relation and release file of [[DATA-MODEL]] §7–8, with the invariants of §10 as its test suite.
3. **Golden vectors** for `source_id` and `document_id`, generated from today's ID code with its compact-JSON serialization and checked in the engine's tests.
4. **Parity against the pinned catalog pair** (not F0, which picks one document per shared body), on browser-visible fields, compared many-to-many and keyed by source evidence: the files and URLs each document holds. IDs match today's wherever their inputs match. Expected, explained changes:
   - about 560k catalog rows leave the list (captions, metadata records, playlists, API responses), and listing pages leave it too;
   - about 30k documents lose error pages from their body sets, and about 4,900 lose Senate landing pages;
   - cut-off copies, recovery imports and broken PDFs drop out of body sets, and so do pages whose reading failed (reported by format and error type), while real web pages now count in body sets;
   - document kinds now also come from the publisher's link labels where the filename gives none;
   - each file has one name, so the files today's catalog lists under several names (about 95,000 carry a download-header name) collapse to one, with different `source_id`s;
   - about 16k format groups merge (32,547 documents today);
   - link-label coverage changes, because labels now come from saved pages; labels that came only from scraper records inside receipts are their own cause;
   - capture dates change where receipts lack times.
   - **The comparison reports by cause, not by document:** each known cause has a checkable predicate, its count and a few reviewed examples, and every difference that fits no known cause is listed separately. Only that last group needs reading one by one.
   - Classify each unexplained difference: a rule change (fine, recorded with the rule); an old-pipeline error (the new model wins); or a fact that exists only in derived tables (a blocker, §8).

**Done when:** every known cause has its predicate, count and examples, every unexplained difference is classified with no blocker left, and the model runs as a CLI job on the smallest runner.

A full Python rebuild of the old catalog is not needed: the pinned catalog pair is the oracle.

### 6.6 Track F: Publish Job, Capture Scheduler and Switch

1. **Workflows** ([[ARCHITECTURE]] §12): the capture job; the publish job; the weekly maintenance job in publish's CI concurrency group. The disabled viewer workflow and its 30-minute cron are deleted.
2. **Capture scheduler:** capture reads `url_state` from the live release, including its queue of linked-but-unfetched URLs, stops reading the raw index, and drops its replay mode.
3. **Delete what is bound to nothing,** one PR per group as [[BINDINGS]] §5 lists them, measured again at cut. The engine cuts apply only to code no consumer uses after the switch.

**Done when** the switch checklist holds:
- the explorer serves an engine-built release, and the reader opens saved files, alternates and recoveries from it;
- every older gzip PDF's copy is recorded (B13);
- the canary and contract test pass the speed targets set on real devices, against that release;
- a failed canary is shown to leave the previous release live;
- capture runs from `url_state` with no raw-index read;
- the old workflows are gone, and the deleted line counts are recorded.

## 7. Parked

- **news_lake** keeps the DocSpec backend and the engine's lifecycle store. No work until it adopts the three layers.
- **The freeze:** no browser or engine performance work beyond this plan until there is a user or a measured failure on real data.
- **Committee explorer and weekly retention onto incremental tables:** the approach conflicts with the design. Re-scope it before starting.
- **Considered, not chosen,** so not re-proposed without new information: showing the original link's last status (36,137 documents' URLs last returned 404 or 410), showing saved-file size (3,042 over 50 MB), and witness links from House meeting XML.
- **Parquet variant for the folds:** revisit when all three hold: an iceberg-rust release writes variant through its Parquet writer (0.10.1, the pinned release, has none; 0.11 is expected to add it), Basin Catalog accepts format-version 3 tables, and DataFusion core or a maintained crate can query variant. The candidates are nested, mixed-type readings such as Congress.gov API JSON and MODS or meeting XML trees. House-naming metadata stays typed facets plus the fold regardless.
- **Full-text extraction of every PDF:** one later read of about 403 GB into `pdf_text` ([[DATA-MODEL]] §6.6). It gives page counts and text fingerprints for every PDF, which makes dedupe across sites cheap to revisit.

## 8. Open Issue

**Only if needed:** if D1 or E4 finds facts that exist only in derived tables, including link labels found only in scraper records inside receipts, the owner decides whether to record them as provenance first or accept losing them.

## 9. References

**[ARCHITECTURE]**
: *Congressional Document Archive: Architecture.* Editor's Draft, 2026-10-24. `docs/engine-first-architecture.md`.

**[DATA-MODEL]**
: *Congressional Document Archive: Data Model.* Editor's Draft, 2026-10-24. `docs/engine-first-data-model.md`.

**[BINDINGS]**
: *Congressional Document Archive: Implementation Bindings.* Note, 2026-10-25. `docs/plans/bindings-20261025.md`.
