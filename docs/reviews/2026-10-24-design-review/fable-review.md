# Architecture review: `docs/engine-first-architecture.md`

Reviewed 2026-10-24, read-only, following the semi-formal architecture-review workflow.
Paths below are relative to `/Users/mikewolfd/Work/wt/ct-ticket-audit` (congressional-tech,
worktree at origin/main `ce1ff7ef`) or prefixed `ds:` for
`/Users/mikewolfd/Work/spicy-stack/docspec-rs` (`d9c6719`) and `ice:` for the pinned
`iceberg-0.10.1` crate source in `~/.cargo/registry`. Nothing was built or run beyond `grep`,
`sed`, `wc` and reading files. Severity mapping: BLOCKER = blocker, CONCERN = major,
OBSERVATION = minor.

## Verdict in one paragraph

**RECONSIDER (D2).** The diagnosis and the core bet are right: receipts already are the
append-only log, the raw index rewrites itself every day, and a full recompute of roughly
8M small rows is cheap on a columnar engine. The raw contract, the content-addressed
release with one `If-Match` flip, the canary, the N/N-1 reader contract and
"measure before deleting" are all sound. But the design as written cannot be built on the
engine it names: docspec-rs has no multi-table SQL operation (its SQL takes one Parquet
input; everything else is typed Join/Aggregate/ConnectedComponents), and iceberg 0.10.1
exposes no public way to commit a "replace table", a snapshot tag, or physical file
cleanup. Both gaps have one clean fix that also removes a primitive the doc asks for:
keep Iceberg only for the two append-only tables (`raw.captures`, `derived.readings`,
where `fast_append` is exactly right) and compute the model straight into the export
Parquet in one DataFusion job. No "replace table", no model snapshots to expire, no
orphan files. Beyond that, the doc underestimates the first readings pass (parsing all
1.04M bodies, 696 GB, which the current system has never done), has an unsafe
high-water-mark ingest, no reclamation for release objects, and drops two things the
site and the owner's decisions still need: document reviews and news_lake's engine
surfaces.

---

## 1. Findings

### FINDING 1 — BLOCKER — The model step needs an engine primitive the doc does not list

- **Category:** intent-vs-shape, unstated-assumption
- **Location:** doc §4.4 ("versioned SQL files in this repo, executed by docspec-rs each run"), §6 Add list
- **Evidence:**
  - The engine's only free-SQL operation is `RunSpec` (Build): one `input: String` Parquet
    file plus one `sql: String` (`ds:src/model/operations.rs:46-62`).
  - Multi-input work is typed, not SQL: `RefreshTransform::{Join, Aggregate,
    ConnectedComponents}` over exact `VersionRef`s (`ds:src/model/transform.rs:281-293`).
  - `ds:docs/STATUS.md`: "General incremental SQL is explicitly deferred; unsupported
    transformations use a full rebuild." `ds:README.md:1-5`: "admits an exact Parquet input,
    executes a repeatable SQL query."
  - The doc's §6 "Add" list has replace-table, multi-table export, streaming hash and
    tags; it has no "run SQL over N Iceberg tables" primitive, yet §4.4 joins
    `raw.captures`, `derived.readings` and provenance in SQL.
- **Contradicts:** P2, P5.
- **Exercised by:** every model table in §4.4; Phase 3 of §11.
- **Change (RESHAPE):** add exactly one engine primitive to §6: *model = execute a SQL file
  over N named Iceberg tables (and provenance) and write the result as the export
  Parquet*. Make it the step that replaces both "replace table" and "multi-table export"
  (see Finding 2). The step's inputs are snapshot IDs; its output is the content-addressed
  file set. Everything the doc wants from steps 3 and 4 survives; one primitive instead of
  two.

### FINDING 2 — BLOCKER — "Replace table", snapshot tags and snapshot expiry cannot be built on iceberg 0.10.1's public API

