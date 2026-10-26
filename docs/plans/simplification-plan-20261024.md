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

The raw log already exists: bodies, receipts and provenance in the R2 bucket `congressional-tech-raw`, backed up on 2026-10-24. Its bodies are preserved unchanged and keep their stored form; older gzip PDFs gain uncompressed copies; older receipts are cleaned once of cookies, credential parameters and local paths. Everything above raw is rebuilt.

Already in place: the hosted setup refuses an engine revision other than the qualified one; the capture schema carries `stored_sha256` from the receipt and never derives it; the gzip-deleting path is gone; and the 12,431 recoveries that existed only in `accepted.json` have a write-once backup under `provenance/recoveries/`. The bucket lock is pending with the owner.

## 2. Strategy

**Contracts first.** Each component's contract suite ([[ARCHITECTURE]] §6, principle 8) is written before any code is bound to it.

**Bind, adapt or build.** For each component, [[BINDINGS]] records the existing code that implements it, the adapter work that closes the gap to the contract, or that it is built new. Code that already meets the contract is lifted, not rewritten; code that carries a broken pattern is not adapted, and the component is built with only its sound parts lifted. Hard-won behavior becomes registry seeds and fixtures rather than code paths.

**One implementation per component.** Where today has several implementations of one component, the binding picks one and the rest are deleted. External systems are the only variation, and they are injected adapters: the object store and local disk, the direct and provider transports, the catalog.

**Switch, then delete.** The target components are built beside the old pipeline. At the switch the publish path binds to them; the old layers are then bound to nothing and are deleted whole, as [[BINDINGS]] §6 lists them. Until the switch, the old capture job keeps writing raw data and reading the raw index, and gets raw-safety fixes only; its whole-leaf index rewrites continue until then, which is accepted.

## 3. Constraints and Rules

**What must survive:** objects in `congressional-tech-raw` under `bodies/`, `receipts/` and `provenance/`. Everything else can be rebuilt, and nothing uses it yet.

**Rules for every step**

- One conceptual move per PR. Contract tests land before the code bound to them moves. Behavior changes go in their own PRs.
- Run checks only through the project runners: `.venv/bin/python scripts/dev.py test <lane>` in congressional-tech and `scripts/check` in docspec-rs. Never use a tool from `PATH`. Say this in every agent and reviewer brief.
- Work in a separate worktree and venv. The primary checkout backs live recovery jobs.
- Report before and after `wc -l` in every PR that deletes code.
- Each step names its evidence: a contract test, or a measurement committed under `docs/`, never in the gitignored `output/`. A change to a rule names the fixtures it re-ran.
- Create the ticket before the first code commit. An epic closes only after its children. Acceptance criteria name an observable behavior and the test or measurement that shows it. Performance work records a baseline on real data and the decision rule first. A deletion closes only when the old path is gone.

**Merge check**

1. Before and after each merge that touches a raw-writer component, list `receipts/` and `bodies/` read-only. Every earlier key is still there with the same size and ETag; only additions are allowed. B0's one-time receipt cleanup is the single exception, and its verification records account for every change.
2. Every receipt-referenced body exists.
3. After the bucket lock: read the lock rules back after any infrastructure change.

## 4. Order of Work

1. The bucket lock on `bodies/` and `provenance/` (owner, B1), at once; then B0; then the lock on `receipts/`.
2. M1, M2 and S1; S2 beside track C.
3. F0 and the hand-built fixture; C0; tracks A and B.
4. Track C, then D, then E, then F.

| Track | Components | Depends on |
|---|---|---|
| A | Reader, canary and contract test, site | F0 and the hand-built fixture |
| B | Raw-writer components | The lock on `bodies/` and `provenance/` first; the old writers patched, then B0, then the lock on `receipts/` |
| C | Engine | M1, M2, S1 |
| D | Lake producers | C2, B2; B13 for D2; B16 for D4 and D5 |
| E | Model | S1, S2, C1, C3, C4, D |
| F | Publish job, capture scheduler, switch | A, E, B13 |

A and B can run beside C. The widest uncertainty is E: it stays bounded unless parity finds facts that only derived tables hold (§8).

## 5. First Steps

### 5.1 M1: Basin Catalog Under Maintenance

All three run on scratch tables, with Basin's catalog-level compaction and snapshot expiration on.

