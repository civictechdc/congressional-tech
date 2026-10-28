# Congressional Document Archive: Implementation Plan

**Note, 2026-10-24.** Not a specification: it carries no normative requirements and cites contracts rather than restating them.

## Abstract

- **Goal:** build the system of [[ARCHITECTURE]] and [[DATA-MODEL]] from today's congressional-tech and docspec-rs code, beside the old pipeline, then switch and delete what is bound to nothing (§2). Work runs in dependency order, with no schedule or effort estimates.
- **Two phases:** phase 1 is the documents-only switch; phase 2 adds hearings, witnesses, the spicy-regs entities and the large one-time raw jobs. §4 scopes both; [[PHASE-2]] holds phase 2's rules and gates.
- **First:** B15 (the weekly job's records into raw), the lock probe, the lock on `bodies/` and `provenance/`, B0, then the lock on `receipts/`; the Basin smoke check and S1 run beside them, since they touch no raw (§4–5).
- **Open (§8):** the rules on real data (S1, S2); the widest is the model (track E).
- **Owner actions,** each before the step it blocks: the rescued batch's import and the weekly job's raw token (B15); the bucket lock (B1); B0's two patterns and scan report, and its live run; the Basin smoke check (§5.1); the credentials (B0's rewriter; the capture, publish and maintenance tokens before F1); facts only derived tables hold (D1, E4), before the switch; the real-device speed runs (A11); widening fingerprint candidates (S2).
- **Detail:** behavior in [[ARCHITECTURE]]; schemas, derivations, registries and invariants in [[DATA-MODEL]] and, for phase 2, [[PHASE-2]]; code and its state in [[BINDINGS]].

## 1. Introduction

The raw log already exists: bodies, receipts and provenance in the R2 bucket `congressional-tech-raw`, backed up on 2026-10-24. Its bodies keep their stored form; the only changes are uncompressed copies of older gzip PDFs (B13) and the one-time cleanup of older receipts (B0), as [[ARCHITECTURE]] §7.1–7.2 specify. Everything above raw is rebuilt.

Already in place: the hosted setup refuses an engine revision other than the qualified one; today's capture index carries `stored_sha256` from the receipt and never derives it; the gzip-deleting path is gone; the 12,431 recoveries that existed only in `accepted.json` have a write-once copy under `provenance/recoveries/`, a whole file the model never reads ([[DATA-MODEL]] §5.3); and the versions of the weekly meeting job's source records from 2026-10-05 to 2026-10-26, which that job overwrites on each run, are kept in a local content-addressed batch until B15 imports it. The bucket lock is pending with the owner.

## 2. Strategy

**Contracts first.** Each component's contract suite ([[ARCHITECTURE]] §4, principle 8) is written before any code is bound to it.

**Bind, adapt or build,** as [[BINDINGS]] §1 defines and records for each component. Code that carries a broken pattern is not adapted: the component is built with only its sound parts lifted. Hard-won behavior becomes registry seeds and fixtures rather than code paths.

**One implementation per component** ([[BINDINGS]] §2, rule 1): where today has several, the binding picks one and the rest are deleted. External systems are the only variation, injected as adapters ([[ARCHITECTURE]] §4, principle 8).

**Reuse before re-reading.** A per-item result that raw or legacy data already settles is borrowed, with its basis recorded, and only the gaps are read; an old decision across items (grouping, matching, roles) is never borrowed, only used as a parity oracle. [[DATA-MODEL]] §6 and §7.3 say what each table reuses and what it reads, and §6.4 item 2 below gives D2's read counts (measured on the 2026-10-16 snapshot, `measurements/phase1-inventory-20261026/`).

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

1. Until `receipts/` is locked, list `receipts/` and `bodies/` read-only before and after the first run of each merged raw-writer change: every earlier key is still there with the same size and ETag, and only additions appear. B0 is the single exception, its verification records accounting for every change. After the lock, B9's weekly check replaces this.
2. Every receipt-referenced body exists.
3. After the bucket lock: read the lock rules back after any infrastructure change.

## 4. Order of Work