- **Category:** unstated-assumption, commitment-violation (doctrine: use maintained primitives, don't roll your own)
- **Location:** doc §4.4 ("replace table operation, new in the engine"), §6 Add 1 and 4, §6 "Library constraint ... does not bind"
- **Evidence:**
  - `ice:src/transaction/mod.rs:135-170`: the public `Transaction` actions are
    `upgrade_table_version`, `update_table_properties`, `update_schema`, `fast_append`,
    `replace_sort_order`, `update_location`, `update_statistics`, `expire_snapshots`.
    There is no overwrite, replace, rewrite-files, delete or manage-snapshot-refs action.
  - A custom action cannot be plugged in: `TransactionAction` is `pub(crate)`
    (`ice:src/transaction/action.rs:37`), and `TableCommit`'s builder is `pub(crate)`
    (`ice:src/catalog/mod.rs:346-351`), so `TableUpdate::SetSnapshotRef` /
    `AddSnapshot` (`ice:src/catalog/mod.rs:531-556`) are unreachable from the engine.
  - `expire_snapshots` is metadata-only: "Physical file cleanup is the responsibility of a
    higher-level maintenance operation" (`ice:src/transaction/expire_snapshots.rs:34`).
  - The engine today uses only `fast_append` (`ds:src/catalog.rs:1150`,
    `ds:src/storage.rs:871,906`), and emulates replacement with a fresh table per release,
    which is the O(F)-metadata pattern the audit faulted
    (`docs/reviews/.../batches/docspec/docspec-efficiency.md` §4 item 3).
- **Contradicts:** P4, P7.
- **Exercised by:** §4.4 daily model commit; §6 Remove 1 (the lifecycle store is removed
  "replaced by Iceberg snapshots, tags and expiry", which the library cannot supply).
- **Change (RESHAPE):** do not store the model in Iceberg. The model is a pure function
  whose only consumer is the export; write the export directly (Finding 1). Keep Iceberg
  for `raw.captures` and `derived.readings`, where `fast_append` is sufficient and
  `set_snapshot_properties` (`ice:src/transaction/append.rs:70`) can carry the step
  identity. Release pins become the release manifests (they already list input snapshot
  IDs); retention of the two append tables is `expire_snapshots` plus one reachability
  sweep (LIST the warehouse prefix, delete files not in any live manifest) — keep that
  one small piece of the engine's retention rather than all of it. Record this in §10 as
  "plain Parquet wins for the model; Iceberg stays for the log."

### FINDING 3 — CONCERN — The first readings pass is an unmeasured, multi-job backfill the estimate omits

- **Category:** user-value (cost), unstated-assumption
- **Location:** doc §4.3, §9 ("Readings: minutes; O(B) only on a parser bump"), §11 Phase 2 exit ("Every body has a reading for the current parser version"), §11 estimate
- **Evidence:**
  - B = 1,036,256 bodies, 696 GB stored (763 GB raw), 260,834 PDFs = 403 GB
    (`docs/reviews/2026-10-24-ticket-audit/batches/czsd/czsd-efficiency.md`, measurements table).
  - The current catalog never parsed all bodies: the rebuild oracle "pins 24,370 consumed
    or missing object keys; unread bodies remain outside that inventory"
    (`docs/core-workflow-qualification.md:129-134`); PDF readings are supplied
    explicitly (`packages/congress_api/tests/historical_raw_catalog.py:46-48`).
  - A hosted job is capped at 360 minutes (`.github/workflows/capture-raw-sources.yml:136`).
    Downloading 696 GB and parsing 403 GB of PDF on 4 vCPU is many hours to days.
  - Owner decision 1 requires resume after a crash (audit README, Owner decisions); a
    single-commit readings step that spans jobs cannot resume.
- **Contradicts:** P3 (as applied to readings), P12, P13.
- **Exercised by:** Phase 2 exit criterion; any parser-version bump.
- **Change (RESHAPE):** define Phase 2's exit as "readings exist for every body the model
  consumes" (today's page bodies and PDF-metadata set), not for every body. State that
  `derived.readings` appends in bounded batches (K bodies per `fast_append`) so the
  anti-join resumes across jobs. Add a line to §9: "first full-corpus parse: O(B) over
  696 GB, run as a batched backfill over N jobs; measure throughput on 1% first."

### FINDING 4 — CONCERN — High-water-mark receipt ingestion silently skips and duplicates rows

- **Category:** correctness, unstated-assumption
- **Location:** doc §4.2 ("appends only receipts newer than the table's high-water mark")
- **Evidence:**
  - Receipt keys are `receipts/<owner>/<day>/download-<run_id>-<seq>.jsonl.gz`
    (`packages/congress_api/src/congress_api/retention/raw_archive.py:517-523`), several
    per run, from several writers: capture, the recovery import
    (`packages/corpus_recovery/src/corpus_recovery/transfer.py:52`), and manual local runs
    (in scope per doc §2 non-goals). A late or earlier-`day` receipt sorts below the mark
    and is never ingested.
  - `fast_append` carries `RefSnapshotIdMatch` (`ice:src/transaction/append.rs:543`), so
    two concurrent appends conflict; the engine retries on a fresh base
    (`ds:src/storage.rs:904-910`), which appends the same receipts twice.
  - R = 2,289 receipt objects today (audit README, Raw-data status): a full LIST is three pages.
- **Exercised by:** the scheduled run overlapping a manual run; the recovery import.
- **Change (RESHAPE):** replace the HWM with a LIST of `receipts/` anti-joined on
  `receipt_key` against the table (O(R) and cheap at any plausible R); dedupe in the model
  SQL on `(receipt_key, receipt_line)`. §8.3 then becomes a check, not the only safety net.

### FINDING 5 — CONCERN — Nothing reclaims release objects or replaced data files

- **Category:** debt-accretion
- **Location:** doc §4.5 ("objects/<sha>.<ext> create-only, only new files"), §6 Add 4
- **Evidence:**
  - Every changed table produces a new object; the current catalog pair is about 1.09 GB
    (`docs/plans/simplification-plan-20261024.md`, WS10 table); daily changes touch the
    big tables, so growth is on the order of 1 GB/day with no delete path named.
  - Replaced Iceberg data files are never physically removed by `expire_snapshots`
    (`ice:src/transaction/expire_snapshots.rs:34`).
  - This is the pattern the audit faulted in the raw index: "never reclaims", 1.3 GB and
    about 512 datasets per run (audit README §1 table; czsd-efficiency finding 1).
- **Exercised by:** every daily run.
- **Change (RESHAPE):** keep the last K release manifests; delete `objects/` not referenced
  by them (one LIST, set difference). With Finding 2's reshape there are no model data
  files to orphan; for the two append tables run `expire_snapshots` plus the reachability
  sweep. Write the K and the sweep into §4.5 and §8.

### FINDING 6 — CONCERN — Two live requirements are dropped: document reviews and news_lake's engine surfaces

- **Category:** scope, sibling-conflict
- **Location:** doc §4.6, §6 Remove 1–2, §12.6, Appendix
- **Evidence:**
  - The site loads a review publication (`data/document-reviews/reviews.json`,
    `apps/site/src/components/explorer/reader/filenames/publication.ts:129-131`), verifies
    a `review_binding` in the manifest and `evidence/<sha>.(pdf|png|txt)` files
    (`.../reviews.ts:12-70`), and exposes `/api/review/` (`.../worker.ts:33`). The review
    inputs are human/assistant decisions in the repo
    (`packages/congress_api/src/congress_api/retention/saved_response_reviews.json`,
    `saved_responses.py:15`) plus 943 lines of `document_review_*.py`. The doc names none
    of this; §12.3 only says "for example review decisions".
  - news_lake (9,238 lines) calls engine `release`, `compact_lifecycle` and exact release
    pins (`packages/news_lake/src/news_lake/storage/docspec/client.py:84-89,158-159,176,219`;
    `lake.py:222-234,574`). Owner decision 2 keeps that backend (audit README). §6
    Remove 1 deletes the lifecycle-record store those calls depend on while §12.6 declares
    news_lake out of scope.
- **Contradicts:** P2 (as "replaces the ... viewer-preparation layers"), owner decision 2.
- **Exercised by:** the explorer's reviewed-search mode; news_lake's poll loop.
- **Change (RESHAPE):** (a) classify reviews: decisions are provenance
  (`provenance/reviews/`), evidence renders are derived export objects, the model's
  `documents` carries the review overlay, and the release manifest keeps
  `review_binding`; add a row to the Appendix. (b) Either sequence news_lake's move onto
  the same pattern before §6 Remove 1, or keep `release`/`compact_lifecycle` until it moves.
  Name the dependency in §6.

### FINDING 7 — CONCERN — Body verification and body encoding are under-specified in ways that cost a full corpus pass or break saved-copy links

- **Category:** unstated-assumption, commitment-violation (do-once)
- **Location:** doc §4.1 (table, "Body encoding", "Protection"), §8.1
- **Evidence:**
  - The key digest is the SHA-256 of the *decompressed* content; the stored object is gzip
    (`packages/congress_api/src/congress_api/retention/body_files.py:112-128`); PDFs are
    stored uncompressed at `.pdf` (`body_keys.py:62-67`). "Every body hashes to its key"
    therefore means download + gunzip of 696 GB weekly.
  - The site builds saved-copy URLs as `/bodies/sha256/<aa>/<sha>.<pdf|gz>`
    (`apps/site/src/components/explorer/reader/filenames/catalog-v6.ts:39-47`). New
    extensionless "exact bytes" objects have no link the reader can form.
  - The receipt already carries `stored_sha256`/`stored_bytes`
    (`retention/raw_schemas.py:24-27`; `body_files.py:156`); R2 LIST returns size and the
    single-part ETag (MD5) per key, 1,000 keys per page.
- **Exercised by:** §8.1 weekly job; every new capture under the new encoding rule.
- **Change (RESHAPE):** state the weekly verifier as LIST + existence + size (and ETag
  where single-part) against receipts, with a sampled full hash; carry the physical
  `stored_key` in `filenames` so the reader never guesses an extension; and pick one body
  encoding now rather than "exact bytes, maybe gzip later" (the audit measured gzip saving
  9.5% on PDFs; for HTML it is large).

### FINDING 8 — CONCERN — The bucket lock is missing from the migration plan

- **Category:** commitment-violation (raw safety), ordering
- **Location:** doc §4.1 "Protection", §11 table
- **Evidence:** the lock is "Owner action pending" (audit README, Actions taken) and the
  plan's P4; §11 Phase 0 is only the measurement. Phases 1–5 run new writers beside old
  ones with bucket-wide credentials (audit README risk 1) before the one platform barrier
  exists. The plan also asks for a read-only token for Step 0
  (`docs/plans/simplification-plan-20261024.md` §2, "Owner action").
- **Exercised by:** every new writer in Phases 1–5.
- **Change (RESHAPE):** Phase 0 = (a) enable the lock on `receipts/`, `bodies/`,
  `provenance/` and read the rules back; (b) mint the read-only token; (c) the DataFusion
  measurement. Note that the Python oracle's 38 min for 671k rows
  (`docs/core-workflow-qualification.md:138-146`) is not the §9 measurement.

### FINDING 9 — OBSERVATION — Step identity omits the engine digest and provenance; run-time values leak into content addressing

- **Location:** doc §4.4, §4.5, §5 "Idempotent steps"
- **Evidence:** the current manifest embeds `published_at: now()`
  (`packages/viewer_publication/src/viewer_publication/filename_exports.py:783-786`) and
  the reader uses it (`catalog-v6.ts:678`); provenance is files, not a snapshot; a parquet
  writer upgrade changes bytes with unchanged inputs (`ds:src/engine/export/pipeline.rs:676-700`).
- **Change:** key steps on `(input snapshot IDs, SQL digest, engine binary digest,
  provenance listing digest)`; load provenance into an append-only Iceberg table if a
  snapshot ID is wanted; forbid run-time values inside exported tables; detect "nothing
  changed" by the object list, not by `release_id`.

### FINDING 10 — OBSERVATION — The determinism test cannot see what it most needs to

- **Location:** doc §8.2, §12.2
- **Evidence:** two consecutive runs on one machine miss rare scheduling races and
  cross-machine differences; the engine's export sorts by `policy.order_by`
  (`ds:src/engine/export/pipeline.rs:154-190`) with no stated total order; writer props
  are fixed (`pipeline.rs:676-700`), which is good.
- **Change:** enforce structurally — total sort order with a unique tie-breaker, a single
  output partition per file, pinned engine — and compare a local run with the hosted run.

### FINDING 11 — OBSERVATION — One workflow chain couples a multi-hour capture to publishing

- **Location:** doc §5
- **Evidence:** capture defaults to 20,000 attempts and five hours of admission
  (`.github/workflows/raw-source-tables.md`, "Verified capture batches"); today acquisition
  and update are deliberately separate runs (same file). A capture hang blocks the publish.
- **Change:** two workflows: capture on its schedule; publish on `workflow_run` plus a
  schedule. The 45-minute budget applies to the publish chain.

### FINDING 12 — OBSERVATION — Canary, caching and rollback details

- **Location:** doc §4.5 "Canary", "Flip"; §4.6
- **Evidence:** the reader has one fixed pointer URL
  (`apps/site/src/components/explorer/reader/filenames/publication.ts:2-3`); the edge
  config sets Cache-Control per prefix (`infra/cloudflare/congressional-data-r2-edge.json`).
- **Change:** give the reader a `?release=<id>` override on the production code path for
  the canary; `Cache-Control: no-cache` on the pointer, `immutable` on `objects/`; state
  rollback as re-pointing to a prior `releases/<id>.json`.

### FINDING 13 — OBSERVATION — Factual slips in the motivation

- **Location:** doc Summary, §1 table, §9
- **Evidence:** "about 4M rows across all tables" versus §9's own list (3.9M + 1.30M +
  1.68M + 1.24M ≈ 8.1M, plus 2.07M body-index rows); "about 1.24M small reads" and "last 60
  runs" appear in no audit artifact (searched `docs/reviews/2026-10-24-ticket-audit/**`
  and the plan; d8z3a-efficiency has D = 1.24M *rows*; `filename_native.py` pages are
  64-row leaves and 16-child branches, about 19k leaves). The engine's real R2 costs — the
  2 MiB file cap (`ds:src/storage.rs:376-380`), about 11 lifecycle commits per operation
  and O(F) re-HEADs (docspec-efficiency §1, §4) — are the reasons today's engine is slow
  and should be named under §6 since Remove 1 and Add 3 fix them.