1. **Guarded commits.** An append whose base snapshot a second client's commit has moved fails rather than being rebased, recomputes its work list and lands within three retries; two ingest runs on the same receipts leave exactly one copy of each row. A second client's commit stands in for Basin's maintenance, which cannot be timed.
2. **Growth, expiration and drops.** With snapshot expiration at its shortest age, append day-sized batches (about 315 KB) across at least ten Basin maintenance runs. After each run, count the current snapshot's data files and manifests and the bytes expiration removed. Read the table through iceberg-datafusion 0.10.1's static provider with a partition filter, and confirm the filter reaches scan planning. Then drop the table with purge and list what remains.
3. **The engine's remote write caps.** Measure scan and commit cost with and without the engine's 2 MiB file and 2,048-row group caps. [[DATA-MODEL]] §6 assumes they go; if they measurably help, that section changes instead.

**Decides:** Iceberg stays (data files and manifests bounded), or the lake tables move to dated Parquet files with an `If-Match` manifest per table: the same atomicity, without time travel. The fallback changes the scope of C1, C2 and D.

### 5.2 M2: Wide Joins and Grouping in a Throwaway DataFusion Harness

The engine cannot run the full export until C1, C3 and C4 exist, so a short standalone DataFusion program measures first, using S's draft rules.

- Inputs: the pinned 2026-10-19 snapshot (captures `db033173…`, catalog generation `596f08fa…`), including today's filename readings and links parsed from a sample of pages.
- Run the model's joins, including `url_key`, link resolution and the link join (about 4.2M links, scaled from the sample, against 1.31M source URLs), filename readings, the folded `detail` and the 1.7M `occurrences`. Report every intermediate join's row count and bytes and every hash-join build's size, as well as time and peak memory. The links are sampled, so this tests mechanisms and memory; D2's full link backfill repeats the join on real data.
- Run the model twice: as one plan, and as named steps with the components and documents materialized once. Compare `EXPLAIN ANALYZE`, time and peak memory, including memory the pool does not account for.
- Group the graph with the specified rule, using the sampled links; D2 repeats the grouping on real links. Record time, peak memory and the largest components.
- Run on `ubuntu-24.04` (4 vCPU, 16 GB), the smallest runner class.

**Decides:** the size of track C, the model's step form, and whether DataFusion handles the wide joins within the pool. The harness is deleted afterwards.

### 5.3 S: The Semantic Checkpoint

E1 is written here: every derivation of [[DATA-MODEL]] §7 as SQL, and the reference model profile, every registry as a versioned file with its first contents and sample tests, seeded as [[BINDINGS]] §4 lists. Each fixture below is written with its expected outcome before any SQL, so the table is the acceptance sheet. S1's fixtures run as an executable model, the draft SQL over fixture tables, before any further change to the rules they cover. S comes in two parts:

- **S1, before track C** (M2 and the engine depend on it): the real-file and grouping SQL with their fixtures, marked S1 below;
- **S2, beside track C:** the rest of the SQL and fixtures, the labeled sample, the edition count and the raw-only check.