**Phase 1, the documents-only switch:** the site serves an engine-built release of documents, saved copies, sources, recoveries and dead-link lookups, rebuilt from raw and reusing every per-item result raw or legacy data already settles; capture runs from it; the old pipeline is deleted, except the weekly meeting job, whose inventories seed capture until B14. Phase 1's model reads `captures`, the document `readings`, `filename_readings`, provenance and the document registries. Its releases carry `meetings.parquet` with keys only, omit the other entity files, and from the first carry `schema.json` and each file's producer and coverage in the manifest ([[DATA-MODEL]] §8.1): hearing keys come from document evidence, chambers from committee codes, `witness_keys` and transcript links are empty, a document dated only by its meeting shows no date, and an undated banded URL takes its family's shortest recheck band ([[DATA-MODEL]] §7.5, §7.7).
1. B15 first, since each weekly run overwrites another version; it ships to main as its own release, ahead of the switch. On a scratch bucket with the same lock rule, record the status of a create-only PUT to an existing key, an unconditional PUT, a DELETE and a multipart create; if the first is not 412, B3 and [[ARCHITECTURE]] §7.1 change before any lock. List `provenance/` and record each object that is not a `<kind>/<ts>.jsonl` record. Then the owner locks `bodies/` and `provenance/` (B1); the old writers are patched and B0 runs; then `receipts/` is locked.
2. The Basin smoke check (§5.1) and S1, beside item 1; S2's document fixtures and the labeled sample beside track C.
3. C0; track A and track B's items 2–9 (item 8 as its one-time script), 11 and 12. F0 and the hand-built fixture exist (§5.4).
4. Track C, then D (items 1–3), then E (the document core, [[DATA-MODEL]] §7.1–7.10, and `urls`), then F (items 1, 2, 4 and 5).

**Phase 2, connections and one-time raw jobs,** adding files and facts. Three items can also change the document core: B13 (an unchecked PDF found broken leaves the list, and its links open the not-found notice), S2's widening and a fingerprint parser (editions can split).
- hearings, witnesses and recordings: B14, D4, and the meeting, appearance and recording relations ([[PHASE-2]] §2), cheap: about 60k bodies (9 GB) plus the 199,156 inline records already in the receipts;
- the spicy-regs entities (committees, members, rosters, bills, CBO estimates, floor votes, amendments, committee activities, nominations), with their pin lists and the committee explorer's move (F3–F4), after spicy-stack ss-vhi2's retention change;
- the large raw jobs: B13 (PDF copies), B10 (full re-hash), S2's edition-count widening, and C4's dense IDs (ss-6jg6);
- engine and tooling: export bytes independent of the runner class (ss-iwqu; phase 1 pins the runner class and limits instead), a `fingerprint` parser only if a PDF or unexpanded-ZIP candidate appears, and the review forms (B8).

| Track | Components | Depends on |
|---|---|---|
| A | Reader, canary and contract test, site | F0 and the hand-built fixture (done) |
| B | Raw-writer components | §4, item 1; B13 after B1 and B3 |
| C | Engine | The Basin smoke check, S1 |
| D | Lake producers | C2, B2, S1's parsers; B14 for D4 |
| E | Model | S1, S2, C1, C3, C4, D |
| F | Publish job, capture scheduler, switch | A, B2–B9, E |

A and B can run beside C.

## 5. First Steps

S settles the rules; the smoke check confirms the lake format. M2 and F0 are done.

### 5.1 M1: Basin Smoke Check

Iceberg on Basin Catalog stays, and no table depends on Basin's managed maintenance ([[ARCHITECTURE]] §8.6). The owner runs the existing probe once with their own credentials, in the dedicated scratch bucket the probe requires (`cx-engine-first-lock-probe-…`), under the same lock rules as the real bucket: create a scratch table, append three days and read them back unchanged, run its race step (the catalog must reject a stale commit, which exactly-once rows depend on), then purge it and list what remains. A failure goes to the owner before track C's table work. The engine's remote write caps go ([[DATA-MODEL]] §6). The earlier experiment's ten-year projection, race and cap trials are dropped; `docs/measurements/engine-first-20261027/m1.md` keeps it as history, with the probe's build and run commands.

### 5.2 M2: Done

The owner ended M2 and directed implementation: the nullable receipt reader is usable, the model uses named steps, and the full join, graph and memory acceptance moves to C6 and D2 (`docs/measurements/engine-first-20261027/m2-reader.md`).

### 5.3 S: The Semantic Checkpoint

S writes every rule as SQL with its fixtures (E1), in two parts:

- **S1, before track C** (the engine depends on it): the real-file and grouping SQL with their fixtures, marked S1 below, and the `sniff`, `html`, `xml` and `json` parsers (D2's code, not yet writing to the lake), with Trafilatura 2.0.0 as the main-content extractor (`docs/measurements/engine-first-20261027/s1-pages.md`); S1's real slices run on them;
- **S2, beside track C:** the rest of the SQL and fixtures, the labeled sample, the edition count and the raw-only check; its meeting, witness and spicy-regs rows wait for phase 2.

- **What S writes (E1):** the reference model profile; every registry as a versioned file with its first contents and sample tests, seeded as [[BINDINGS]] §4 lists.
- **Fixtures first:** each fixture of the acceptance sheet, `model/fixtures/manifest.md` ([[FIXTURES]]), is written with its expected outcome before any SQL. S adds a row for each format of [[DATA-MODEL]] §6.2 the sheet does not yet name.
- **An executable model:** S1's fixtures run as the draft SQL over fixture tables and over real slices (the GovInfo ZIPs, the End of Term lines, docs.house.gov's `.xml` URLs, the pages saved twice in one fetch and the short-page sample), before any further change to the rules they cover.

- **The labeled sample** sets the page thresholds and the final file-shape list. It is the sample of [[ARCHITECTURE]] §15, item 2, and its rubric is [[ARCHITECTURE]] §9.2–9.3.
  - It is a hand-labeled stratified sample of a few hundred files, starting from the responses already labeled by hand and the 2026-10-25 short-page sample ([[BINDINGS]] §4).
  - It covers short real pages, challenge, soft-error and download pages, archive members, landing pages, listing pages, files listed together on one page and widely mirrored real documents.
  - It includes a listing page captured in two places and pages whose links sit outside any list item.