- **Change:** correct the sum; cite or drop the two unsourced numbers; add the three engine
  costs to §6 as the measured motivation.

### FINDING 14 — OBSERVATION — Two hash families

- **Location:** doc §4.5, §6 Add 2–3
- **Evidence:** the engine's identity is BLAKE3 everywhere
  (`ds:src/engine/export.rs:658-662`, `ds:src/storage/remote/objects.rs:593-626`); the doc
  asks for SHA-256 while writing.
- **Change:** pick one. Naming objects by BLAKE3 hex changes nothing downstream; or switch
  the engine. Don't carry both.

### FINDING 15 — OBSERVATION — The raw-writer inventory is incomplete

- **Location:** doc §4 diagram ("fetchers"), Appendix
- **Evidence:** `source-fetch` writes nothing to R2 (stdin → local files → stdout,
  `packages/source-fetch/main.rs:3`); Python uploads (`acquisition/raw_sync.py:398-419`,
  `body_files.py:105-157`). `corpus_recovery` (1,700 lines) is a second raw writer
  (`transfer.py:52`). The Committee Explorer builds `bodies/sha256/...` paths only in a
  local stage and publishes to the `pipeline-data` git branch
  (`apps/committee_youtube/src/committee_explorer/parquet.py:418-428`;
  `.github/workflows/publish-explorer.yml:34-50`) — not an R2 writer, and unaffected.
