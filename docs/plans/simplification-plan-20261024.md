# Simplification plan: congressional-tech and docspec-rs

Revision 6, 2026-10-24. It implements `docs/engine-first-architecture.md` (revision 9)
and `docs/engine-first-data-model.md`, and replaces earlier revisions of this file (in git
history). Evidence: `docs/reviews/2026-10-24-ticket-audit/` (the audit, with measured line
counts) and `docs/reviews/2026-10-24-design-review/` (six design reviews). Below, "design
§n" cites the design document and "data model §n" its companion.

## 1. Strategy: build beside, switch, delete

Revision 1 refactored the old pipeline piece by piece. The design replaces most of that
pipeline, so refactoring it is wasted work. This plan builds the target beside the old
pipeline, switches publishing to it, and deletes the old layers whole.

- **What survives:** fetchers and raw writers, recovery imports, review tools,
  `house-naming`, the site and docspec-rs. Changes to these happen now.
- **What goes:** the Python catalog (incremental and rebuild), the raw index and its
  routing, the viewer-publication journal route, the v6 preparer, and the shims around
  them. They get no new work and are deleted at the switch.
- **Until the switch,** the old capture job keeps writing raw data and reading the raw
  index. It gets raw-safety fixes only. Its whole-leaf index rewrites (revision 1's E1
  cost) continue until then; that is accepted.

## 2. Constraints

**What must survive:** objects in R2 `congressional-tech-raw` under `bodies/`,
`receipts/` and `provenance/`. Everything else can be rebuilt, and nothing uses it yet.

**Owner decisions (binding):**

| # | Decision | Effect on this plan |
|---|---|---|
| 1 | Durable per-step commits | Each pipeline step commits once (one Iceberg append). The engine's deferred-commit mode is reverted (C0). |
| 2 | news_lake keeps the DocSpec backend | Parked: no work until news_lake adopts the three layers (design §14). |
| 3 | Publishing moves to export-pins | The release pipeline (design §6.4) is its finished form. The journal and resume route is deleted (F3). |
| 4 | Raw protection is a bucket lock; one bucket | Step B1. |
| 5 | `r2.dev` stays open | Every key is public, so a path allowlist on the custom domain protects nothing; decision 39 deletes it. |
| 6 | Engine first | The target is built in docspec-rs; congressional-tech keeps no code that overlaps it. |
| 7 | Documents only | No per-copy pages and no `sources` file. Per-copy filename readings stay in the lake. |
| 8 | Links point at a file; 16-hex keys | `links.parquet` maps every real file's key to its document (amended by 27: every real body is in exactly one document). F0 uses it, so links survive the switch. |
| 9 | Desktop and mid-range phones | The reader decodes `list` column by column; the canary and contract test enforce a heap budget. |
| 10 | A document is one distinct content; its page links its newest real file (amended by 31 and 32: all formats are one entry, and the PDF comes first) | Text fingerprints only where one URL gave 2+ complete files (D2); the rule is part of E1. |
| 11 | hyparquet stays in the browser | Page reads through offset indexes (A1, C3). |
| 12 | Older gzip PDFs get uncompressed copies; other older bodies unpack in the browser | B13 and A5. |
| 13 | Only real files count as a document's files: a real fetch (not a recovery import), complete, 2xx, non-empty, not a placeholder (amended by 24 and 26: record role `document` and any content format, with API responses defined by an endpoint list) | Receipts record the sniffed format (B2); older bodies without one get a ranged sniff (D2); the rule is part of E1. |
| 14 | No early launch: the explorer waits for the engine-built release | F0 is the reader's fixture and the parity oracle only. |
| 15 | Re-fetch the 62 URLs that only have a 64 MiB cut-off copy; a size-limit outcome means retry | B2 and B14. |
| 16 | Investigate the Oct 15 recovery run | Done: its 5,587 lines are recovery imports, not bad downloads, so no raw correction is needed. Captures keep the import fields (D1); imports are never real files (E1). |
| 17 | Show capture dates | A6 and E2. |
| 18 | Show every recovery, labeled by kind with its evidence | A7 and E2: recovered copy, excerpt from the official hearing record, or the named official substitute. Nothing poses as the original file. |
| 19 | HTML counts as a web page only if the link is page-shaped and the page shows no generic error signs | E1, with the signals from the HTML reading (D2). |
| 20 | Capture dates say what we know: a real fetch date, "in our archive since Sept 29, 2026", or "not recorded" | A6 and E2; undated rows sort after dated ones. |
| 21 | `document_id` keeps today's body-set formula | E3's golden vectors; links don't depend on it. |
| 22 | No PDF reading for now; full-text extraction of every PDF comes later | D2 has no PDF parser; the full-text job is parked (G). |
| 23 | Keep two releases: the live one and the last good one | F1's weekly job; the reader reloads on a 404 (A1, A3, A4). |
| 24 | The explorer lists real documents only: at least one real file or recovery, about 0.6–0.7M | Record roles in D2; the listing rule in E1. |
| 25 | Show link context: the page that linked each copy, and the link's label | `page_links` in D1; occurrences in E2; A8. |
| 26 | Any content format counts, including Word, web archives and images | The real-file rule in E1. |
| 27 | Identical real web pages are one document | Same-body edges include HTML (E1); every real body is in one document. |
| 28 | The text check reads PDF text for its candidates only (about 297 bodies) | The `fingerprint` parser in D2; the every-PDF pass stays parked (G). |
| 29 | Every link join normalizes the URL with `url_key`: unwrap redirect and archive wrappers, strip only trackers and page state on known hosts, keep and sort the rest | E1 (data model §3.0). |
| 30 | No per-view byte budget; the heap budget stays | A3 and A4 check heap only. |
| 31 | One entry for all formats of a document | A `same_rendition` edge in E1, from publisher groups in `page_links` or same-stem files; E4 reports the merges. |
| 32 | PDF first: the page offers the PDF and lists other formats as alternates | The saved-file rule in E1; A5 shows alternates. |
| 33 | Link documents to their meetings, from URLs and linking pages | `meeting_ref` in E1; A9 lists every document for a hearing. |
| 34 | A typed document date for sorting and filtering | `document_date` in D3 and E2; A6 and A9. |
| 35 | Official record keys as typed fields, for link-outs | GovInfo package, bill keys and Bioguide IDs in D3 and E2; A9. |
| 36 | Show committee names, not codes | `committee_records` in D5; the mapping in E1; A9. |
| 37 | No schedule or effort planning (replaces the 11–20 week estimate) | §3, §4 and §8 order the work by dependency only. |
| 38 | Meetings get titles: `meetings.py` fetches through the raw writer into `meeting_records` | B16, D6 and E1; hearing pages show title, date, type and committee (A9). |
| 39 | Delete the custom-domain path allowlist and its tooling; keep CORS, cache headers, CSP and the `?filename=` rule | F3. |
| 40 | Raw stays on Cloudflare R2 only, with no second copy elsewhere | Design §4.4 states the failure model. |
| 41 | Set speed targets after measuring | A11 measures F0 on real devices, then fixes the targets the canary checks. |
| 42 | Editions stay apart: no format grouping at addresses with several editions | E1 (S), with adversarial fixtures. |
| 43 | Files inside ZIPs are judged and named by their own path | E1 (S); data model §3.1–3.2. |
| 44 | Keep every value of multi-valued facets | D3 and A. |
| 45 | Hand-check a labeled sample to measure the classification rules | S. |
| 46 | A hidden document's links show a "removed by review" note | E1 (S) and A10. |
| 47 | A reviewer's "duplicate of" merges two documents | E1 (S). |