- **The edition count**, for the owner's decision:
  - every real body that shares a rendition group with a body in `edition_bodies` and is not itself a fingerprint candidate is fingerprinted (*est.* about 15 bodies and 1.4 MB by the same-stem groups; publisher groups are counted again after D2's link backfill), and the count is of those whose text equals such a body's;
  - S reports the count with examples; the owner then decides whether to widen the candidates to every rendition-group member (*est.* 8–45 GB of reads once).
- **The raw-only check:** every rule can be computed from raw, with nothing borrowed from the old derived tables.

### 5.4 F0: Done

The pinned catalog pair is converted to the release format as release `62bddc63…`, keeping all 1,241,157 catalog documents, beside a seven-row hand-built fixture for what F0 cannot show (format groups, a titled hearing, versions, recovery kinds, a hidden document) (`docs/measurements/engine-first-20261027/f0.md`). Both serve the reader's development; neither is published, and the converter is deleted at the switch.

## 6. Tracks

[[BINDINGS]] §3 says which existing code is bound to each component and what changes.

### 6.1 Track A: Reader, Canary and Site

1. **Reader** to [[ARCHITECTURE]] §11, with hyparquet's `useOffsetIndex` for `detail` ([[ARCHITECTURE]] §11.1) and `usePageIndex` for `links`.
2. **Links** resolve through `links` ([[ARCHITECTURE]] §10.1).
3. **Canary** ([[ARCHITECTURE]] §10.3.5), run by the publish job against the uploaded candidate.
4. **Contract test** ([[ARCHITECTURE]] §15, item 5), run on the first engine-built release; F0 and the hand-built fixture serve development until then.
5. **Saved copies** ([[ARCHITECTURE]] §11.5).
6. **Dates:** the document date and capture date in list rows, so same-filename editions read apart; on the document page, the labels of [[ARCHITECTURE]] §11.6.
7. **Recoveries** ([[ARCHITECTURE]] §11.5; [[DATA-MODEL]] §8.1), each on the page the attachment rule gives it.
8. **Sources:** where the document was published and which page listed it, from `sources`.
9. **Connections** (phase 2, except hearing keys and versions): filter by hearing, bill, member and witness, and sort by document date; a hearing's witnesses with what each submitted, its status, sittings and recordings; a document's other versions; a member's terms, committees, appearances and documents; a committee's current roster, hearings and documents; a bill's title, sponsor, status, hearings and documents; link out to the GPO record, the bill and the member.
10. **Removed by review** ([[DATA-MODEL]] §7.9).
11. **Speed, measured then fixed:** measure startup, search, detail and heap once on real phones and desktops against the first engine-built release, then write those targets into the canary and contract test. F0 gives provisional numbers for development.

**Done when:** the site loads F0 locally on desktop and in a phone-sized profile, and the canary passes against F0 in under a minute.

### 6.2 Track B: Raw-Writer Components

These components survive, so they are bound now.

0. **Clean the older receipts, once, before `receipts/` is locked**, by the patterns of [[DATA-MODEL]] §5.2. The one-off rewriter is built and qualified on scratch copies of all 2,289 receipts, with zero matches left; the owner confirms the two patterns from its scan report, patches and drains the old writers, then runs it live and locks `receipts/` by the procedure in `docs/measurements/engine-first-20261027/b0/`.
1. **Bucket lock** (owner), per prefix, in §4 item 1's order.
2. **Fetcher, receipt writer and archive expander** to [[ARCHITECTURE]] §7.1–7.2 and [[DATA-MODEL]] §5.2, proven by their contract suites.
3. **One body store.**
   - Write the refusal matrix first, as the body store's contract test: a write that is not create-only under `bodies/`, `receipts/` or `provenance/`, or a receipt line with a credential parameter in a recorded URL, is refused before any I/O.
   - Then bind one body store with an R2 adapter and a local-disk adapter, and route every raw write through it, including the writers that lay out bodies themselves.
4. **Ingest policy set once,** where capture builds its store. The raw-intake exclusion gate is deleted.
5. **Body existence by key** ([[ARCHITECTURE]] §7.1), never by an index lookup.
6. **Code identity for receipt writers and recovery imports:** the commit (HEAD of a clean tree) plus the SHA-256 of `uv.lock`, refusing uncommitted application code.
7. **Recovery importer:** reconcile `accepted.json` with the receipts, so recoveries become provenance records the model reads, each with its kind.
   - New imports write date-shaped receipts with their recovery category, and provenance, through the receipt writer and the body store, with no guards or upload loop of their own.
   - Its records and B8's are staged where the model reads them during E4's parity, and are written under `provenance/` once it passes.
8. **Review recorder:** in phase 1, one script writes the 86 published assistant reviews of document kinds as `kind_override` records on their files' link keys, with the assistant as reviewer, and writes any new review as a provenance record ([[DATA-MODEL]] §5.3, §7.9); the review forms that record verdicts come in phase 2.
9. **Raw verifier** ([[ARCHITECTURE]] §7.4, §10.3.7), in the maintenance job, joining to the old capture index until D1 exists. Its first run records the listing baseline ([[DATA-MODEL]] §5.3), checking each older body's listed size against its recorded stored size (from the receipts, else the old index for the 364,193 bodies, nearly all Senate captions, whose receipts record none; [[ARCHITECTURE]] §7.4); it then runs weekly.
10. **The one-time full re-hash** (phase 2; [[ARCHITECTURE]] §7.4), after B13, skipping keys whose record has `sha256_verified` true.
11. **A ratchet test:** no test-only branch or test-only input substitution may appear in a surviving component; tests inject adapters instead ([[ARCHITECTURE]] §15, item 7).
12. **Owed while the old capture path runs,** which skips the upload of any digest its index holds: B9's first run also reports index rows whose object is missing, and they are repaired; wrong `stored_sha256` rows are repaired in place; and the daily capture is confirmed to write correct values. These matter only until the switch.
13. **Uncompressed copies of older gzip PDFs** (phase 2; after B1 and B3), by the PDF copier of [[BINDINGS]] §3.1. Running it before B10 saves B10 about 365 GB of reads.
    - **Candidates:** older `.gz` bodies that phase 1's `sniff` reads as `pdf`. Each whole read checks the bytes against their key, recording a mismatch and going on, and re-checks the end marker; the copy's verification record carries the result, which the model reads ([[DATA-MODEL]] §7.3).
    - **Size:** the largest raw write in the plan, so the lock and the refusal matrix come first: about 260,175 uploads and 403 GB once decompressed (about $72 a year of storage under the lock).
14. **Meeting fetches through the fetcher** (phase 2) like every other fetch: the Congress.gov meeting API, the House meeting and witness-list XML, Senate committee hearing pages and the meeting inventories; committees come from spicy-regs ([[ARCHITECTURE]] §7.2, §8.5; [[PHASE-2]] §1.1–1.2).
    - An incremental relist is keyed by its API endpoint and time window, and the window advances only when every page through the last has a good fetch, so a partial run repeats it; the old pending-state path goes only after S2's later-page-failure fixture passes.
    - Once it runs, the weekly job and capture's inventory seeds stop; their records are already in raw (B15).
15. **The weekly meeting job's records into raw** (phase 1, first; [[ARCHITECTURE]] §7.2): each run also writes every source record it saves as bodies and `mode = fetch` receipts at the snapshot's real time ([[DATA-MODEL]] §5.2), through the existing raw writer, keeping its branch as it is. The rescued batch (§1) is imported once the same way, with `mode = fetch` and its original snapshot times; only its run ID enters the import-run registry, so the model does not treat those times as capture dates ([[DATA-MODEL]] §7.4). Its runs pause with capture during B0's window. B14 replaces it.

**Done when:**
- every weekly run since B15, and the rescued batch, is in raw;
- every older receipt is cleaned and verified;
- the refusal matrix passes;
- the lock is on all three prefixes;
- every older body has a verification record, a listing baseline at least.

### 6.3 Track C: Engine

**C0, first moves on engine main** (beside the smoke check): the C0 cleanup of [[BINDINGS]] §3.3. The engine's digest for every runner OS, Linux included, is recorded and checked as [[ARCHITECTURE]] §12 says.

**Then the capabilities of [[ARCHITECTURE]] §13, C*n* being its item *n*, each with its contract test:**

| # | Capability | Contract test |
|---|---|---|
| C1 | Multi-input SQL jobs | A job joining two tables, a file and a receipt holding a type conflict, read whole with the value nulled and its raw line kept; a partition filter visible in the Iceberg scan |
| C2 | Table operations | Guarded commits that fail rather than rebase, three retries, two ingests of the same receipts leaving one copy of each row, and drop with purge, on local tables; the smoke check (§5.1) on Basin |
| C3 | Deterministic export (spicy-stack ss-iwqu) | Phase 1: byte equality across reruns and input orders on the pinned runner class and limits; phase 2: across threads, batch sizes and a forced spill; after a row group's first view through the reader's byte cache, a `detail` view is one round trip |
| C4 | Connected components (ss-6jg6; phase 1 without the dense IDs) | D2's real graph within its heap budget, labels equal across threads and input orders; a refusal test |
| C5 | Streaming I/O | Request counts, peak memory, and no multipart upload or read-back, in a test |
| C6 | Bounded resources | A join at the pool limit fails clearly; D2's build sizes on real links; every hash-join build `EXPLAIN` shows is the smaller input and carries no wide column |
| C7 | Thin interface | The model's export as a job spec |
| C8 | URL, filename and JSON functions (ss-7qz3, ss-e53d, ss-1pg7) | The WHATWG URL test suite and golden vectors from today's fetcher's URL handling and its filename code, for strict-UTF-8 percent-decoding and the RFC 6266 name; `json_array` against Python `json.dumps`; `url_key` timing on the real links |

**Not needed any more:** the lifecycle store's commit requirements, lifecycle-store compaction on R2, copy-on-write measurement and insert-if-absent. Close them unless another consumer needs them.

**Done when:** the model's export runs as a CLI job spec (C7) from Basin tables on the smallest runner (`ubuntu-24.04`, 4 vCPU, 16 GB) and passes C3's test; the full export closes with E.

### 6.4 Track D: Lake Producers

Each producer is built to [[ARCHITECTURE]] §8 and [[DATA-MODEL]] §6.

1. **Captures ingest:**
   - backfill the narrow phase-1 index ([[DATA-MODEL]] §6.1) from the complete pinned original gzip receipt inventory, including non-date segments, through the native JSONL/gzip reader rather than the historical Parquet counter ([[ARCHITECTURE]] §7.2), through the existing incremental capture CLI in whole-receipt batches sized by uncompressed bytes and list items; run the heaviest first in separate OS processes with one idempotent Iceberg commit per batch and one source read per receipt. Keep receipt-local source guards mandatory in each batch, then gate the unpublished generation on whole-table public constraints, exact receipt coverage and independent source counts, and prove one-shot/batched equality on about 200 representative whole receipts, including the largest House, Senate and YouTube lines and required shapes under an explicit one-shot byte cap, before downstream reads;
   - the backfill restores the HTTP status on the about 37,000 bodiless lines that record one (`http_status` or `status_code`; `capture_status` and `meetingStatus` are not HTTP statuses);
   - it maps a fetch time from every receipt shape: 522,448 rows in dated receipts have no time in the snapshot, and 500,689 of them carry one on their own entry or line;
   - the rebuild-equivalence test;
   - **compare with the pinned old capture index** (3,909,134 rows) on receipt-derived columns, with written transformation rules for the expected differences:
     - statuses restored on bodiless lines;
     - the 5,587 lines of the 2026-10-15 recovery run read as recoveries rather than fetches;
     - the final response's completeness (per-attempt completeness stays in raw);
     - `stored_md5` and `stored_suffix` new, `stored_sha256` gone.
     - new-only rows from record-list items the old index collapsed: source evidence must prove the list and the distinct item's ordinal; count and report those rows as expected. Unproved new-only rows remain owner gates.

     A row that exists only in the old index is a fact raw does not hold, and it blocks the switch until the owner decides (§8).
2. **Parsers,** written in S1, appending through the engine, each body read once through the existing adapter: remote reads use captured stored-MD5/size-pinned ranges, declared or known pages use bounded per-batch `R2Store.prefetch_immutable` caches, unknown pages complete through disjoint cached ranges, and every full page's decoded SHA-256 is checked against its body key before parsing; caches stay below 10 GB with at most 64 concurrent GETs and are removed only after their readings commit. Main's 491,699 local readings are a format-comparison oracle, never inputs (counts below come from the pinned index's metadata, before any body read):
   - no read where the writer's facts settle the format: 362,208 captions, 953 playlists and one empty body;
   - one full read of each page body the media type routes to HTML, XML or JSON (288,223 bodies, 4.98 GB), sniffed from those bytes and parsed in the same pass; a body whose bytes say otherwise is sniffed as what it is;
   - a bounded prefix read for the other 384,871 bodies, mostly PDFs and ZIPs, whose media type proves nothing;
   - 673,094 object opens instead of 1,324,479, and a byte floor of 8.0 GB instead of 9.7 GB; page fingerprints and the readings table's size (links and `text_head` included) are measured in the run. There is no PDF parser and no fingerprint parser for now;
   - then the link join and grouping on the real links and fingerprints, every step within the pool limit and scratch ceiling of the 16 GB runner, peak RSS included (C6).
3. **Filename reader:** a producer that runs the filename parser over its work list and appends through the engine; the parser changed since the old catalog, which is its diff oracle.
4. **Meeting parsers** (phase 2; needs B14): one row per input and version, over the meeting-source registry's work list ([[PHASE-2]] §1.2–1.3):
   - Congress.gov records, the 199,156 inline receipt records (18,140 meetings; read once from the four `congress/meetings` receipt files, 77 MB, by their D1 pointers, with `record_sha` computed here) and response bodies alike, and House `committee-meeting` XML, into `meeting_records`;
   - House witness lists, Congress.gov records, Senate hearing page cards and the `mods.xml` records already in raw into `appearance_records`, each witness with its name key and document links.

**Done when:** each phase's lake tables (phase 1: `captures`, `readings`, `filename_readings`) exist with complete backfills at the pinned versions, and both `captures` comparisons pass.

### 6.5 Track E: Model

1. **The rules, written in S** (§5.3). The file-shape list starts from the broader list; the roughly 27k bodies between it and the narrow list (16,775) are sampled before it is fixed.
   - The broader list has 44,047 file-shaped bodies: the narrow list's `.pdf`, `.zip`, `.doc`, `.docx`, `.xml`, `/download/`, `download=1` and `file_id=`, plus `/files/`, `/uploadedfiles/`, `/media/doc/` and more extensions.
2. **The model SQL:** every relation and release file of [[DATA-MODEL]] §7–8, with the invariants of §10 as its test suite, including byte-identical releases from a maintained lake and a clean rebuild after a registry change and after a table rebuilt at a new schema.
3. **Golden vectors** for `source_id` and `document_id`, generated from today's ID code with its compact-JSON serialization and checked in the engine's tests.
4. **Parity against the pinned catalog pair**, the oracle (not F0, which picks one document per shared body), on browser-visible fields, compared many-to-many and keyed by source evidence: the files and URLs each document holds. IDs match today's wherever their inputs match.
   - **Expected, explained changes:**
     - about 615k catalog rows (captions, metadata records, playlists and API responses; [[DATA-MODEL]] §7.5) and the listing pages leave the list;
     - documents lose soft-error and wrapper pages, and about 4,900 lose Senate landing pages, from their body sets, while short real pages and real web pages now count;
     - cut-off copies, damaged PDFs and pages whose reading failed (reported by format and error type) drop out of body sets, and feed pages become listings;
     - the 3,690 recovered files that a real fetch also saved become real bodies;
     - about 2,250 pages saved twice in one fetch (a direct attempt and a provider retry) merge by main content, and 999 veterans.house.gov pages from the End of Term archive gain their webharvest.gov copies as attached recoveries;
     - document kinds now also come from the publisher's link labels where the filename gives none;
     - a file's name comes from each capture row, download header first: about 95,000 files carry a download-header name and change `source_id`, and a body offered several names keeps one source file per name in one document;
     - about 460,000 rows today named only from `download_state` are saved-text duplicates of exact copies at the same URL, and collapse into their twins; where a URL's copies differ (532 URLs), the exact copy becomes the saved file;
     - about 34,100 GovInfo ZIP groups and about 560 same-stem groups merge; the old catalog's about 19,500 multi-format same-stem groups were mostly (about 17,400) PDFs paired with one docs.house.gov 404 body saved at `.xml` URLs, a placeholder that is no good fetch;
     - `document_id` keeps today's formula, but its inputs now include real web pages and untyped bodies;
     - link-label coverage changes, because labels now come from saved pages; labels that came only from scraper records inside receipts are their own cause;
     - capture dates change where receipts lack times.
   - **The comparison reports by cause, not by document:** each known cause has a checkable predicate, its count and a few reviewed examples, and every difference that fits no known cause is listed separately. Only that last group needs reading one by one.
   - **Classify each unexplained difference:** a rule change (fine, recorded with the rule); an old-pipeline error (the new model wins); or a fact that exists only in derived tables (a blocker, §8).

**Done when:** every known cause has its predicate, count and examples, every unexplained difference is classified with no blocker left, and the model runs as a CLI job on the smallest runner.

### 6.6 Track F: Publish Job, Capture Scheduler and Switch

1. **Workflows** ([[ARCHITECTURE]] §12): the capture job; the publish job, backfills and the maintenance job, with its monthly table rebuild ([[ARCHITECTURE]] §8.6), in one CI concurrency group. The disabled viewer workflow and its 30-minute cron are deleted.
2. **Capture scheduler:** capture reads `url_state` from the live release, including its queue of linked-but-unfetched URLs, stops reading the raw index and drops its replay mode; until B14 it also takes the weekly job's inventory files as seeds.
   - Each run works within a request, byte and spool budget sized from the first engine-built `url_state`'s due rows (1,298,420 URLs today; the old capture caps a run at 20,000), taking the queue first, which holds the wrapped files (*est.* 8,800 never fetched), then the cut-off URLs (62 to 64, whose cut-off copies stay in raw), then the oldest `next_attempt_at`.
3. **The committee explorer** (phase 2) reads meeting and witness records from the lake and committees, members and rosters from the pinned spicy-regs generations ([[ARCHITECTURE]] §8.5), not from the fetchers' state files.
4. **Pins:** publish and the maintenance job keep the receipt-key lists and, in phase 2, `pins/spicy-generations.json` ([[ARCHITECTURE]] §10.3.4, §10.3.7). The spicy-regs side (its retention reading that list, `nomination_id`, the nominations backfill, and reading the archive's releases instead of capturing meetings) is spicy-stack ss-vhi2.
5. **Delete what is bound to nothing,** one PR per group as [[BINDINGS]] §6 lists them, measured again at cut.

The first engine-era release may be seeded by an engine SQL conversion of the pinned live v5 catalog `596f08fa`, with its seed origin and input hashes recorded; the raw rebuild replaces it after its E4 comparison passes. This seed is display-only: its `url_state` does not drive capture, and the old capture and update workflows continue until the rebuild cut-over.

**Phase-1 exit checklist.** The switch is done when all of these hold; phase 2's additions are in [[PHASE-2]] §4.1:
- tracks A to E meet their done-when;
- the cut-over ran in order: old capture disabled; a final ingest and publish; the flip; the new capture's first run on the target writers, whose `stored` lines carry MD5s matching their ETags and every line its stored suffix;
- the explorer serves an engine-built release, and the reader opens saved files, alternates and recoveries from it;
- the canary and contract test pass on that release, with the speed targets set on real devices against it (A11);
- C3's export is byte-identical across reruns and input orders on the pinned runner class and limits;
- a failed canary is shown to leave the previous release live;
- capture runs from `url_state` with no raw-index read, and every cut-off URL has a complete copy or a recorded reason;
- the old workflows are gone, except the weekly meeting job until B14, and the deleted line counts are recorded.

## 7. Parked

- **news_lake** keeps the DocSpec backend and the engine's lifecycle store. No work until it adopts the three layers.
- **The freeze:** no browser or engine performance work beyond this plan until there is a user or a measured failure on real data.
- **Committee explorer and weekly retention onto incremental tables:** the approach conflicts with the design. Re-scope it before starting.
- **Considered, not chosen,** so not re-proposed without new information: showing the original link's last status (36,768 documents' URLs last returned 404 or 410), showing saved-file size (2,467 files over 50 MB), and saving resolved links between publishes (revisit only if a measured reprint shows link resolution is the slow step).
- **The MCP coverage tasks** (`docs/youtube-coverage/congressional-explorer-mcp-data-coverage-tasks.md`, a proposal): what the target covers is in [[PHASE-2]] §4.3.
- **Parquet variant for the folds:** revisit when all three hold:
  - an iceberg-rust release writes variant through its Parquet writer (0.10.1, the pinned release, has none; 0.11 is expected to add it);
  - Basin Catalog accepts format-version 3 tables;
  - DataFusion core or a maintained crate can query variant.

  The candidates are nested, mixed-type readings such as Congress.gov API JSON and MODS or meeting XML trees.
- **Structured transcripts:** the captions and subtitles are held in raw and, in phase 2, listed per recording (99% of Senate meeting videos in the 118th–119th Congresses have them); turning them and the printed transcripts (`pdf_text`) into timed speaker turns is full-text work. Such a reading can also name witnesses a source left unnamed, as attributes that never move a `witness_key` ([[PHASE-2]] §2).
- **Committee markup votes:** spicy-regs has amendments and committee activities but no committee vote tallies; the House committee repository is the source if one is needed.
- **Full-text extraction of every PDF:** one later read of about 403 GB into `pdf_text` ([[DATA-MODEL]] §6.6). It gives page counts and text fingerprints for every PDF, which makes dedupe across sites cheap to revisit.

## 8. Uncertainties and Tests

Each row names an unknown, the step that settles it and what it decides, and closes only with its measurement. The widest is the model (track E), bounded unless parity finds facts only derived tables hold. Phase 2's rows are in [[PHASE-2]] §4.2.

| Uncertainty | Settled by | Decides |
|---|---|---|
| The ingest mapping reads every older shape: 2.96M of 3.9M rows carry no outcome, 1,420 receipts mix types on a path, one line is 188 MB | D1's comparison with the old index | The outcome and mode table, and any fact that exists only in derived tables (the owner records it as provenance or accepts losing it) |
| The rules give the right documents on real data, not only on fixtures and proxies | S1 on real slices; the labeled sample (S2) | Rule changes, the page thresholds and the final file-shape list |
| Re-packaged editions join the wrong XML | S2's edition count | The owner widens fingerprint candidates, or not |
| How many links pages hold (*est.* 4.2M, from 80 pages) and how large the link join is | D2's link backfill | The link-join budget (C6) |
| The 33,369 never-sniffed PDF candidates are PDFs | Phase 1's `sniff` | The copy count |
| No older body beyond the 61 known has a multipart ETag | B9's first run | Nothing, unless the count changes |
| The numbers in the specifications reproduce: each review round found 10–20 of about 370 wrong | Each load-bearing number re-derived from its committed script before a rule relies on it | Corrections in place |
| Speed and heap targets on real phones and desktops | A11, on the first engine-built release | The canary's and contract test's thresholds |
| Whether `list` with titles fits the phone heap budget (*est.* 17–30 MB more; 46% of documents have a publisher label) | A11 on the first engine-built release; F0 gives a provisional budget | Titles stay in `list`, or move back to `detail` |
| How many House event pages only the committee explorer's POST calendar API finds, which capture's scope drops ([[BINDINGS]] §3.1) | A count from the explorer's discovery before the switch | Whether capture needs that API as a seed |

## 9. References

**[ARCHITECTURE]**
: *Congressional Document Archive: Architecture.* Editor's Draft, 2026-10-24. `docs/engine-first-architecture.md`.

**[DATA-MODEL]**
: *Congressional Document Archive: Data Model.* Editor's Draft, 2026-10-24. `docs/engine-first-data-model.md`.

**[BINDINGS]**
: *Congressional Document Archive: Implementation Bindings.* Note, 2026-10-25. `docs/plans/bindings-20261025.md`.

**[FIXTURES]**
: *Congressional Document Archive: Acceptance Fixtures.* Note, 2026-10-26. `model/fixtures/manifest.md`.

**[PHASE-2]**
: *Congressional Document Archive: Phase-2 Annex.* Note, 2026-10-28. `docs/plans/phase-2-annex-20261028.md`.