- **Change:** name both in §4.1 and the Appendix; say the Committee Explorer is out of
  scope and why.

### FINDING 16 — OBSERVATION — Receipts need a writer identity and a header allowlist

- **Location:** doc §4.1, §7
- **Evidence:** with bucket-wide tokens and a create-only lock a buggy writer can still add
  receipts; receipts record `response_headers`
  (`packages/congress_api/src/congress_api/transport/rust_fetch.py:87`) and are public and
  permanent by design.
- **Change:** record git commit and run id in each receipt (consistent with "refuse
  uncommitted code"); allowlist response headers so `Set-Cookie`/auth headers never enter
  an immutable public object.

### FINDING 17 — OBSERVATION — Hosted runner disk

- **Location:** doc §9
- **Evidence:** the doc states 4 vCPU / 16 GB; the standard public-repo runner also has
  about 14 GB of SSD (external knowledge, confirm). DataFusion spill plus export files plus
  Iceberg staging must fit.
- **Change:** add the disk bound to the measurement record.

---

## 2. Section-by-section verdict

| Section | Verdict | Why |
|---|---|---|
| Summary, §1 Context | keep (fix F13) | Diagnosis is right and sourced except two numbers |
| §2 Goals / non-goals | keep | Complete; goal 4 is the doctrine |
| §3 Constraints | keep | Matches the owner decisions in the audit README |
| §4 Architecture diagram | reshape | Merge steps 3 and 4; the model is not an Iceberg table (F1, F2) |
| §4.1 Raw layer | keep core; reshape verification, encoding, writers | F7, F15, F16; lock moves to Phase 0 (F8) |
| §4.2 Captures | reshape | LIST + anti-join, dedupe (F4) |
| §4.3 Readings | reshape | Batched appends; scope the first pass (F3) |
| §4.4 Model | reshape | SQL-over-N-tables primitive writing the export; no replace table (F1, F2) |
| §4.5 Export and publish | keep; add GC, canary override, cache, rollback | F5, F12, F9 |
| §4.6 Site contract | keep; add reviews, recoveries, saved-copy key | F6, F7 |
| §5 Orchestration | reshape | Two workflows; fuller step identity (F11, F9) |
| §6 Changes to docspec-rs | reshape | Replace "replace table" and "tags/expiry" with the SQL→export primitive and a reachability sweep; sequence against news_lake (F2, F6) |
| §7 Security | keep; add F16 | Token scoping statement is correct as far as I know (confirm) |
| §8 Verification | reshape | LIST-based raw check; structural determinism (F7, F10) |
| §9 Performance model | reshape | Add the readings backfill and disk (F3, F17) |
| §10 Alternatives | reshape | "Plain Parquet" wins for the model; Iceberg stays for the log (F2) |
| §11 Migration | reshape | Lock and token in Phase 0; Phase 2 exit; reviews and news_lake rows (F8, F3, F6) |
| §12 Risks | keep; add F2 | The library gap is the biggest unlisted risk |
| Appendix | reshape | Add corpus_recovery, reviews, news_lake, Committee Explorer (F6, F15) |

Nothing warrants **reverse**. The bet (full recompute, receipts as truth, content-addressed
release) stands.

## 3. What the doc gets right

- The diagnosis: the raw index is O(S+B) per run and "incremental" layers touch everything
  (czsd-efficiency finding 1; README §1). Receipts already are the append-only log (every
  capture row carries a `receipt_key`; 2,289 of 2,289 present).
- Engine-native keyed merges are copy-on-write over hash-distributed keys in iceberg
  0.10.1 — the doc's §10 reason for rejecting them is correct (`ice:` has no delete-file
  commit action; docspec-efficiency §3).