Also answered on Oct 24: no exclusion list will exist; wrong `stored_sha256` rows are
repaired in place; recovery imports refuse uncommitted code.

**Done on Oct 24** (commit `54a68ac7`, the audit README and the design):
- P1: deleted `delete_gzip`.
- P2: hosted setup refuses an engine revision other than `QUALIFIED_DOCSPEC_RUNTIME`.
- P3: the capture schema carries `stored_sha256` from the receipt and never derives it.
- P5: 12,431 of 24,028 recoveries existed only in `accepted.json`; a write-once backup is
  in `provenance/recoveries/`.

**Owner action pending:** P4, the bucket lock (ct-1l1h).

**Rules for every step:**
- One conceptual move per PR. Tests that pin behavior land before code moves. Behavior
  changes go in their own PRs.
- Run checks only through the project runners: `.venv/bin/python scripts/dev.py test <lane>`
  and docspec-rs `scripts/check`. Never use a tool from `PATH`. Say this in every agent and
  reviewer brief.
- Work in a separate worktree and venv. The primary checkout backs live recovery jobs.
- Report before and after `wc -l` in every PR that deletes code.
- Each step names its evidence: a test, or a measurement committed under `docs/`.

**Raw check (R-check):**
1. Before and after each merge that touches raw writers, list `receipts/` and `bodies/`
   read-only. Every earlier key is still there with the same size and ETag; only additions
   are allowed.
2. Every receipt-referenced body exists.
3. After P4: read the bucket-lock rules back after any infra change.

## 3. First: protect, measure and pin down the rules

The work starts with the owner's bucket lock and the cut-off re-fetch (B14). Then come two
measurements that decide how much engine work there is (M1, M2), and the semantic
checkpoint (S), which writes the rules the measurements and the engine depend on. After
those come F0, C0 and tracks A and B.