| Part | Fixture | Expected outcome |
|---|---|---|
| S1 | A PDF replaced while its XML stays, with historical pages linking both | Three documents: each PDF edition alone, and the XML alone |
| S1 | Two mirrors that each pair one of two editions with the same XML | No document holds both editions |
| S1 | Re-packaged copies of each edition, each paired with one XML, never at a shared address | The known limit: such a copy can join the XML; the edition count measures how often |
| S1 | A ZIP repacked so `report.pdf` moves to another position, with mirrors pairing each edition with the same XML | One edition-ambiguous endpoint; the editions stay apart |
| S1 | Two archive members with one name and different bytes | An edition-ambiguous endpoint; neither member takes a rendition edge |
| S1 | A linked GovInfo ZIP holding one hearing's HTML and PDF; a linked ZIP holding two different PDFs | The ZIP and both members form one document; no rendition edges |
| S1 | Several same-format files listed together; unrelated files on one page outside any list item | Each stays its own document; the unlisted files get no publisher group |
| S1 | One PDF body under two download names, listed with its XML | One document with both names and the XML; the group counts one PDF body |
| S1 | One page template under two hearings, where only hearing A's PDF and hearing B's XML were captured | No rendition edge between them |
| S1 | One old page saved by two archives with different menus | One document: equal main-content fingerprints |
| S1 | A page with relative links saved in two directories; a relative `<base href>`; a page whose relative links point at sibling archive members | Each copy's links resolve against its own address and base; member links target endpoints in the same container |
| S1 | A concatenated `href` whose two targets both exist | Two links, in `href` order, one target each |
| S1 | URLs written with raw spaces and with `%20` | One `url_key` |
| S1 | A placeholder page at thousands of addresses | Not a real file; it connects nothing, and its links are not resolved |
| S1 | A short real hearing page; a short soft-error page; a near-empty page; a "your download will begin" page | `document`; `error_response`; `error_response`; `wrapper`, with its file link queued |
| S1 | A broken PDF; a valid PDF with trailing bytes after its end marker; a new valid PDF; a PDF over the reader's limit with no end marker in its tail; an older gzip PDF with no verified copy | `damaged`; real; real, from the `intact` its capture recorded; `damaged` and reported; `damaged` |
| S1 | An Office file | One body, no members |
| S1 | A feed page | `listing`, and no link context |
| S1 | A response with no declared length read to a clean end; a body assembled from ranges of one entity; ranges whose entity changed in between | Complete; complete; not complete |
| S1 | A cut-off direct attempt and a complete provider retry in one fetch | The retry's body is real; the cut-off body is not |
| S1 | A recovered file that a real fetch also saved | A real body and link key; the recovery attaches as labeled evidence |
| S1 | An incrementally maintained lake and a clean rebuild, after a registry change and after a table rebuilt at a new schema | Byte-identical releases |
| S2 | One body under two filenames | Two source files in one document, which shows the saved file's name |
| S2 | A file named only by its download header; a URL with `?file=a.pdf&name=b.pdf` | The header's name (`filename*` first); `a.pdf` |
| S2 | An exact copy and a provider's saved-text copy at one URL | The exact copy is the saved file |
| S2 | A file whose kind only the publisher gives, by `doc_type`, and another by link text only | Each gets the publisher-kind registry's kind |
| S2 | A committee-removed document; one removed and later re-added | `removed_on` set; null |
| S2 | A meeting named only by a GovInfo MODS record; a meeting with no record | The package's source files carry the meeting; the meeting is listed by key with null details |
| S2 | A `Retry-After` beyond the family's recheck interval; a URL whose latest line has no time | `next_attempt_at` capped at the interval; due now |
| S2 | An API list URL whose latest attempt failed after a good fetch | The relist window starts at `last_good_at` |
| S2 | A queue link carrying a credential parameter | The queue row has it removed |
| S2 | A recovery at an edition-ambiguous link; a recovery import for a URL never fetched | A document of its own each; the URL enters the queue |
| S2 | A recovery-only link that later downloads | Its link URL key opens the document that now holds the download, where the recovery attaches |
| S2 | Two recoveries equal in kind, time and body; decisions that match one recovery row twice; a recovery whose decision rejects it | Both shown, in receipt order; one recovery, from the latest decision; no recovery |
| S2 | Two merged documents with different title overrides; two active merges on one document; a hide and its withdrawal | The latest override by `(decided_at, id)`; both merges applied; visible again |

- **The labeled sample:** a hand-labeled stratified sample of a few hundred files, starting from the responses already labeled by hand and the 2026-10-25 short-page sample ([[BINDINGS]] §4), covering short real pages, challenge, soft-error and download pages, archive members, landing pages, listing pages, files listed together on one page and widely mirrored real documents. It is the sample of [[ARCHITECTURE]] §15, item 2, and sets the page thresholds and the final file-shape list. It includes a listing page captured in two places and pages whose links sit outside any list item. The labeling rubric: a file is a real document when its main content is the document itself (testimony, a report, a transcript, a bill, a hearing record), not a list of links to documents, a landing, download or error page, or metadata about a document. Two files are one document when they hold the same content: identical bytes, the same main text at one address, or one text in different formats.
- **The edition count**, for the owner's decision: every real body that shares a rendition group with a body in `edition_bodies` and is not itself a fingerprint candidate (*est.* about 15 bodies and 1.4 MB by the same-stem groups; publisher groups are counted again after D2's link backfill) is fingerprinted, and the count is of those whose text equals such a body's. S reports the count with examples; the owner then decides whether to widen the candidates to every rendition-group member (*est.* 8–45 GB of reads once).
- **The raw-only check:** every rule can be computed from raw, with nothing borrowed from the old derived tables.

