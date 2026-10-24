# Simplification plan: congressional-tech and docspec-rs

Revision 2, 2026-10-24. It implements `docs/engine-first-architecture.md` (revision 4)
and replaces revision 1 of this file (in git history). Evidence:
`docs/reviews/2026-10-24-ticket-audit/` (the audit, with measured line counts) and
`docs/reviews/2026-10-24-design-review/` (three design reviews; section numbers below
cite the design as "design §n" and the efficiency review as "CS300 Fn").

## 1. Strategy: build beside, switch, delete

Revision 1 refactored the old pipeline piece by piece. The design replaces most of that
pipeline, so refactoring it is wasted work. Revision 2 builds the target beside the old
pipeline, switches publishing to it, and deletes the old layers whole.

- **What survives:** fetchers and raw writers, recovery imports, review tools,
  `house-naming`, the site and docspec-rs. Changes to these happen now.
- **What goes:** the Python catalog (incremental and rebuild), the raw index and its
  routing, the viewer-publication journal route, the v6 preparer, and the shims around
  them. They get no new work and are deleted at the switch.
- **Until the switch,** the old capture job keeps writing raw data. It gets raw-safety
  fixes only.

## 2. Constraints

**What must survive:** objects in R2 `congressional-tech-raw` under `bodies/`,
`receipts/` and `provenance/`. Everything else can be rebuilt, and nothing uses it yet.

**Owner decisions (binding):**

| # | Decision | Effect in revision 2 |
|---|---|---|
| 1 | Durable per-step commits | Each pipeline step commits once (one Iceberg append). The engine's deferred-commit mode is reverted (C0). |
| 2 | news_lake keeps the DocSpec backend | Parked: no work until news_lake adopts the three layers (design §14). |
| 3 | Publishing moves to export-pins | The release pipeline (design §6.4) is its finished form: one release identified by content, one conditional pointer flip. The journal and resume route is deleted (F3). |
| 4 | Raw protection is a bucket lock; one bucket | Step B1. |
| 5 | `r2.dev` stays open | Every key is public, so a path allowlist on the custom domain protects nothing (open question 5). |
| 6 | Engine first | The target is built in docspec-rs; congressional-tech keeps no code that overlaps it. |

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

## 3. Week one: measure, then commit to the engine work

Two measurements decide how much engine work there is. The first release starts the
site work at the same time.

**M1. Basin Catalog commits and compaction** (docspec-rs; ss-om9p, ss-n68e).
1. Fix ss-om9p so every commit sends its requirements. Test: two writers append from the
   same snapshot, and the second is refused.
2. Append 400 day-sized batches (about 315 KB each) to a scratch table with Basin
   compaction and snapshot expiration enabled. Count data files and manifests in the
   current snapshot before and after maintenance runs.
3. Measure or remove the unmeasured 2 MiB file cap (ss-n68e).

Decides: Iceberg stays (manifests bounded), or the three logs move to dated Parquet with an
`If-Match` manifest (design §13).

**M2. Export and grouping on real data** (docspec-rs).
- Inputs: the pinned Oct 19 snapshot (captures `db033173…`, catalog generation
  `596f08fa…`).
- Group the real graph with a first placeholder rule. Record time, peak memory and the
  largest components.
- Export `list`, `detail`, `ids` and `occurrences`. Bytes must be identical across 1, 2
  and 4 threads and shuffled input. Record time and peak memory on `ubuntu-24.04`
  (4 vCPU, 16 GB), the smallest runner class.

Decides: the size of track C, and whether DataFusion matches the 3.7 s DuckDB proxy.

**F0. The first release, converted from the pinned catalog** (congressional-tech).
- Convert the pinned catalog pair into the release format (design §6.2), using the
  engine's RunSpec where it can. The CS300 review's
  `measurements/build_list.py` shows the shape; it built all four files in 24 s.
- This release is the reader's fixture (track A) and the parity oracle (E4). Its manifest
  records that it came from the pinned catalog.
- If the owner agrees (open question 1), it goes live as the first release, so the
  explorer works on Oct 19 data while the rest is built.
- The converter is a migration tool. It is deleted at the switch.

## 4. Tracks

| Track | What | Depends on | Estimate | Starts |
|---|---|---|---|---|
| A | Site reader and canary | F0 | 1–2 weeks | week 1 |
| B | Raw writers and protection | P4 (owner) for B1 only | 1–2 weeks | week 1 |
| C | Engine capabilities | M1, M2 | 3–6 weeks | week 2 |
| D | Lake tables and backfills | C2, B2 | 1–2 weeks | after C2 |
| E | Model SQL and parity | C1, C3, C4, D, F0 | 2–4 weeks | after D |
| F | Switch and delete | A, E | 1–2 weeks | last |

The critical path is M → C → D → E → F: 8–15 weeks for one engineer. A and B run beside
C. Estimated total: **8–16 weeks**.

### A. Site reader and canary