**M1. Basin Catalog commits under maintenance** (docspec-rs).
1. **Conflict retry.** Plain appends already send their commit requirements; ss-om9p
   concerns the engine's lifecycle store, which the target drops. So M1 tests what is new:
   an append that races a Basin compaction recomputes its work list and lands, and two
   ingest runs on the same receipts leave exactly one copy of each row (design §5).
2. **Manifest growth.** Append 400 day-sized batches (about 315 KB each) to a scratch
   table with Basin compaction and snapshot expiration enabled. Count data files and
   manifests in the current snapshot before and after maintenance runs.
3. Measure or remove the unmeasured 2 MiB file cap (ss-n68e).

Decides: Iceberg stays (manifests bounded), or the lake tables move to dated Parquet with
an `If-Match` manifest (design §13). The fallback changes the scope of C1, C2 and D.

**M2. Wide joins and grouping in a throwaway DataFusion harness.** The engine can't run
the full export until C1, C3 and C4 exist, so this measures with a short standalone
DataFusion program instead, using S's draft grouping rule.
- Inputs: the pinned Oct 19 snapshot (captures `db033173…`, catalog generation
  `596f08fa…`), including today's filename readings.
- Run the model's joins, including filename readings, the folded `detail` and the 4.7M
  `occurrences`, and report the size of every hash-join build.
- Group the real graph with the design's rule. Record time, peak memory and the largest
  components.
- Run on `ubuntu-24.04` (4 vCPU, 16 GB), the smallest runner class.

Decides: the size of track C, and whether DataFusion handles the wide joins within the
pool. The harness is deleted afterwards. Byte-for-byte determinism becomes C3's acceptance
test.

**S. The semantic checkpoint** (before C). E1 is written first, here, because M2 and the
engine work depend on it:
- the grouping rule as SQL, with adversarial fixtures: a PDF replaced while its XML stays,
  historical pages linking both, archive members, a recovery-only link that later downloads,
  a reviewer's merge and hide;
- a hand-labeled stratified sample of a few hundred files (decision 45), measuring how often
  the page-shape, error-sign and placeholder rules wrongly include or exclude a file;
- a check that every rule can be computed from raw, with nothing borrowed from the old
  derived tables.

**F0. The first release, converted from the pinned catalog** (congressional-tech).
- Convert the pinned catalog pair into the release format (design §6.2), with the final
  writer settings: offset indexes, the folded `detail`, `links` keyed by body prefixes.
  Use the engine's RunSpec where it can. The CS300 measurements show the shape:
  `measurements/build_list.py` built `list`, `ids` and `detail` in 24 s, and
  `size_occ_captures.py` built `occurrences`.
- This release is the reader's fixture (track A). Its manifest records that it came from
  the pinned catalog. It does not go live (decision 14).
- **It fills what it can:** meeting IDs from URLs, document dates from the old metadata,
  link labels from the old occurrences, and committee names from today's committee file.
- **It can't show** format groups, meeting titles or the new recovery kinds, so a small
  hand-built fixture release covers them: one document with PDF and XML alternates, one
  titled hearing, one of each recovery kind and one hidden document. The contract test runs
  both.
- **It assumes nothing unique about old bodies:** 141,762 body keys appear in several old
  documents, so F0 resolves each link key to the first document in list order. It stays a
  reader fixture; correctness is checked by E4's comparison, keyed by source evidence.
- The converter is a migration tool. It is deleted at the switch.

## 4. Tracks

| Track | What | Depends on |
|---|---|---|
| A | Site reader and canary | F0 and the hand-built fixture |
| B | Raw writers and protection | P4 (owner) for B1 and B13 |
| C | Engine capabilities | M1, M2, S |
| D | Lake tables and backfills | C2, B2, B16 |
| E | Model SQL and parity | S, C1, C3, C4, D, F0 |
| F | Switch and delete | A, E |

There is no schedule (decision 37); the tracks run in dependency order, and A and B can run
beside C.

### A. Site reader and canary

1. **A reader module for the release format:** pointer → manifest → `list` in a Web
   Worker, decoded column by column into arrays and dictionary codes; `detail` by row with
   hyparquet's `useOffsetIndex`, its offset index fetched once per session and cached;
   `links`; `occurrences`; shards. No DOM dependency. Accepts the current and previous
   `schema_version`. On a 404 for a release file, it re-reads the pointer and reloads,
   since only two releases are kept (decision 23).
2. **Links** carry a 16-hex file fingerprint and resolve through `links` to whichever
   document holds that file now.
3. **The Node canary** (design §6.4): a script the publish job runs against the uploaded
   candidate, including a heap budget for a mid-range phone and the 404 reload.
4. **A CI contract test:** the real site in a headless browser against F0 and the
   hand-built fixture release, within the heap budget. It moves to a release built from a
   fixed sample of real receipts once track E exists.