### 5.4 F0: The First Release, Converted From the Pinned Catalog

- A converter writes the pinned catalog pair in the release format ([[DATA-MODEL]] §8.1) with the final writer settings. It uses the engine's RunSpec where it can.
- This release is the reader's fixture (track A). Its manifest records that it came from the pinned catalog. It does not go live: the explorer waits for the engine-built release.
- **It fills what it can:** meeting keys from URLs, document dates from the old metadata, link labels from the old occurrences, and committee names from today's committee file. It keeps all 1.24M of today's catalog rows, so it is about twice the target `list`.
- **It cannot show** format groups, meeting titles or the new recovery kinds, so a small hand-built fixture release covers them: one document with PDF and XML alternates, one titled hearing in `meetings`, one of each recovery kind and one hidden document. The contract test runs both.
- **It assumes nothing unique about old bodies:** 141,762 body keys appear in several old documents, so F0 resolves each link key to the first document in list order.
- The converter is a migration tool, deleted at the switch.

## 6. Tracks

Each task names the component it builds or binds and the contract it must pass. [[BINDINGS]] §3 says which existing code is bound to each component and what changes.

### 6.1 Track A: Reader, Canary and Site

1. **Reader** to [[ARCHITECTURE]] §11, with hyparquet's `useOffsetIndex` for `detail` (each row group's offset index cached for the session) and `usePageIndex` for `links`.
2. **Links** resolve through `links` ([[ARCHITECTURE]] §10.1).
3. **Canary** ([[ARCHITECTURE]] §10.3.5), run by the publish job against the uploaded candidate.
4. **Contract test** ([[ARCHITECTURE]] §15, item 5), against F0 and the hand-built fixture until track E exists.
5. **Saved copies** ([[ARCHITECTURE]] §11.5).
6. **Dates:** the document date and capture date in list rows, so same-filename editions read apart; on the document page, the labels of [[ARCHITECTURE]] §11.6.
7. **Recoveries** ([[ARCHITECTURE]] §11.5; [[DATA-MODEL]] §8.1), each on the page the attachment rule gives it.
8. **Link context:** "where each copy was seen" names the page that linked it and the link's label.
9. **Meetings and record links:** filter and sort by document date; list every document for a hearing under its title, date, type and committee; link out to the GPO record, the bill and the member.
10. **Removed by review** ([[DATA-MODEL]] §7.9).
11. **Speed, measured then fixed:** measure startup, search, detail and heap on real phones and desktops with F0, then write those targets into the canary and contract test. F0's size makes these targets conservative; re-measure on the first engine-built release.

**Done when:** the site loads F0 locally on desktop and in a phone-sized profile, and the canary passes against F0 in under a minute.

### 6.2 Track B: Raw-Writer Components

These components survive, so they are bound now.

0. **Clean the older receipts, once, before `receipts/` is locked** ([[DATA-MODEL]] §5.2). A full scan on 2026-10-25 found 534,733 recorded cookies on 242,438 lines and local paths in more than 40 fields, and receipts are public.
   - **First, stop the old writers adding more:** today's capture and import writers drop cookies, credential parameters and local paths (241,328 of the 530,081 lines written in the two weeks before the scan carry a `Set-Cookie`, and the newest import runs a path on every line). No import runs between the cleanup and the lock on `receipts/`.
   - **The fields:** the read-only scan lists, by field, the values that look like local paths, including paths inside JSON key names; its list is committed with B0, the owner confirms it before the run, and no other field is touched. The input is the receipt keys in the 2026-10-24 backup plus any written since; each receipt not in the backup is copied into it before it is rewritten.
   - **The tool** is a one-off rewriter outside the body store, with its own credential, deleted once B0 is verified. The body store stays create-only throughout.
   - **The run:** for each receipt without a verification record, write the cleaned bytes to the same key with `If-Match` on the original ETag and `Content-MD5`; re-read it; check that every line equals the original minus exactly the listed values and key names, that no recorded URL changed except by losing a credential parameter, that no `links[]` value changed, and that every `pointer` still resolves to the same entry (a listed key that a `pointer` passes through is left uncut and reported to the owner); and record the result, with the fields [[DATA-MODEL]] §5.3 lists, in a few batched verification files. A rerun skips receipts already recorded, and after a crash it verifies against the backup's original.
   - **The safety net:** the private 2026-10-24 backup keeps the originals.
   - **Done when:** every receipt under `receipts/` has a verification record and a re-scan finds no cookie, credential parameter or local path in the listed fields.