- Receipts as truth, provenance as raw, `accepted.json` moved into `provenance/` with the
  backup already made (README, Actions taken).
- Create-only PUT with Content-MD5 is already how the raw path writes
  (`retention/r2.py:111-124,378-379,424-444`); the doc asks only for the sha256 metadata and
  a byte compare on 412, which the audit also asked for.
- Content-addressed objects + release manifest + one `If-Match` flip; canary before flip;
  N/N-1 reader versions; CI running real publisher output through the real reader.
- Naming the load-bearing assumption and measuring before deleting (§9).
- Removing the lifecycle-record store, the `test-util` production branches, the Dagster
  adapter, `cli_args.rs`, legacy formats and the hand-rolled SHA-256
  (`ds:src/engine/connected_components/sha256.rs`; `sha2` is in `Cargo.lock`).
- Idempotent steps keyed by inputs; no journals or resume descriptors.
- Honest alternatives table that already contains the right answer for the model layer.

---

## 4. Evidence certificate

### 0. Coverage and observation log

#### Artifacts read

| Artifact | O-IDs | Key observations |
|---|---|---|
| `docs/engine-first-architecture.md` | — | The artifact under review (all sections) |
| `docs/reviews/2026-10-24-ticket-audit/README.md` | O30, O33 | O30: sizes, 1.3 GB/512 datasets/141k routing objects, 12,431 accepted-only recoveries, 27.8k retention lines (§1, Raw-data risks, efficiency pass). O33: owner decisions table. |
| `docs/plans/simplification-plan-20261024.md` (all 969 lines) | O30 | Step 0 inputs and sizes (§2); WS lists; E1–E12 (§7); 1.09 GB catalog pair (WS10) |
| `batches/czsd/czsd-efficiency.md` | O16, O30 | S=1,298,420; B=1,036,256; 2.07M index rows; N=3,909,134; C=259–3,520/day; 763/696 GB; 260,834 PDFs; mean 672 KB |
| `batches/docspec/docspec-efficiency.md` | O32, O36 | COW rewrites; D1–D9 repeats; 11 commits/op; O(H²) lifecycle; 2 MiB cap; iceberg has no row-delta action |
| `batches/d8z3a/d8z3a-efficiency.md` (grep) | O31 | D = 1.24M rows; no "1.24M reads" claim found |
| `ds:Cargo.toml` | O1 | iceberg `=0.10.1` (:49), datafusion `=53.1.0` (:48), remote = rest catalog + opendal s3 (:30-37) |
| `ice:src/transaction/{mod,action,append,snapshot,expire_snapshots,update_schema}.rs`, `ice:src/catalog/mod.rs` | O2, O3, O4, O5, O35 | Public actions (mod.rs:135-170); `TransactionAction` pub(crate) (action.rs:37); `TableCommit` builder pub(crate) (catalog/mod.rs:350); `SetSnapshotRef` variant (catalog/mod.rs:541); expire is metadata-only (expire_snapshots.rs:34); `set_snapshot_properties` (append.rs:70); `RefSnapshotIdMatch` (append.rs:543); schema add/delete column only (update_schema.rs:137-147) |
| `ds:src/catalog.rs`, `ds:src/storage.rs` | O5, O10 | `fast_append` at catalog.rs:1150, storage.rs:871,906; retry re-base storage.rs:904-910; remote 2 MiB cap storage.rs:376-384 |
| `ds:src/model/{operations,transform}.rs` | O6, O7 | `RunSpec` single input + sql (operations.rs:46-62); `RefreshTransform` enum (transform.rs:281-293); `ConnectedComponentsTransform` (transform.rs:268) |
| `ds:src/engine/connected_components.rs`, `topology.rs`, `sha256.rs` | O7 | hard-coded `compute_document_id` (:27-36); validate fields (:39-48); body-edge by namespace (topology.rs:24-27) |
| `ds:src/engine/export.rs`, `export/pipeline.rs`, `export/remote.rs` | O8 | `HashingFile` blake3 (export.rs:658-662); writer props (pipeline.rs:676-700); sort (pipeline.rs:154-190); uuid stage files (:477) |
| `ds:src/storage/remote/objects.rs` | O9 | `if_not_exists(true)` (:535-538, :569-571); blake3 while uploading (:593-626); `verify` full GET (:648) |
| `ds:src/engine/retention/inventory/expand.rs` (counts) | O11 | 836 lines; 35 `starts_with("` prefix checks |
| `ds:src/storage/partitioning.rs`, `ds:src/engine/aggregation/*` | O12 | Year/Month/Day hand-computed (:94-157), Bucket via iceberg (:289); CollectSet UDAF |
| `ds:AGENTS.md`, `ds:docs/STATUS.md`, `ds:README.md` | O6, O13 | Iceberg-only lifecycle; do-once; "General incremental SQL is explicitly deferred"; single-input SQL |
| `retention/r2.py` | O15 | `IfNoneMatch='*'` (:378-379); Content-MD5 in `put_parameters` (:111-124); ETag check (:127-129); 412 on bodies returns False (:386-387); `put_file` (:424-444) |
| `retention/body_files.py`, `body_keys.py`, `pdf_backfill.py`, `raw_schemas.py`, `raw_values.py` | O16 | content-hash key, gzip stored (body_files.py:112-128,156); `.pdf` siblings (body_keys.py:62-67); `stored_sha256` schema (raw_schemas.py:24-27) |
| `retention/raw_archive.py` | O17, O18 | receipt key and immutable put (:517-523); record contents (:103-206) |
| `acquisition/raw_sync.py`, `transport/rust_fetch.py`, `transport/zyte.py`, `packages/source-fetch/main.rs` | O18, O19 | Python uploads bodies (raw_sync.py:398-419); response_headers recorded (rust_fetch.py:87); fetcher writes no R2 (main.rs:3) |
| `retention/raw_readings.py`, `raw_reading_inventory.py`, `archive_members.py` | O22 | readings = body-reader result parts under `indexes/processing/body-reader-results/` |
| `packages/congress_api/tests/historical_raw_catalog.py`, `docs/core-workflow-qualification.md:120-150` | O21 | oracle reads ~24,370 objects; explicit PDF readings; 38 min / 671k rows / 3.96 GiB |
| line counts: `retention/index/*`, `catalog_staging.py`, etc.; `parsers/**`, `models/**`; `house-naming`; capture path | O20 | 6,187 / 6,980 / 3,993 / 3,160 lines |
| `apps/site/src/components/explorer/reader/filenames/{catalog-v6,publication,reviews,recoveries,worker}.ts` | O23 | manifest v6; recovery and review descriptors; `savedCopyUrl` ext pdf/gz (catalog-v6.ts:39-47); fixed pointer URL (publication.ts:2-3); API routes (worker.ts:29-45) |
| `retention/document_review*.py`, `saved_responses.py`, `viewer_publication/filename_reviews.py`, `filename_review_binding.py` | O24 | 943 lines; repo JSON input; `evidence/<sha>.<ext>`; review_sha256 binding |
| `.github/workflows/{capture-raw-sources,publish-filename-viewer,publish-explorer,update-data,deploy-pages,validate-explorer}.yml`, `raw-source-tables.md` | O25 | 360-min capture; 180-min publish on a 30-min cron; explicit dispatch of acquisition; 20k attempts / 5 h |
| `apps/committee_youtube/src/committee_explorer/parquet.py:400-440`, `publish-explorer.yml:34-55` | O26 | local stage paths; publishes to `pipeline-data` branch |
| `packages/corpus_recovery/src/**` (grep) | O27 | 1,700 lines; writes bodies/receipts; reads/writes `accepted.json` |
| `packages/news_lake/src/news_lake/storage/docspec/{client,lake}.py` (grep) | O28 | 9,238 lines; `release`, `compact_lifecycle`, exact pins |
| `infra/cloudflare/congressional-data-r2-edge.json` | O29 | custom domain, CORS, WAF allow/block prefixes, CSP |
| `viewer_publication/filename_exports.py:763-820` | O8 | two engine exports; manifest `published_at: now()` |