5. **Saved copies:** link the document's saved file, PDF first, with its other formats
   listed as alternates. Older gzip PDFs open their `.pdf` copy
   (B13). Other older gzip bodies are fetched, unpacked with `DecompressionStream`, and
   opened with the media type from `detail`. Those over 100 MB (579) are offered as a
   labeled compressed download instead.
6. **Capture dates:** the first-captured date in list rows, so same-filename editions
   read apart, and the first and last capture dates on the document page. Labels say what
   we know: "Captured <date>", "In our archive since Sept 29, 2026 (original capture date
   not recorded)", or "Capture date not recorded" (design §6.2).
7. **Recoveries:** each one on its original link's page, labeled by kind (recovered copy,
   excerpt from the official hearing record, or the named official substitute), with its
   recovered URL, match basis, evidence digest and identity note, and a link to the
   recovered file.
8. **Link context:** "where each copy was seen" names the page that linked it and the
   link's label (decision 25).
9. **Meetings, dates and record links:** filter and sort by document date; list every
   document for a hearing under its title, date, type and committee; link out to the GPO
   record, the bill and the member (decisions 33–35 and 38).
10. **Removed by review:** a hidden document's link opens a note with the reason and date
    (decision 46).
11. **Speed, measured then fixed** (decision 41): measure startup, search, detail and heap
    on real phones and desktops with F0, then write those targets into the canary and
    contract test.

**Done when:** the site loads F0 locally on desktop and in a phone-sized profile, and the
canary passes against F0 in under a minute.
**Replaces at the switch:** `catalog-v6.ts` and its v6 and ExportPin branches, the v6
paths in `worker.ts`, and `verify-live-publication.mjs`. Keep `cache.ts`,
`withVerifiedJson` and `startup.ts` (ct-tdsx) where they fit.

### B. Raw writers and protection

This code survives, so it is fixed now.

1. **Bucket lock** (owner, ct-1l1h) on `bodies/`, `receipts/` and `provenance/`. This is
   the single most protective step in the plan, and it gates B13.
2. **Receipts and bodies to the design (§4.1–4.2):**
   - every receipt line records the format sniffed from the body's first bytes, beside the
     server's media type and the HTTP status;
   - `stored` receipt lines record the stored MD5 and size;
   - new compressible bodies are stored with `Content-Encoding: gzip` and the original
     `Content-Type`; new PDFs are stored as-is;
   - one create-only PUT per body with Content-MD5, never multipart;
   - a 412 is recorded as `unchanged`, with no HEAD and no comparison (ct-klql);
   - the fetcher spools each body to a temporary file and never cuts one off; a
     `size_limit` or `request_failed` outcome is retried;
   - receipt keys use the UTC write date;
   - lines carry the run ID and writer identity, one entry per referenced body with its
     path inside an archive, and the links found with their labels; they drop the
     provider metadata, duplicated headers and old raw-index row, so a line is about 1 KB
     (data model §1.2).
3. **One namespace policy for raw keys.** Write the refusal matrix first: every writer
   (`R2Store.put`, `put_file`, `put_pdf_body`, `AsyncBodies.put`, `LocalStore.put`) refuses
   a write that is not create-only under `bodies/`, `receipts/` or `provenance/`, before
   any I/O. Then delete the `immutable` flag.
4. **Ingest policy set once,** where capture builds its store. Delete the exclusion gate
   (`raw_storage.py:75-236`, 162 lines).
5. **Body existence by key:** a create-only PUT and its 412, plus an in-run set. No index
   lookup (ct-allr).
6. **One body layout.** The hand-written layout writers call `put_body`:
   `committee_explorer/parquet.py:406-428`, senate `seed_fetch`, and the e2e harness.
7. **Code identity for recovery imports:** the git tree hash plus the `uv.lock` digest,
   refusing uncommitted changes under `packages/` or `scripts/` (ct-70kc).
8. **Reconcile `accepted.json` with the receipts** (ct-st8m), so recoveries become
   provenance records the model reads.
9. **The weekly maintenance job** (design §4.4): LIST joined to each body's creating
   receipt line, a one-time re-hash of any body with no creating line, the 25-body sample,
   the orphan report and release retention. It joins to the old capture
   index until D1 exists.
10. **The one-time full re-hash** of bodies written before receipts carried an MD5, with
    their ETags recorded under `provenance/verification/`.
11. **A ratchet test:** `PYTEST_CURRENT_TEST` may not appear in surviving packages. Delete
    the raw-adjacent substitution in `raw_storage.py:655-672` now; the rest of the 75
    sites go with the old layers.
12. **Owed while the old capture path runs:** ct-63hg (repair wrong `stored_sha256` index
    rows in place) and ct-j9c4 (confirm the daily capture writes correct values). The
    target reads receipts, so these matter only until the switch.