1. **Bucket lock** (owner), per prefix: `bodies/` and `provenance/` at once, `receipts/` after B0.
2. **Fetcher, receipt writer and archive expander** to [[ARCHITECTURE]] §7.1–7.2 and [[DATA-MODEL]] §5.2, proven by their contract suites, with scope, redirects, pacing and fallback from the registries.
3. **One body store.** Write the refusal matrix first, as the body store's contract test: a write that is not create-only under `bodies/`, `receipts/` or `provenance/`, or a receipt line with a credential parameter in a recorded URL, is refused before any I/O. Then bind one body store with an R2 adapter and a local-disk adapter, and route every raw write through it, including the writers that lay out bodies themselves.
4. **Ingest policy set once,** where capture builds its store. The raw-intake exclusion gate is deleted.
5. **Body existence by key** ([[ARCHITECTURE]] §7.1), never by an index lookup.
6. **Code identity for recovery imports:** the git tree hash plus the lockfile digest, refusing uncommitted application code.
7. **Recovery importer:** reconcile `accepted.json` with the receipts, so recoveries become provenance records the model reads, each with its kind; new imports write date-shaped receipts with their recovery category, and provenance, through the receipt writer and the body store, with no guards or upload loop of their own. Six accepted recoveries attach a 2-page excerpt to full 95–196-page transcripts; the owner reviews them, and each one confirmed wrong gets a `rejected` decision.
8. **Review recorder:** the review forms record provenance verdicts that target link keys ([[DATA-MODEL]] §5.3, §7.9). The 86 published assistant reviews of document kinds carry over as `kind_override` records on their files' link keys, with the assistant as reviewer.
9. **Raw verifier** ([[ARCHITECTURE]] §7.4, §10.3.7), in the maintenance job, first run after B10. It joins to the old capture index until D1 exists.
10. **The one-time full re-hash** ([[ARCHITECTURE]] §7.4), after B13, skipping the keys B13 verified.
11. **A ratchet test:** no test-only branch or test-only input substitution may appear in a surviving component; tests inject adapters instead ([[ARCHITECTURE]] §15, item 7).
12. **Owed while the old capture path runs:** repair wrong `stored_sha256` index rows in place, and confirm the daily capture writes correct values. The target reads receipts, so these matter only until the switch.
13. **Uncompressed copies of older gzip PDFs** (after B1 and B3), by the PDF copier of [[BINDINGS]] §3.1. The largest raw write in the plan, so the lock and the refusal matrix come first: about 261,055 uploads and 403 GB once decompressed (about $72 a year of storage under the lock). Running it before B10 saves B10 about 365 GB of reads.
14. **Re-fetch the cut-off files** (after B2, through the spooled fetcher): every URL with a copy cut off at 64 MiB and no complete 2xx copy, 62 to 64 by the snapshot index depending on how a complete copy is counted; the receipts decide. The cut-off copies stay in raw.
15. **The 2026-10-15 recovery run needs no correction.** All 5,587 lines of `receipts/documents/2026-10-15/download-filename-recovery-all-*` are `retained_import` recoveries with a synthetic HTTP 200 (5,154 recovered copies, 341 hearing-record excerpts, 92 official substitutes). The old capture index had flattened them into fetches. What remains is in D1 and E1.
16. **Committee and meeting fetches through the fetcher** like every other fetch: the Congress.gov committee and meeting APIs and the House and Senate meeting inventories ([[ARCHITECTURE]] §7.2, §8.5; [[DATA-MODEL]] §6.5). An incremental relist takes its window from the `last_good_at` of the API list URL it pages through, and pages to the end of the list.
17. **Fetch the wrapped files** (after B2): the file links of download-wrapper pages, *est.* 8,800 testimony and statement PDFs that were never fetched, ahead of the model's queue.