#### Artifacts NOT read, and why that is safe

- `batches/{d8z3b,kl2a1aa,mi03a,mi03b,standalone,syem}/*-efficiency.md` bodies (only grepped):
  the doc's load-bearing numbers trace to the README, the plan and czsd/docspec, which I
  read; the two numbers I could not source are reported as unverified (F13), not asserted.
- `ds:src/engine/write.rs`, `ds:src/engine/retention/**` internals: I rely on the audit's
  O(F)/O(H²) findings only as motivation (F13), not for any BLOCKER.
- `packages/news_lake/.../lake.py` in full and `viewer_publication/filename_native.py` in
  full: the finding about them (F6, F13) needs only the call sites and page shape, which I read.
- Cloudflare documentation: three facts are external knowledge, flagged "confirm" — R2
  conditional PUT `If-Match`/`If-None-Match`; bucket-lock rules by prefix with indefinite
  retention; bucket-scoped (not prefix-scoped) API tokens; the 14 GB runner disk.
- GitHub run history (`gh run list`): not queried (network rule); the "60 runs" claim is
  therefore unverified rather than refuted.

#### Hypotheses

- H1 (engine supports what the doc assumes): REFINED — `fast_append`, CC, export and
  lifecycle records exist; "replace table" is absent *and* not buildable on the public
  0.10.1 API; tags and physical expiry likewise; multi-table SQL is absent (O2–O6).
- H2 (sizes and costs are sourced): CONFIRMED for every number except "1.24M small reads"
  and "60 runs" (O30, O31).
- H3 (raw writers already create-only with Content-MD5): CONFIRMED (O15); what is new is
  sha256 metadata and byte-compare on 412.
- H4 (requirements dropped): CONFIRMED for reviews and news_lake; recoveries and saved
  copies are covered but under-specified (O23, O24, O28).

### 1. Artifact summary

- **Path:** `docs/engine-first-architecture.md` (status: proposed, 2026-10-24, owner Mike Deeb)
- **Stated problem:** four custom Python layers between raw files and the browser, each
  "incremental" yet touching everything; explorer down (§1).
- **Stated decision:** append-only raw log; recompute every derived table per run as SQL in
  docspec-rs; content-addressed export behind one pointer; readings the only incremental step (Summary, §4).
- **Category:** ops scaffolding that carries a product surface (the explorer).
- **Subsystems touched:** raw capture (`retention/`, `acquisition/`), docspec-rs engine,
  viewer publication, site reader, workflows, R2 edge config.