1. A reader module for the release format: pointer → manifest → `list` in a Web Worker,
   `detail` by row (page index, concurrent page reads), `ids`, `occurrences` and shards.
   No DOM dependency. Accepts the current and previous `schema_version`.
2. Deep links carry the `document_id` and resolve it through `ids`.
3. The Node canary (design §6.4), as a script the publish job runs.
4. A CI contract test: the real site in a headless browser against F0. It moves to a
   release built from a fixed sample of real receipts once track E exists.

**Done when:** the site loads F0 locally, and the canary passes against F0 in under a
minute.
**Replaces at the switch:** `catalog-v6.ts` and its v6 and ExportPin branches, the v6
paths in `worker.ts`, and `verify-live-publication.mjs`. Keep `cache.ts`,
`withVerifiedJson` and `startup.ts` (ct-tdsx) where they fit.

### B. Raw writers and protection

This code survives, so it is fixed now.

1. **Bucket lock** (owner, ct-1l1h) on `bodies/`, `receipts/` and `provenance/`.
2. **Receipts and bodies to the design (§4.1–4.2):**
   - receipts record the stored MD5 and stored size;
   - new compressible bodies are stored with `Content-Encoding: gzip` and the original
     `Content-Type`;
   - one create-only PUT per body, never multipart;
   - on a 412, compare the ETag with the MD5 (one verifier, ct-klql);
   - receipt keys use the UTC write date.
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
9. **The weekly maintenance job** (design §4.4): LIST joined to the capture rows, the
   25-body sample and the orphan report. It joins to the old capture index until D1
   exists.
10. **The one-time full re-hash** of bodies written before receipts carried an MD5, with
    their ETags recorded under `provenance/verification/`.
11. **A ratchet test:** `PYTEST_CURRENT_TEST` may not appear in surviving packages. Delete
    the raw-adjacent substitution in `raw_storage.py:655-672` now; the rest of the 75
    sites go with the old layers.
12. **Owed while the old capture path runs:** ct-63hg (repair wrong `stored_sha256` index
    rows in place) and ct-j9c4 (confirm the daily capture writes correct values). The
    target reads receipts, so these matter only until the switch.

**Done when:** the refusal matrix passes, the lock is on, and one capture run's receipts
carry MD5s that match the stored ETags.

### C. Engine capabilities (docspec-rs)

**C0. First moves on engine main.** Revert the deferred-commit mode and delete the
dataset-name predicates (ss-pdv0). Both came after congressional-tech's pin, so nothing
depends on them. Hash while writing, and stop HEADing and re-downloading immutable files
(ss-k1f0).

**Then the capabilities in design §9:**

| # | Capability | Evidence |
|---|---|---|
| C1 | Multi-input SQL plans over Basin tables and Parquet files in one context | A plan joining two tables and a file |
| C2 | Append through the REST catalog with requirements (lands in M1) | The two-writer test |
| C3 | Deterministic multi-file export: SHA-256 and MD5 while writing, unique sort keys, row-range shards, pinned writer properties | Byte equality across thread counts and input orders |
| C4 | ConnectedComponents in memory over 32-bit IDs, refusing above a node cap | M2's graph; a refusal test |
| C5 | Streaming I/O: no re-read or HEAD of immutable files (C0) | Request counts in a test |
| C6 | Bounded threads, memory pool and scratch | A join at the pool limit spills or fails clearly |
| C7 | A CLI that runs a declarative job spec and returns a machine-readable result | The M2 export as a job spec |

**Not needed by congressional-tech any more:** lifecycle-store compaction on R2
(ss-1uh5), copy-on-write measurement (ss-eyhn) and insert-if-absent (ss-jxvn). The target
has no engine lifecycle store, no updates and no news_lake work. Close them unless another
consumer needs them.

**Done when:** one CLI job runs the M2 export from Basin tables, byte-identical across
thread counts, on the smallest runner.

### D. Lake tables and backfills

1. **`captures`** (design §5.1):
   - ingest with per-family listing from the newest ingested date;
   - backfill from all 2,289 receipts (1.08 GB compressed); older receipt shapes are
     mapped in the ingest SQL, with a test sample of each shape;
   - the rebuild-equivalence test;
   - **compare with the pinned old capture index** (3,909,134 rows) as row multisets. A row
     that exists only in the old index is a fact raw doesn't hold, and it blocks the
     switch until the owner decides (open question 7).
2. **`readings`** (design §5.2): one parser and version per media family; the scope in
   the model SQL. Backfill HTML, XML and JSON first (about 5 GB), then PDF titles and page
   counts as a background job (about 335 GB). The parser functions survive; the
   adoption machinery around them goes in F3.
3. **`filename_readings`** (design §5.3): a producer that runs `house-naming` over the
   work list and appends through the engine. Backfill is about 7 minutes.
4. Enable Basin compaction and snapshot expiration on all three tables.

**Done when:** all three tables exist with complete backfills, and both `captures`
comparisons pass.

### E. Model SQL and parity