**Done when:** every older receipt is cleaned and verified, the refusal matrix passes, the lock is on all three prefixes, one capture run's `stored` lines carry MD5s that match the stored ETags and every line carries its stored suffix, every older gzip PDF has a recorded copy, and every cut-off URL has a complete copy or a recorded reason.

### 6.3 Track C: Engine

**C0, first moves on engine main** (beside M1): the C0 cleanup of [[BINDINGS]] §3.3, before any capability work. The engine's digest for every runner OS, Linux included, is recorded and checked as [[ARCHITECTURE]] §12 says.

**Then the capabilities of [[ARCHITECTURE]] §13, C*n* being its item *n*, each with its contract test:**

| # | Capability | Contract test |
|---|---|---|
| C1 | Multi-input SQL jobs | A job joining two tables, a file and a receipt; a partition filter visible in the Iceberg scan |
| C2 | Table operations | M1's commit and drop tests |
| C3 | Deterministic export | Byte equality across threads, input orders, batch sizes and a forced spill; hyparquet page reads with no dictionary page under a ranged read |
| C4 | Connected components | M2's graph; a refusal test |
| C5 | Streaming I/O | Request counts in a test |
| C6 | Bounded resources | A join at the pool limit fails clearly; M2's build sizes |
| C7 | Thin interface | The M2 export as a job spec |
| C8 | URL functions | Conformance vectors from RFC 3986 §5.4, and golden vectors from today's fetcher's URL handling; M2's `url_key` timing |

**Not needed any more:** the lifecycle store's commit requirements, lifecycle-store compaction on R2, copy-on-write measurement and insert-if-absent. The target has no engine lifecycle store, no updates and no news_lake work. Close them unless another consumer needs them.

**Done when:** one CLI job runs the full export from Basin tables, byte-identical across threads, input orders and batch sizes and with a forced spill, on the smallest runner.

### 6.4 Track D: Lake Producers

Each producer is built to [[ARCHITECTURE]] §8 and [[DATA-MODEL]] §6.

1. **Captures ingest:**
   - backfill from all 2,289 receipts (1.08 GB compressed), including the non-date segments ([[ARCHITECTURE]] §7.2), with a test sample of each older receipt shape ([[DATA-MODEL]] §6.1);
   - the backfill restores the statuses today's index dropped for 1.04M bodiless lines, and maps a time from every receipt shape: 522,448 rows in dated receipts have no time in the snapshot, and 47,359 of them carry one on their line;
   - the rebuild-equivalence test;
   - **compare with the pinned old capture index** (3,909,134 rows) on receipt-derived columns, with written transformation rules for the expected differences: statuses restored on bodiless lines, completeness per attempt, `stored_md5` and `stored_suffix` new, `stored_sha256` gone. A row that exists only in the old index is a fact raw does not hold, and it blocks the switch until the owner decides (§8).
2. **Parsers:**
   - first `sniff` over every older body, after B13 so a PDF's tail is read from its `.pdf` copy: about 1.04M ranged GETs plus about 261k tail reads, timed in the run;
   - then the main-content extractor, chosen by measurement on the ~960 veterans.house.gov pages two archives saved and on the labeled sample;
   - then HTML, XML and JSON (about 5 GB; 287,765 bodies the server labels HTML or XML), with the table's size (links and `text_head` included) measured. There is no PDF parser for now;
   - then `fingerprint` for the other candidates, measured here;
   - then M2's link join and grouping, repeated on the real links and fingerprints.
3. **Filename reader:** a producer that runs the filename parser over its work list and appends through the engine.
4. **Committee and meeting parsers, committees** (needs B16): the JSON parser, once per response and version.
5. **Committee and meeting parsers, meetings** (needs B16): the JSON and XML parsers, once per response and version.
6. Enable Basin's catalog-level compaction and snapshot expiration.

**Done when:** all five tables exist with complete backfills at the pinned versions, and both `captures` comparisons pass.

### 6.5 Track E: Model