- **Prior artifacts cited:** audit README, simplification plan, `export-pins`, ticket ct-st8m.
- **Should have cited:** `ds:docs/STATUS.md` (SQL scope), the iceberg 0.10.1 transaction
  surface, `packages/news_lake` (decision 2), the reviews reader/publisher, `corpus_recovery`.
- **Implementation status:** pre-implementation.

PREMISES
- P1: Four incremental layers pay full-rebuild cost with more complexity (§1).
- P2: Full recompute in SQL on docspec-rs, steps 1–4, with "replace table" for the model (§4, §4.4).
- P3: Data is small (~4M rows); recompute is seconds–minutes (Summary, §9).
- P4: iceberg 0.10.1's `fast_append`-only limit "does not bind" because tables are appended or replaced (§6).
- P5: The engine already supplies `fast_append`, ConnectedComponents, export, content hashing (§6 Keep).
- P6: The `document_id` expression moves from engine to SQL (§4.4, §6 Remove 4).
- P7: Release pins become Iceberg tags; retention becomes snapshot expiry (§6 Add 4).
- P8: Each item is handled once; platform primitives over hand-built ones (§2 goal 4).
- P9: Daily capture-to-live under 45 minutes; a broken release never goes live (§2 goals 3, 6).
- P10: Receipts are the source of truth; everything derived rebuilds from receipts, bodies, provenance (§4.1).
- P11: Steps are keyed by input snapshot IDs plus code/SQL digest (§4.4, §5).
- P12: Phase 2 exit: every body has a reading for the current parser version (§11).
- P13: 1.5–2 weeks of focused work (§11).
- P14: Viewer prep does ~1.24M small reads; the hosted publish failed its last 60 runs (§1).

### 2. Lineage and relationships

| Prior artifact | Type | Relation | Citation |
|---|---|---|---|
| Audit README | parent | supplies the diagnosis, sizes and owner decisions | `docs/reviews/2026-10-24-ticket-audit/README.md` |
| Simplification plan | sibling (superseded in part) | Step 0 + WS6/WS7/WS9 cover the same ground incrementally; the doc replaces WS7's "engine-native incremental" with full recompute | `docs/plans/simplification-plan-20261024.md` §2, WS7 |
| czsd / docspec efficiency passes | grandparent evidence | the O(S+B) and COW findings the doc's bet rests on | `batches/czsd/czsd-efficiency.md` §1; `batches/docspec/docspec-efficiency.md` §4 |
| `ds:AGENTS.md`, `ds:docs/STATUS.md` | constraint the parent inherits | Iceberg-only lifecycle; general SQL deferred | O6, O13 |
| `export-pins` route | implementation lineage | the publish shape the doc finishes | `viewer_publication/filename_exports.py:763-820` |

| Component / seam | Owner | Depends on | Depended on by | Seam named? |
|---|---|---|---|---|
| Raw prefixes (`bodies/`, `receipts/`, `provenance/`) | congressional-tech capture + corpus_recovery | R2 create-only, bucket lock | engine captures step, weekly verifier, site saved copies | yes — doc §4.1 (corpus_recovery missing) |
| `raw.captures`, `derived.readings` | docspec-rs | receipts LIST, parsers | model SQL | partly — HWM seam unsafe (F4) |
| Model SQL → export | congressional-tech SQL files, docspec-rs executor | the two tables + provenance | release manifest, site | **no** — the engine primitive is unnamed (F1) |
| Release manifest + pointer | docspec-rs export, publisher | content-addressed objects | site reader, canary | yes — §4.5 |
| Site reader contract | apps/site | manifest `schema_version` | users | yes — §4.6, but reviews/recoveries absent (F6) |
| Capture ← `url_state` | capture (Python) | previous run's model | — | **no** — how capture reads `url_state` is unstated |
| news_lake ← engine lifecycle | news_lake | `release`, `compact_lifecycle` | — | **no** — contradicted by §6 Remove 1 (F6) |

**Stated intent vs actual shape:** MAJOR divergence on P2/P4/P7 (F1, F2): the doc's shape
requires engine and library primitives that do not exist and cannot be added on the pinned
library's public API; MINOR on P12/P13 (F3) and P14 (F13).

### 3. Invariants and commitments

```
INVARIANT 1: Raw prefixes are create-only; nothing overwrites or deletes them.
  Source: audit README owner decisions; doc §4.1.           Status: NEWLY-INTRODUCED (platform lock); today code-only (r2.py:378-379).
  Failure: a stale engine or derived writer writes raw (README risk 2). Exercised by Phases 1–5 before the lock (F8).

INVARIANT 2: Receipts are the single source of truth for captures.
  Source: doc §4.1; plan Step 0 Run A is the check.         Status: RELIED-UPON, not yet verified.
  Failure: facts only in indexes/ or accepted.json (README risk 6). Exercised by Phase 1 exit; F4 weakens it daily.

INVARIANT 3: Engine first; no application code overlapping docspec-rs.
  Source: README owner decisions.                            Status: RELIED-UPON; the ~14k lines of capture, parsers and vocabulary stay in Python (no overlap), but the model needs an engine primitive that is absent (F1).

INVARIANT 4: Durable per-step commits with resume after a crash.
  Source: README owner decision 1.                           Status: PRESERVED at step granularity; BROKEN inside a multi-job readings pass unless batched (F3).

INVARIANT 5: Publishing is a content-addressed export plus one pointer flip.
  Source: README owner decision 3.                           Status: PRESERVED (§4.5).

INVARIANT 6: Reader accepts schema N and N-1.
  Source: doc §4.6.                                          Status: NEWLY-INTRODUCED; today v6 only (README: v5 decoder deleted).

INVARIANT 7: Do each action once.
  Source: user doctrine; ds:AGENTS.md "Do something once".   Status: PRESERVED in the pipeline; BROKEN by the weekly full-body hash (F7).

INVARIANT 8: Iceberg-only lifecycle in the engine.
  Source: ds:AGENTS.md.                                      Status: RELIED-UPON; the doc's tags/expiry plan honours it in spirit but the library cannot deliver it (F2).
```