1. **Write the grouping rule down first:** the edge set and the placeholder threshold *k*
   (open question 2), as SQL with a short rationale.
2. **The model SQL** (design §6.1): `url_state`, `filenames`, `documents`, `members`,
   `recoveries`, `reviews`, and the browser files.
3. **Golden vectors** for `source_id` and `document_id`, generated from Python
   `source_identity` and `compute_document_id` (`retention/index/bipartite.py:165,197`) and
   checked in the engine's tests.
4. **Parity against F0,** on browser-visible fields only. Classify each difference:
   - a rule change: fine, recorded with the rule;
   - an old-pipeline error: the new model wins;
   - a fact that exists only in derived tables: a blocker (open question 7).

**Done when:** every difference is classified with no blocker left, and the model runs as
a CLI job on the smallest runner.

The 38–95 minute Python rebuild from revision 1 (Step 0) is not needed: the pinned
catalog pair, converted in F0, is the oracle (CS300 F11).

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
| The F0 converter | at cut |
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

### H. Ticket process

1. Create the ticket before the first code commit. An epic closes only after its children.
2. Acceptance criteria name an observable behavior and the test or measurement that shows
   it. Performance work records a baseline on real data and the decision rule first.
3. Commit evidence under `docs/` or in the ticket, never in the gitignored `output/`.
4. A deletion closes only when the old path is gone, with before and after `wc -l`.
5. Every reviewer brief names the project runners (`scripts/dev.py`, `scripts/check`).

## 5. What revision 1 became

| Revision 1 | Ticket | Revision 2 |
|---|---|---|
| Step 0, full Python rebuild | ct-q2ht | Dropped: the pinned catalog is the oracle (F0, E4) |
| WS1 Python half | ct-dzlf | B11 for surviving code; the other sites go with the old layers |
| WS1 engine half | ss-pdv0 | C0 |
| WS2 raw write rules | ct-syx8 | B2–B6; the PDF migration fold, planner and `raw.json` steps go with the old layers |
| WS3 custody client | ct-tw3r | Deleted with the HTTP custody path (F3) |
| WS4 provenance pinning | ct-70kc | B7; the fingerprints go with the old catalog |
| WS5 WAF allowlist | ct-t906 | Open question 5 |
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
| E4 verify each upload once | ct-klql | B2 |
| E5, E6, E9 | — | Dropped with the old layers; C3 and C5 hash while writing |
| E7 engine I/O and lifecycle | ss-k1f0, ss-n68e, ss-1uh5, ss-eyhn | C0 and M1; the other two aren't needed |
| E8 `blake3` | ct-5v1y | Deleted with the HTTP custody path |
| E10 news_lake | ss-jxvn | Parked |
| E11 `accepted.json` | ct-st8m | B8 |
| E12 small items | ct-i5g2 | The receipt LIST is D1; the rest goes with the old layers |

## 6. Keep list

These survive the switch unchanged:

- **Raw path:** create-only body and receipt writes, MD5-verified uploads; recovery
  `checked_put`; RecoveryGuard (ct-jl1m), the body-key shard check (ct-qspb), recovery
  admission (ct-4r1c), ct-fqgf and ct-vxzu; `derive_body_key` and its golden test.
- **Site:** `cache.ts`, `withVerifiedJson`, `startup.ts`, and `--verify-publication`'s
  Chromium checks, retargeted to the contract test.
- **Engine:** `Strict<T>`, the remote scope boundary with create-only writes and the
  digest-verified delete actor, `BackendCapability`, `deny_unknown_fields`,
  ConnectedComponents, and export child tables.

## 7. Open questions for the owner

1. **First release:** publish F0 (converted from the pinned Oct 19 catalog) as the live
   release, so the explorer works in two to three weeks? Recommended.
2. **Placeholder threshold** *k* for grouping (design §14.2).
3. **PDF readings:** title and page count, or nothing (design §14.3).
4. **Public document IDs:** full SHA-256 or a 16-hex prefix (design §14.1).
5. **Custom-domain path allowlist:** delete it and its tooling? `r2.dev` already serves
   every key (decision 5), and saved copies need `bodies/` on the custom domain. Keep the
   CORS policy either way.
6. **Legacy gzip bodies:** serve saved copies through an edge rule, or write uncompressed
   copies once under new keys?
7. **Only if needed:** if D1 or E4 finds facts that exist only in derived tables, record
   them as provenance first, or accept losing them?
8. **Retention numbers:** releases kept and snapshot age.

## 8. Schedule

| When | Work |
|---|---|
| Week 1 | P4 lock; M1; M2; F0; A and B start |
| Weeks 2–3 | A and B done; the explorer goes live on F0 if approved; C under way |
| Weeks 2–7 | C |
| Then | D (1–2 weeks), E (2–4 weeks), F (1–2 weeks) |

Total: 8–16 weeks for one engineer. The critical path is C → D → E. The widest
uncertainty is E: it stays bounded unless parity finds facts that only derived tables
hold.