1. **The rules, written in S** (§5.3). The file-shape list starts from the broader list (44,047 file-shaped bodies); the roughly 27k bodies between it and the narrow list (16,775) are sampled before it is fixed.
2. **The model SQL:** every relation and release file of [[DATA-MODEL]] §7–8, with the invariants of §10 as its test suite.
3. **Golden vectors** for `source_id` and `document_id`, generated from today's ID code with its compact-JSON serialization and checked in the engine's tests.
4. **Parity against the pinned catalog pair**, the oracle (not F0, which picks one document per shared body), on browser-visible fields, compared many-to-many and keyed by source evidence: the files and URLs each document holds. IDs match today's wherever their inputs match. Expected, explained changes:
   - about 615k catalog rows (captions, metadata records, playlists and API responses; [[DATA-MODEL]] §7.5) and the listing pages leave the list;
   - documents lose soft-error and wrapper pages, and about 4,900 lose Senate landing pages, from their body sets, while short real pages and real web pages now count;
   - cut-off copies, damaged PDFs and pages whose reading failed (reported by format and error type) drop out of body sets, and feed pages become listings;
   - the 3,558 recovered files that a real fetch also saved become real bodies;
   - about 960 veterans.house.gov pages saved by two archives merge by main content;
   - document kinds now also come from the publisher's link labels where the filename gives none;
   - a file's name comes from each capture row, download header first: about 95,000 files carry a download-header name and change `source_id`, and a body offered several names keeps one source file per name in one document;
   - about 460,000 rows today named only from `download_state` are saved-text duplicates of exact copies at the same URL, and collapse into their twins; where a URL's copies differ (532 URLs), the exact copy becomes the saved file;
   - about 16k format groups merge (32,547 documents today);
   - `document_id` keeps today's formula, but its inputs now include real web pages;
   - link-label coverage changes, because labels now come from saved pages; labels that came only from scraper records inside receipts are their own cause;
   - capture dates change where receipts lack times.
   - **The comparison reports by cause, not by document:** each known cause has a checkable predicate, its count and a few reviewed examples, and every difference that fits no known cause is listed separately. Only that last group needs reading one by one.
   - Classify each unexplained difference: a rule change (fine, recorded with the rule); an old-pipeline error (the new model wins); or a fact that exists only in derived tables (a blocker, §8).

**Done when:** every known cause has its predicate, count and examples, every unexplained difference is classified with no blocker left, and the model runs as a CLI job on the smallest runner.

### 6.6 Track F: Publish Job, Capture Scheduler and Switch

1. **Workflows** ([[ARCHITECTURE]] §12): the capture job; the publish job, backfills and the maintenance job in one CI concurrency group. The disabled viewer workflow and its 30-minute cron are deleted.
2. **Capture scheduler:** capture reads `url_state` from the live release, including its queue of linked-but-unfetched URLs, stops reading the raw index, and drops its replay mode.
3. **The committee explorer** reads committee and meeting records from the lake ([[ARCHITECTURE]] §8.5), not from the fetchers' state files.
4. **Delete what is bound to nothing,** one PR per group as [[BINDINGS]] §6 lists them, measured again at cut.

**Done when** the switch checklist holds:
- the explorer serves an engine-built release, and the reader opens saved files, alternates and recoveries from it;
- every older gzip PDF's copy is recorded (B13);
- the canary and contract test pass the speed targets set on real devices, against that release;
- a failed canary is shown to leave the previous release live;
- capture runs from `url_state` with no raw-index read, and the committee explorer reads the lake;
- the old workflows are gone, and the deleted line counts are recorded.

## 7. Parked

- **news_lake** keeps the DocSpec backend and the engine's lifecycle store. No work until it adopts the three layers.
- **The freeze:** no browser or engine performance work beyond this plan until there is a user or a measured failure on real data.
- **Committee explorer and weekly retention onto incremental tables:** the approach conflicts with the design. Re-scope it before starting.
- **Considered, not chosen,** so not re-proposed without new information: showing the original link's last status (36,768 documents' URLs last returned 404 or 410), showing saved-file size (2,467 files over 50 MB), and witness links from House meeting XML.
- **Parquet variant for the folds:** revisit when all three hold: an iceberg-rust release writes variant through its Parquet writer (0.10.1, the pinned release, has none; 0.11 is expected to add it), Basin Catalog accepts format-version 3 tables, and DataFusion core or a maintained crate can query variant. The candidates are nested, mixed-type readings such as Congress.gov API JSON and MODS or meeting XML trees.
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