### 4. User-value analysis

- **User-visible outcome:** the explorer comes back and updates daily; a broken release can
  never go live. Real and currently unmet (the viewer is down).
- **Beneficiary:** explorer users; the owner as sole operator.
- **Debt added:** one new engine primitive (SQL over N tables → export); versioned SQL files;
  a release GC; batched readings backfill.
- **Debt paid down:** raw-index leaves and routing (1.3 GB/day), the incremental catalog
  (9.2k lines), journals/resume/custody (1.5k lines), the engine lifecycle store and
  test-util branches.
- **Category:** ops scaffolding carrying a product surface.
- **Falsifiability:** six months on, if the daily publish chain exceeds 45 minutes, or if
  any receipt-derived fact disagrees with a weekly rebuild, or if a release reached the
  pointer without passing the canary, the design failed its claims.
- **Smaller shapes considered:** (a) model straight to export, Iceberg only for the log —
  **adopted here** (F2); (b) plain Parquet everywhere incl. captures — rejected: appends
  need atomic commit, and `fast_append` gives it cheaply; (c) DuckDB — rejected by owner.
- **Greenfield-first:** YES for the raw contract and the release; NO for "model as Iceberg
  table with replace", which exists only to reuse the engine's Iceberg habit.

### 5. Counterfactual analysis

- **Kill criterion:** the §9 measurement exceeds 15 minutes on the hosted runner *after*
  the SQL→export primitive exists; or receipts prove unable to reproduce today's capture
  and state tables (Phase 1 exit).
- **Counter-decision shape:** engine-native incremental merges (plan WS7) — copy-on-write
  rewrites hash-distributed tables wholesale in iceberg 0.10.1 (docspec-efficiency §4 item 1),
  so it is slower and more complex at this scale. The doc is right to reject it.
- **Removal probe:** without this doc, the plan's WS6+WS7 proceed; the viewer still returns
  on WS6, but 9.2k lines of incremental Python are replaced by engine incremental updates
  that the audit shows are O(R) per day.
- **Sibling subsumption:** PARTIAL — the simplification plan already contains Step 0, WS6
  (export-pins) and WS9 (engine cuts); the doc should say which WS rows it supersedes.
- **Six-month critic:** "Why is there a `replace table` patch to iceberg-rust and a
  table-per-day warehouse when the only consumer of the model is a Parquet export?"

```
OPPOSITE-VERDICT PROBE (APPROVE as written):
  Evidence that would exist: an engine operation executing SQL over several Iceberg tables; a public
  iceberg 0.10.1 action that replaces a table's files or sets a snapshot ref.
  Searched for: ds:src/model/operations.rs, ds:src/model/transform.rs, ds:docs/STATUS.md, ds:README.md,
    ds:src/engine/refresh/*, ds:src/engine/sql_validation.rs; ice:src/transaction/{mod,action,snapshot}.rs,
    ice:src/catalog/mod.rs.
  Found: single-input RunSpec.sql (operations.rs:46-62); typed RefreshTransform (transform.rs:281-293);
    "General incremental SQL is explicitly deferred" (STATUS.md); Transaction actions list without
    overwrite/replace/refs (mod.rs:135-170); TransactionAction pub(crate) (action.rs:37); TableCommit
    builder pub(crate) (catalog/mod.rs:350).
  Conclusion: REFUTED for APPROVE. Also probed REJECT (no reshape preserves intent): the
    "model → export, Iceberg for the log" reshape preserves every §2 goal and every §3 decision,
    so REJECT does not hold.
```

### 7. Verdict

```
VERDICT: RECONSIDER — by D2

Justification:
  - Intent vs. shape: DIVERGES — FINDING 1, FINDING 2 (O2, O3, O4, O6; P2, P4, P7)
  - User-value claim: SUPPORTED for the bet, WEAK on cost — FINDING 3 (O21, O16; P12, P13)
  - Commitment status: DRIFTING — INVARIANT 4 (F3), INVARIANT 7 (F7), INVARIANT 1 ordering (F8)
  - Conceptual debt delta: PAYS DOWN overall; ACCRETES without GC — FINDING 5
  - Sibling subsumption: PARTIAL — simplification plan Step 0 / WS6 / WS9
  - Opposite-verdict probe: REFUTED
  - Confidence: HIGH on engine and library facts (source read); MEDIUM on cost estimates (reasoned, not run)

Required reshape:
  1. §4.4/§6: replace "replace table" + "multi-table export" with one primitive — SQL over N
     named Iceberg tables and provenance, written directly as the content-addressed export.
     Iceberg stays only for raw.captures and derived.readings.
  2. §4.2: LIST receipts and anti-join on receipt_key; dedupe on (receipt_key, receipt_line).
  3. §4.3/§11: batched readings appends; Phase 2 exit scoped to bodies the model consumes;
     full-corpus parse as a measured multi-job backfill.
  4. §4.5/§8: keep last K releases and delete unreferenced objects; snapshot expiry plus a
     reachability sweep for the two append tables.
  5. §4.6/§6/Appendix: classify reviews (decisions → provenance, renders → export objects);
     sequence news_lake before removing release/compact_lifecycle; list corpus_recovery.
  6. §11 Phase 0: bucket lock enabled and read back, read-only token, then the DataFusion measurement.
```