13. **Uncompressed copies of older gzip PDFs** (after B1 and B3; track A's saved copies
    need them). It is the largest raw write in the plan, so the lock and the refusal
    matrix come first. First fold `migrate_pdf_bodies_to_uncompressed` into
    `backfill_uncompressed_pdfs` (`pdf_backfill.py`), so one path remains. Then run it over
    every older gzip PDF: create-only to `bodies/sha256/<aa>/<sha>.pdf`, with Content-MD5,
    and the decompressed SHA-256 checked before upload. About 261k uploads ($1.20) and
    403 GB once decompressed, about $72 a year of storage kept under the lock; a few hours.
    Copies that already exist return 412 and are skipped.
14. **Re-fetch the cut-off files** (first, in today's capture path): the 62 URLs whose only
    copy was cut off at 64 MiB. The cut-off copies stay in raw.
15. **The Oct 15 recovery run: done, no correction needed.** The Iceberg/Parquet review
    traced `receipts/documents/2026-10-15/download-filename-recovery-all-*`: all 5,587
    lines are `retained_import` recoveries with a synthetic HTTP 200 (5,154 recovered
    copies, 341 hearing-record excerpts, 92 official substitutes). The old capture index
    had flattened them into fetches. What remains is in D1 and E1.
16. **Committee and meeting fetches through the raw writer** (decisions 36 and 38):
    `acquisition/committees.py` and `acquisition/meetings.py` stop writing their own output
    files and fetch through the raw writer like every other fetch.

**Done when:** the refusal matrix passes, the lock is on, one capture run's `stored` lines
carry MD5s that match the stored ETags, every older gzip PDF has its copy, the 62 cut-off
URLs have complete copies or a recorded reason.

### C. Engine capabilities (docspec-rs)

**C0. First moves on engine main** (beside M1). Revert the deferred-commit mode and
delete the dataset-name predicates (ss-pdv0). Both came after congressional-tech's pin, so
nothing depends on them. Hash while writing, and stop HEADing and re-downloading immutable
files (ss-k1f0; this is also C5).

**Then the capabilities in design §9:**

| # | Capability | Evidence |
|---|---|---|
| C1 | Multi-input SQL plans over Basin tables and Parquet files in one context | A plan joining two tables and a file |
| C2 | Append through the REST catalog, with the conflict retry | M1's two tests |
| C3 | Deterministic multi-file export: SHA-256 and MD5 while writing; per-file writer settings, including offset and column indexes, page sizes and row limits, and per-column encodings such as delta-encoded filenames; fixed row counts per row group; unique sort keys; row-range shards | Byte equality across threads, input orders, batch sizes and a forced spill; hyparquet page reads on the output |
| C4 | ConnectedComponents in memory over 32-bit IDs, refusing above a node cap | M2's graph; a refusal test |
| C5 | Streaming I/O: no re-read or HEAD of immutable files | Request counts in a test |
| C6 | Bounded threads, memory pool and scratch; wide folded columns kept off hash-join build sides | A join at the pool limit fails clearly; M2's build sizes |
| C7 | A CLI that runs a declarative job spec and returns a machine-readable result | The M2 export as a job spec |

The engine's current export disables the offset index unless page-index columns are named
(`export/pipeline.rs:687-697`), so C3's per-file settings are required, not optional.

**Not needed by congressional-tech any more:** the lifecycle store's commit requirements
(ss-om9p), lifecycle-store compaction on R2 (ss-1uh5), copy-on-write measurement
(ss-eyhn) and insert-if-absent (ss-jxvn). The target has no engine lifecycle store, no
updates and no news_lake work. Close them unless another consumer needs them.

**Done when:** one CLI job runs the full export from Basin tables, byte-identical across
threads, input orders and batch sizes and with a forced spill, on the smallest runner.

### D. Lake tables and backfills

1. **`captures`** (design §5.1):
   - ingest from date-shaped prefixes only, per family, from the newest ingested date;
   - backfill from all 2,289 receipts (1.08 GB compressed), including the non-date
     segments (`undated/`, `mixed-dates/`: 49 files, 2.2M rows); older receipt shapes are
     mapped in the ingest SQL, with a test sample of each shape;
   - the key is `(receipt_key, receipt_line, capture_index)`, because one line can
     reference many bodies; each row carries `member_path`, so the endpoint is
     `(context_url, member_path)`, and `run_id`;
   - a line with no body still yields one line-only row, and the line's own fields
     (requested URL, time, HTTP status, outcome, mode) are on every row; the backfill
     restores the statuses today's index dropped for 1.04M bodiless lines;
   - recovery imports keep `mode`, `publisher_requested`, the recovery category and the
     original link as columns;
   - **`page_links`** is filled from each line's links (decision 25), with its own work
     list and commit, and keeps each link's `source_xpath` for publisher format groups
     (decision 31); a receipt with no links gets a completion row; a lag shows as missing
     link context, not a failure;
   - the rebuild-equivalence test;
   - **compare with the pinned old capture index** (3,909,134 rows) on receipt-derived
     columns, with written transformation rules for the expected differences: statuses
     restored on bodiless lines, `stored_md5` new, `stored_sha256` gone. A row that exists
     only in the old index is a fact raw doesn't hold, and it blocks the switch until the
     owner decides (open question 1).
2. **`readings`** (design §5.2): one parser and version per media family; partitioned by
   `(parser, parser_version)`; a version is complete when its work list is empty. The scope
   in the model SQL excludes ZIPs and captions.
   - First the `sniff` parser runs once over every older body: one ranged read of its first
     bytes, about 1.04M GETs (about $0.37), under an hour. The real-file rule needs a
     sniffed format and record role for every body (decisions 13 and 24).
   - Then backfill HTML, XML and JSON (about 5 GB). There is no PDF parser for now
     (decision 22).
   - The readings core carries what the rules read: format, record role, title, heading,
     visible-text size, error signals and fingerprint (data model §2.2).
   - The `fingerprint` parser reads only the bodies at endpoints with two or more complete
     real files: 148 endpoints, 297 bodies, 1.4 GB today. For PDFs it extracts the text
     (decision 28).
   The parser functions survive; the adoption machinery around them goes in F3.
3. **`filename_readings`** (design §5.3): a producer that runs `house-naming` over the
   work list and appends through the engine. It also writes the typed `document_date`,
   `measure_keys`, `bioguide_ids` and `gpo_package_id` (decisions 34–35), so the model
   never unnests the field list. Multi-valued facets stay lists (decision 44), and an input
   house-naming can't read gets a status row. Backfill is 7–18 minutes over 1.39M pairs.
4. Enable Basin compaction and snapshot expiration on all six lake tables.
5. **`committee_records`** (design §5.5): the JSON parser reads each committee API
   response once, with a completion row for a response with no committees (needs B16).
6. **`meeting_records`** (design §5.6): the JSON and XML parsers read each meeting response
   once, with completion rows (decision 38; needs B16).

**Done when:** all lake tables exist with complete backfills, and both `captures`
comparisons pass.

### E. Model SQL and parity

1. **The grouping rule, written in S** before the engine work, as SQL with a short
   rationale:
   - which responses are real files (decisions 13 and 26): record role `document`, any
     content format, and the two web-page checks (decision 19). The link-shape patterns
     are an exact list of regular expressions: start from the broader list (adding
     `/files/`, `/uploadedfiles/`, `/media/doc/` and more extensions, 44,047 file-shaped
     bodies), sample the roughly 27k between it and the narrow list (16,775), then fix it;
   - which documents are listed (decision 24): at least one real file or one recovery;
   - recovery imports are evidence for their original link, never real files,
     `url_state`, fingerprint candidates, link keys or capture dates; the written
     recovery-kind mapping, where an unmapped category fails the build;
   - the import day, defined by the import run's ID, not by its date;
   - the committee mapping (decision 36): House codes as `hs` plus the lowercased code,
     joined to `committee_records` by congress, with unmapped codes reported by count;
   - `real_body`: a body with at least one real capture row; edges connect only source
     files whose own rows are real;
   - API responses: JSON fetched from the endpoint list (api.congress.gov,
     api.govinfo.gov, the YouTube Data API, the Wayback CDX API), with a sample URL test
     per entry;
   - a bodiless source file for each recovery whose original link was never fetched, so
     every recovery has a document;
   - total orders for every "earliest" pick (`linked_from`, `first_run`) and a fixed order
     for every list column (data model §3.3);
   - the `url_state` recheck intervals, as a `(family, interval)` policy table;
   - `url_key` for every link join (decision 29): the wrapper patterns and the
     strip-list, each entry with a real sample URL as a test;
   - the edge set: identical real files connect, web pages included (decision 27);
     placeholders (*k* = 100) connect nothing; a shared endpoint connects two complete
     files only when their text fingerprints match (decision 10); renditions of one
     document connect through publisher groups or, failing that, same-directory same-stem
     files with document extensions and a list of generic stems to exclude (decision 31);
   - the saved file: the PDF if there is one, otherwise the newest real file by first
     fetch, undated files last, ties broken by body hash; the rest are alternates
     (decision 32);
   - `url_state`, keyed by requested URL and counted over receipt lines, not capture rows;
   - editions stay apart: no rendition edge at an address with several editions
     (decision 42);
   - archive members judged and named by their own path (decision 43);
   - review semantics: supersession, `hide` with its note, `duplicate_of` as a merge edge,
     overrides (decisions 46–47);
   - each document's meetings joined to `meeting_records` (decision 38);
2. **The model SQL** (design §6.1), with the data model's 20 invariants as its test suite:
   `url_state`, `filenames`, `documents`, `members`, `recoveries`, `reviews`, and the
   release files, with `list` sorted by filename and then
   first-captured date (undated rows last within a filename), every recovery labeled by
   kind (decision 18), and each document's meeting references, document date and official
   record keys (decisions 33–35).
3. **Golden vectors** for `source_id` and `document_id`, generated from Python
   `source_identity` and `compute_document_id` (`retention/index/bipartite.py:165,197`) and
   checked in the engine's tests. The formulas keep the logical body key string
   `bodies/sha256/<aa>/<sha>.gz`.
4. **Parity against the old catalog,** on browser-visible fields, compared many-to-many and
   keyed by source evidence (the files and URLs each document holds), since old body keys
   can sit in several old documents. Expect large, explained changes: about 560k
   catalog rows leave the list (captions, metadata records, playlists, API responses),
   about 30k documents lose error pages from their body sets, about 4,900 lose Senate
   landing pages, cut-off copies and recovery imports drop out of body sets, and about
   16k format groups merge (32,547 documents today).
   - **The comparison reports by cause, not by document:** each known cause with its count
     and a few sampled examples, and every difference that fits no known cause listed
     separately. Only that last group needs reading one by one.
   - Classify each unexplained difference:
     - a rule change: fine, recorded with the rule;
     - an old-pipeline error: the new model wins;
     - a fact that exists only in derived tables: a blocker (open question 1).

**Done when:** every known cause has its count and samples, every unexplained difference is
classified with no blocker left, and the model runs as a CLI job on the smallest
runner.

The 38–95 minute Python rebuild from revision 1 (Step 0) is not needed: the pinned
catalog pair, converted in F0, is the oracle.

### F. Switch and delete

1. **Publish workflow** (design §8): the capture job; the publish job (ingest, readings,
   filename readings, model, export, canary, flip, status); the weekly maintenance job.
   Delete the disabled viewer workflow and its 30-minute cron.
2. **Capture reads `url_state` from the live release** and stops reading the raw index.
3. **Delete the old layers,** one PR per group, measured at cut. Revision 1's counts are
   the estimates:

| Group | Estimate (source + tests) |
|---|---|
| Python incremental catalog: 22 modules, the `catalog/` facade, `incremental_boundary_proof.py` | 9,509 + 6,744 |
| Python rebuild path, now replaced by the model SQL: `catalog_staging`, `catalog_publication`, `catalog_cache`, `catalog_validation`, `index/*`, the oracle files | at cut |
| Raw index: `partition_routing`, `raw_state_routes`, `raw_changes`, the Python merge, the `raw.json` schema backfills, the retention planner (147) | at cut |
| Viewer publication: the journal, resume and attempt route | 2,786 + 2,005 |
| Viewer publication: the v6 preparer and the v6 reader branch | 1,695 + 1,112 |
| `docspec_client`'s HTTP custody path, with its fallbacks and the pure-Python `blake3`, if nothing else uses it | at cut |
| Shims and legacy formats (revision 1 WS10 list) | 2,064 + 1,058 |
| Measurement scripts for deleted subjects (revision 1 WS11 list) | 1,862 + 723 |
| The F0 converter and the one-off PDF copy job (after B13) | at cut |
| The custom-domain path allowlist and its tooling: `r2_edge_rules.py`, `apply_r2_edge_rules.py` (decision 39); CORS, cache headers, CSP and the `?filename=` rule stay | at cut |
| docspec-rs: unused routes, lifecycle families, the Dagster adapter, provider suites, `cli_args.rs`, hand-written SHA-256, date transforms, legacy formats (ss-oxg1's WS9 children) | 14,383 certain, up to 2,101 more |

The engine cuts apply only to code no consumer uses after the switch. Check
`spicysearch`, `spicyengine` and `DocSpec` as well as congressional-tech. The independent
ones (`sha2`, date transforms, `cli_args.rs`, the Dagster adapter) can land any time.

**Done when:** the explorer serves an engine-built release, the old workflows are gone,
and the deleted line counts are recorded.

### G. Parked

- **news_lake** (ct-d8cf, ss-jxvn): decision 2 stands; no work until it adopts the three
  layers.
- **The freeze:** no browser or engine performance work beyond this plan until there is a
  user or a measured failure on real data.
- **ct-gi01** (committee explorer and weekly retention onto incremental tables): its
  approach conflicts with the design. Re-scope it before starting.
- **Considered, not chosen** (owner, Oct 24), so they aren't re-proposed without new
  information: showing the original link's last status (36,137 documents' URLs last
  returned 404 or 410), showing saved-file size (3,042 over 50 MB), and witness links from
  House meeting XML.
- **Parquet variant for the folds:** revisit when all three hold: an iceberg-rust release
  writes variant through its Parquet writer (0.10.1, the pinned and latest release, has no
  variant type; 0.11 is expected to add it), Basin Catalog accepts format-version 3
  tables, and DataFusion core or a maintained crate can query variant. The candidates are
  nested, mixed-type readings such as Congress.gov API JSON and MODS or meeting XML trees.
  House-naming metadata stays typed facets plus the fold (owner decision; data model,
  conventions).
- **Full-text extraction of every PDF** (decision 22): one later read of about 403 GB into
  its own text table. It gives page counts, and text fingerprints for every PDF, which
  makes dedupe across sites cheap to revisit.

### H. Ticket process

1. Create the ticket before the first code commit. An epic closes only after its children.
2. Acceptance criteria name an observable behavior and the test or measurement that shows
   it. Performance work records a baseline on real data and the decision rule first.
3. Commit evidence under `docs/` or in the ticket, never in the gitignored `output/`.
4. A deletion closes only when the old path is gone, with before and after `wc -l`.
5. Every reviewer brief names the project runners (`scripts/dev.py`, `scripts/check`).

## 5. What revision 1 became

| Revision 1 | Ticket | Now |
|---|---|---|
| Step 0, full Python rebuild | ct-q2ht | Dropped: the pinned catalog is the oracle (F0, E4) |
| WS1 Python half | ct-dzlf | B11 for surviving code; the other sites go with the old layers |
| WS1 engine half | ss-pdv0 | C0 |
| WS2 raw write rules | ct-syx8 | B2–B6 and B13; the planner and `raw.json` steps go with the old layers |
| WS3 custody client | ct-tw3r | Deleted with the HTTP custody path (F3) |
| WS4 provenance pinning | ct-70kc | B7; the fingerprints go with the old catalog |
| WS5 WAF allowlist | ct-t906 | Deleted in F3 (decision 39) |
| WS6 export-pins | ct-qqk2 | A, design §6.4 built in E and F; the journal route deleted in F3 |
| WS7 incremental catalog | ct-7uit | Replaced by D and E; the Python layer deleted in F3 |
| WS8 news_lake | ct-d8cf | Parked (G) |
| WS9 docspec-rs cuts | ss-oxg1 children | F3; capabilities in C |
| WS10 shims | ct-r6xw | F3 |
| WS11 freeze | ct-2wsw | Rule in G; script deletions in F3 |
| WS12 process | ct-uov2 | H |
| E1 raw index onto engine datasets | ct-w5fm | Dropped: `captures` replaces the raw index |
| E2 body existence | ct-allr | B5 |
| E3 byte-count round trips | ct-eb71 | Dropped with the old layers |
| E4 verify each upload once | ct-klql | B2: Content-MD5 on create, nothing on a 412 |
| E5, E6, E9 | — | Dropped with the old layers; C3 and C5 hash while writing |
| E7 engine I/O and lifecycle | ss-k1f0, ss-n68e, ss-1uh5, ss-eyhn | C0 and M1; the other two aren't needed |
| E8 `blake3` | ct-5v1y | Deleted with the HTTP custody path |
| E10 news_lake | ss-jxvn | Parked |
| E11 `accepted.json` | ct-st8m | B8 |
| E12 small items | ct-i5g2 | The receipt LIST is D1; the rest goes with the old layers |
| — | ss-om9p | Not needed: it fixes the lifecycle store, which the target drops |

## 6. Keep list

These survive the switch unchanged:

- **Raw path:** create-only body and receipt writes, MD5-verified uploads; recovery
  `checked_put`; RecoveryGuard (ct-jl1m), the body-key shard check (ct-qspb), recovery
  admission (ct-4r1c), ct-fqgf and ct-vxzu; `derive_body_key`, `physical_body_object_key`
  and their golden tests.
- **Site:** `cache.ts`, `withVerifiedJson`, `startup.ts`, and `--verify-publication`'s
  Chromium checks, retargeted to the contract test.
- **Engine:** `Strict<T>`, the remote scope boundary with create-only writes and the
  digest-verified delete actor, `BackendCapability`, `deny_unknown_fields`,
  ConnectedComponents, and export child tables.

## 7. Open questions for the owner

1. **Only if needed:** if D1 or E4 finds facts that exist only in derived tables, record
   them as provenance first, or accept losing them?

## 8. Order

There is no schedule (decision 37). The work runs in this order:
1. P4, the bucket lock (owner), and B14, the cut-off re-fetch.
2. M1, M2 and S.
3. F0 and the hand-built fixture release; C0; tracks A and B (B13 after B1 and B3).
4. C.
5. D.
6. E, with E1 already written in S.
7. F.

The widest uncertainty is E: it stays bounded unless parity finds facts that only derived
tables hold.
