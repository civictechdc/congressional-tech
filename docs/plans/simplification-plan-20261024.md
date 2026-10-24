# Simplification plan: congressional-tech and docspec-rs

Date: 2026-10-24. Source: `docs/reviews/2026-10-24-ticket-audit/` (README and `batches/*`).
Code read at congressional-tech `c858a5a2` and docspec-rs `d9c6719`; both are still HEAD.
Every line count is `wc -l` on tracked files at those commits. "At cut" means the number
is measured in the PR that makes the cut, because the code sits inside a larger file.
Nothing was run except reads, greps, `wc -l`, static import scans and `gh run list`.

## 1. Goal and constraints

**Goal.** Capture raw sources safely, rebuild everything else from them, and delete what a
rebuild makes unnecessary.

**What must survive.** Objects in R2 `congressional-tech-raw` under `bodies/` and
`receipts/`, and their provenance. Everything else can be rebuilt; nothing uses it yet.

**Owner decisions (binding):**

| # | Decision | Effect on this plan |
|---|---|---|
| 1 | Engine keeps durable per-phase commits and resume after a crash | Revert the deferred-commit mode (`b4b827d`). A "durable deferral" is per-phase commits with extra steps. |
| 2 | news_lake keeps the DocSpec backend | Port the crash, fence and merge tests, fix the two bugs, delete the PyIceberg oracle |
| 3 | Publishing moves to a finished `export-pins` route | Delete the journal, resume, attempt and preflight machinery |
| 4 | Raw protection is an R2 bucket lock on `receipts/`, `bodies/` and `provenance/`; one bucket | No derived-bucket work. The barriers are a code key policy plus the lock. |
| 5 | The `r2.dev` address stays open | Every key in the bucket is publicly readable, so the custom-domain WAF is not an exposure boundary |
| 6 | **Engine first:** congressional-tech always uses docspec-rs and keeps little or no custom code that overlaps it | Incremental updates move onto engine operations, and the Python incremental layer is deleted whatever Step 0 finds (WS7). Missing primitives are added to docspec-rs generically, never in congressional-tech. Duplicated engine behavior is a deletion target in every workstream. |

**Done on Oct 24** (commit `54a68ac7` and the audit README):
- P1: deleted `delete_gzip`.
- P2: hosted setup refuses an engine revision other than `QUALIFIED_DOCSPEC_RUNTIME`.
- P3: the capture schema carries `stored_sha256`.
- P5: checked `accepted.json`. 12,431 of its 24,028 recoveries exist only there; a
  write-once backup is in `provenance/recoveries/`.

**Owner action pending:** P4, the bucket lock on `receipts/`, `bodies/` and `provenance/`.

**Rules for every workstream:**
- One conceptual move per PR. Tests that pin the behavior land before the code moves.
  Behavior changes go in their own PRs.
- Run checks only through the project runners: `.venv/bin/python scripts/dev.py test <lane>`
  (lanes include `production-offline` and `native-loopback`) and docspec-rs `scripts/check`.
  Never use a tool from `PATH`. Say this in every agent and reviewer brief.
- Work in a separate worktree and venv. The primary checkout backs live recovery jobs.
- Report before and after `wc -l` in every PR that deletes code.
- Honor the keep list (Section 4).

**Raw check ("R-check"), referenced by every workstream:**
1. Before and after each merge, list `receipts/` and `bodies/` read-only
   (`rclone lsjson -R --hash`, read-only R2 token). Every earlier key must still be there
   with the same size and hash; only additions are allowed.
2. Every `receipt_key` in the capture index exists. This is the audit's 2,289-of-2,289 check.
3. The raw invariant tests pass under `scripts/dev.py test production-offline`. Today these
   are `test_r2_archive_store`, `test_async_capture`, `test_r2_body_files`,
   `test_pdf_backfill`, `test_import_corpus_recovery_batch`, `test_recovery_guards` and
   `test_docspec_input_custody`. WS2 and WS3 add refusal tests.
4. After P4: read back the bucket-lock rules after any infra change.

A PR that touches none of the raw-writing modules needs only checks 1 and 2. Those modules
are `retention/{r2,raw_archive,raw_storage,body_files,partition_routing,raw_state_routes,immutable_metadata}.py`,
`acquisition/raw_sync.py`, `corpus_recovery/transfer.py` and `docspec_client`.

## 2. Step 0: measure the full rebuild from raw

**Question.** How long does a full rebuild from raw take, and does it reproduce today's catalog? Under decision 6 this no longer decides whether the Python incremental layer survives; it is deleted either way. The rebuild becomes the correctness oracle and recovery tool, and the cost baseline that engine-native incremental updates (WS7) must beat.
The retention package is 27,800 lines. Of those, 9,248 are incremental-only (WS7).

**Entry points that already exist. Use them; don't write a new harness.**
- The oracle is `packages/congress_api/tests/historical_raw_catalog.py` (283 lines) plus
  `historical_catalog_lineage.py` (120). The brief's `tests/historical_raw_catalog.py`
  means this file. It reads `indexes/captures.parquet`, `indexes/download-state.parquet`,
  receipts and page bodies, and writes the filenames/documents pair.
- The harness is `scripts/measure/benchmark_core_rebuild.py` (507 lines). It runs the
  oracle against a read-only mirror and sends writes to an output overlay. It records:
  - elapsed and per-stage time;
  - reads and bytes per key family;
  - Linux process-tree memory (RSS) every 250 ms, and scratch disk.

  It then compares the output with a reference pair by hashing whole canonical records
  (`--compare-only`). Its usage is documented at `docs/core-workflow-qualification.md:46-145`.
- Production refuses a full rebuild today: `cli/raw_sync.py:373-374` and
  `cli/document_index.py:41-42`.
- Two fixes are needed before running (found by reading; not run):
  - `benchmark_core_rebuild.py:30` puts the repo-root `tests/` on `sys.path`, but the oracle
    moved to `packages/congress_api/tests/`. Set `PYTHONPATH=packages/congress_api/tests`
    or fix the line.
  - The documented command `-m scripts.benchmark_core_rebuild` is stale. The file is now
    `scripts/measure/benchmark_core_rebuild.py`.

**Prior evidence. It informs Step 0 but does not replace it.**
- Oct 4 rebuild: 671,035 filename rows in 2,285 s (38 min), with 3.96 GiB sampled memory,
  on 2 workers, 3 CPUs and a 10 GiB container (`docs/core-workflow-qualification.md:129-145`).
  It read 24,370 objects, not every body.
- Today's corpus has 1,683,430 filename rows and 1,241,157 documents, 2.5 times as many.
  Linear scaling would put the rebuild near 95 min. That is an extrapolation, not a
  measurement.
- Today's daily cost: the last successful scheduled capture plus incremental update
  (Oct 20, run `39395557565`) took 11.4 min for the whole workflow.

**Inputs.** All are pinned and read-only. There have been no new captures since about
Oct 19.

| Input | Key | Size | Pin |
|---|---|---|---|
| Captures | `indexes/captures.parquet` | 282,900,803 B, 3,909,134 rows | sha256 `db033173…` (`output/incremental-updates-20261019/adoption-inputs/captures-receipt.json`) |
| State | `indexes/download-state.parquet` | 97,042,360 B | sha256 `79b0473c…` (`state-receipt.json`) |
| Receipts | `receipts/` | 2,289 objects, 1.08 GB | audit listing |
| Page bodies | `bodies/sha256/…` | read set recorded by the harness | — |
| Reference A | `catalog-generations/596f08fa…/` (legacy pair) | 1,683,430 / 1,241,157 rows | sha256 `2af2dbdb…`, `f0bf8fb6…` |
| Reference B | the selected incremental catalog, materialized with `read_catalog(store, native=…)` | — | selector identity |

- The mirror must hold raw inputs only, with no `indexes/catalog.json` or earlier catalog
  tables. When a previous catalog is present, the oracle reads it
  (`historical_raw_catalog.py:96`), restores its source metadata (`:164-187`) and archives
  it (`:271-279`). A true rebuild must not see derived data.
- Use the seed files whose digest matches reference A's `seed_digest` metadata.
- If the engine will not start with a read-only token, skip reference B and record that.

**Runs:**

| Run | What | What it decides |
|---|---|---|
| A | Replay every `receipts/` line through the existing `apply`/`add_index` (`raw_archive.py:536-584`, the code the orphan-receipt path uses at `:670-677`) into capture and state tables. Compare all columns, as row multisets, with the pinned tables and with the native raw selection. Time it. | Whether the raw index can be derived from receipts (feeds Q3). If those methods need a native selection, a short loop over them in `scripts/measure` is the only new code. Note that `apply` backfills `stored_sha256` from `sha256` (`:546-547`), the P3 bug. |
| B1 | Harness with `--repair`, `PYTEST_CURRENT_TEST` unset | The timing of record |
| B2 | Same, with `PYTEST_CURRENT_TEST=1`; compare with B1 using `--compare-only` | 21 pytest-only branches sit in modules the rebuild runs (WS1). An output difference means a production-only branch changes data. A time difference shows what the speed branches are worth. |
| B3 | Only if B1 misses the bar: `py-spy record` on B1 | The one obvious bottleneck. So far, slow paths were repeated work. |
| C | Compare B1 with references A and B, and classify every differing field. (i) A rule change since the reference: fine. (ii) An incremental-engine error: the rebuild wins. (iii) A fact that exists only in earlier derived tables, such as restored previous metadata or `catalog-history/`: a blocker (open question 8). | Whether derived tables hold anything raw lacks |

**Where to run:**
1. Locally, for profiling:
   - Use a separate worktree and venv, launched as its own launchd job after checking load
     and swap. Take the shared Docker lock if it runs in a container.
   - For the first run, mount the bucket read-only (`rclone mount --read-only`, read-only
     token) to record the read set.
   - Then `rclone copy --files-from` that read set for repeats with no network.
2. The run that decides: a `workflow_dispatch` job on `ubuntu-24.04`, the capture job's
   runner class. The repo is public. Record `nproc`, `free -g` and `df -h` in the report.
   Read R2 with a read-only token and write only to runner disk.

Owner action: create a bucket-scoped, read-only R2 token for these runs.

**What the result decides (decision 6):** the Python incremental layer is deleted either way
(WS7). The rebuild result sets three things:
- **Oracle:** comparison C must find no class (iii) difference before WS7 deletes anything.
  A class (iii) difference blocks deletion until the owner answers open question 8.
- **Recovery:** the rebuild must fit the 360-min hosted job and runner memory, or it is
  profiled once (run B3) and fixed in the rebuild path.
- **Baseline:** runs A and B1 give the cost that WS7's engine-native incremental update
  must beat by a clear margin. That justifies incremental updates at all; otherwise the
  daily update is the rebuild.
- **Re-run B1** when filename rows double. A rebuild costs O(corpus) per run; an
  engine-native incremental update should cost O(changes).

**Raw safety during Step 0.** Writes are impossible with a read-only token and a read-only
mount, and outputs stay on local disk. Run R-check 1 before and after.

## 3. Workstreams in dependency order

| WS | Workstream | Depends on | Start |
|---|---|---|---|
| 1 | Test/production divergence | — (engine half before any pin bump) | now, beside Step 0 |
| 2 | One owner for raw write rules | P1; P4 in parallel | now |
| 3 | Custody client: fallbacks, then one owner | engine pre-admission change ships with WS9's pin bump | now (tests) |
| 4 | Provenance pinning | — | now; before WS10 |
| 5 | WAF allowlist single source | WS6's release key layout | now |
| 6 | Finish export-pins; delete the journal and resume route | WS2 steps 1–2; P5 | after WS2 step 2 |
| 7 | Move incremental updates onto the engine (decision 6) | Step 0; WS6; WS9 primitives | after both |
| 8 | news_lake under decision 2 | engine pin | now |
| 9 | docspec-rs cuts | WS1's engine half | after it |
| 10 | Shims and legacy formats | WS4; WS6 | after both |
| 11 | Browser and performance freeze | — | now |
| 12 | Ticket process | — | now |

### WS1. Test/production divergence

**Addresses:**
- Hotspot 1; raw risks 4 and 7.
- The ct-2ukk commits (`48137619`, `6c5712c1`, `017eb2cc`, `a8ddaa8f`, `93a63e1d`,
  `e4b3216b`, `f5e8fe1b`).
- docspec-rs `b4b827d`, `97373eb` and `d05df4d`.

**Python: 75 `PYTEST_CURRENT_TEST` sites in 24 modules** (`git grep -c`).

| Group | Sites | Where |
|---|---:|---|
| Raw-adjacent; survives any Step 0 outcome | 3 | `raw_storage.py:655-672` reads the Oct 20 `output/…/state.parquet` when its row count matches and swallows errors; it fires on the live checkout. `partition_routing.py:80-84,146-163` adds a page cache and batched uploads of raw routing pages that only production runs. |
| Rebuild path; survives | 21 | catalog_staging 10, index/records 4, index/sources 2, source_inputs 2, document_recovery 1, index/document_sources 1, index/lifecycle 1 |
| Incremental-only | 51 | 15 modules, deleted by WS7 (decision 6) |

**First move:**
1. Add a characterization test for `iter_states_for` with more than 512 URLs, asserting the
   exact rows and `STATE_ORDER` ordering.
2. Delete `raw_storage.py:655-672`.
3. In the same PR series, delete the other two success-shaped substitutions keyed on row
   counts: `source_capture_inputs.py:61-74` (a cache stands in for receipts) and
   `catalog_raw_updates.py:155-183` (local adoption inputs).

**Then:**
- Add a ratchet test that counts `PYTEST_CURRENT_TEST` in `packages/*/src` and fails if the
  count rises. Lower the limit in every PR until it reaches 0.
- In `partition_routing.py`, make batched upload the only path, and test it, including the
  final flush at `:200-202`.
- Settle the 21 rebuild-path sites from Step 0's B1/B2 comparison:
  - If the output differs, add a contract test and keep one behavior.
  - If only speed differs, make it an explicit parameter that both tests and production set
    (batch size, in-memory maps).
- The 51 incremental-only sites go with WS7. Until then, treat them like the others,
  starting with `catalog_adoption.py:134-137`. There, production sets
  `actual = expected`, so it hashes the source against itself.

**Engine: 60 production-only `cfg` sites in 14 files.**
- Counts: `catalog.rs` 20, `pipeline.rs` 10, `storage.rs` 8, `storage/pinned.rs` 5,
  `remote/objects.rs` 3, `engine.rs` 3, `write/build.rs` 2, `release_check.rs` 2, six files
  with 1 each.
- One of them, `export/pipeline.rs:608`, is `cfg(not(feature="test-util"))`.
- congressional-tech pins `c949c67`, which has 1 such site.

Moves, in order:
1. **Delete the dataset-name predicates.** Nothing depends on them, because they came after
   the pin.
   - `pipeline.rs:317-335` records a remote input reference without uploading it, for
     datasets named `raw-`, `catalog-`, `obs-` or `source-observations-`.
   - `pipeline/completion.rs:234-237` and `write/build.rs:362-372`.
   - `release_check.rs:86-93,226-229` skip verification by name.
2. **Revert the deferral (decision 1):** `catalog.rs:765-790`, `pipeline.rs:510-518`, the
   discarded flush at `pipeline.rs:111-112`, and the test-only `GuardedCatalog` reload at
   `catalog.rs:696-700`. One protocol remains: durable per-phase commits.
3. Reduce every remaining site to one behavior.

Evidence:
- Add to `scripts/check` one integration run without `--all-features`
  (`cargo test --locked --test integration`). Integration tests compile the library
  without `cfg(test)`, so production code actually runs.
- Measure a remote raw-leaf Build (catalog commit count, wall time) before and after the
  revert. If per-phase commits prove too slow, the fix is the app's one-dataset-per-leaf
  layout (`raw_storage.py:1058-1075`), not deferral (Q6).

**Delete:** 61 lines of raw substitution: 18 in `raw_storage`, and 43 in modules WS7 may
delete anyway. The 75 and 60 sites go to 0; their line totals are counted at cut.
**Replace with:** one code path, with explicit parameters.
**Raw check:** R-check 1–3. After the engine revert and the next pin bump, deep release
verification must pass for `raw-*` datasets, which shows their inputs were really uploaded.
**Depends on:** nothing. The app's engine pin must not move past `c949c67` until the engine
half lands; P2 enforces the pin.

### WS2. One owner for raw write rules

**Addresses:**
- Hotspot 2; raw risks 1, 4 and 5.
- d8z3b H1, kl2a1aa H2, czsd hotspot 2, syem hotspots 4 and 6, mi03a H4, mi03b H3.
- ct-te1p, ct-ec91, ct-a70m, ct-dmca.

**Current model:**
- **Five write entry points, each with an `immutable` flag:**
  - `R2Store.put` (`r2.py:338-397`) writes unconditionally outside `indexes/` when
    `immutable=False`.
  - `put_file` (`:407-444`) and `put_pdf_body` (`:401-406`).
  - `AsyncBodies.put` (`:150-161`).
  - `LocalStore.put` (`catalog_cache.py:84-110`).
- **Prefix rules are restated** in viewer `client.py:62-64,128-131`, `derived_files.py:18`
  and `index_selector.py:4-8`.
- **A 412 counts as success without a byte check** (`r2.py:386-387,436-440`).
- **Collision checks are copied three times**: `raw_archive.py:381-383`,
  `acquisition/raw_sync.py:412-415` and `body_files.py:137-140`. PDFs have none
  (`r2.py:388-391`).
- **Ingest flags are probed everywhere:** `excluded_body_hashes` and
  `store_uncompressed_pdfs` appear 40 times in 7 source files. A missing exclusion file
  returns an empty set (`raw_storage.py:134-137`), so the gate fails open.
- **There are two PDF migration paths.**
- **Verification reads can come from a local cache** (`r2.py:247-278`; `cache_dir` is set at
  `cli/raw_sync.py:323`).

**First move (after P1).** Add a parametrized test over
{`put`, `put_file`, `put_pdf_body`, `AsyncBodies.put`, `LocalStore.put`,
`GuardedPublicationClient.put_object`} × {`bodies/`, `receipts/`, `quarantine/`,
`indexes/raw.json`}. It asserts that a write that is not create-only is refused before any
I/O, and that no unconditional `put_object` is sent. It characterizes today's behavior,
because every raw caller passes `immutable=True`.

**Steps:**
1. One namespace-policy function maps a key to `create_only`, `cas_selector`,
   `mutable_status` or `derived`. Every adapter and the publication client consult it, and
   the `immutable` argument goes away. Raw prefixes are always create-only.
2. One verifier for existing objects. On a 412 for a raw key, compare size and stored
   sha256 (or the ETag MD5) before reporting "already retained", for `.gz` and `.pdf` alike.
   Route the three copies through it.
   - Write this test first: a PDF collision with different bytes fails.
   - This is a behavior change. Put it in its own PR, and update
     `test_r2_archive_store.py:84-105`, `test_r2_body_files.py:50-63` and
     `test_async_capture_native.py:261` deliberately.
3. Set ingest policy once, where `raw_sync` constructs the store, and delete the per-layer
   probes. Exclusions and PDF siblings are open (Q2).
4. Make raw-key reads used for verification skip the local cache.
5. Fold `migrate_pdf_bodies_to_uncompressed` (`raw_storage.py:280-363`, 84 lines; after P1)
   into `backfill_uncompressed_pdfs` (`pdf_backfill.py:159`).
6. **Retention planner (third-pass call):**
   - Add a guard test first: no Python path calls `/retention/removal/execute` or deletes
     under raw prefixes. It passes today.
   - Delete the reclaim classification and the `removal_id` branch of
     `plan_protected_retention` (`native_capacity.py:430-576`, 147 lines). Keep
     `inspect_operator_status`.
   - Rewrite `test_native_capacity.py:~314-333`, which asserts that an unknown object is
     reclaimable.
7. **Raw-state schema (ct-dmca, third-pass call):** fill missing fields at read time and
   never republish `indexes/raw.json` just to change a schema. If the engine is kept,
   delete the default scalar backfills (`catalog_raw_updates.py:96-135,707-721`). Decide
   whether an old `links_scanned` means False or NULL before keeping
   `test_catalog_raw_updates.py:~565`.
8. **`VerifiedFile`:** the positional constructor must hash or refuse
   (`custody.py:66-83,99-100`). Test that `VerifiedFile(p, wrong_sha, size).require(p)`
   raises.
   - Delete the unused `congress_shared.custody.copy_checked` (`custody.py:372-462`, 91
     lines).
   - Keep `derived_files.copy_checked`, which owns a different policy (syem hotspot 6).
9. Make the hand-written body-layout writers call
   `physical_body_object_key`/`put_body`: `committee_explorer/parquet.py:406-428`, senate
   `seed_fetch`, and the e2e harness.
10. **One-time read-only check (kl2a1aa H3):** look for `.pdf` keys in the raw-bodies
    routing index written between Oct 22 20:16 and Oct 23 18:44.

**Delete:** 345 lines certain (84 + 147 + 91 + 23). If Q2 says no exclusion list will
exist, also delete the exclusion gate at `raw_storage.py:75-236` (162 lines). The per-layer
probes are counted at cut.
**Replace with:** one policy function, one verifier, ingest policy set at the store, and the
P4 bucket lock as the platform barrier.
**Raw check:** R-check 1–4, plus the refusal matrix.
**Depends on:** P1 before step 5. P4 runs in parallel.

### WS3. Custody client: delete fallbacks first, then one owner

**Addresses:**
- Hotspots 4 and 5; raw risk 5.
- mi03a H2, mi03b H1–H2, syem hotspot 2, standalone H5.
- ct-3faj, ct-m9td, ct-q968, ct-xq1y, ct-nmjc, ct-0n0y.

**Current model:**
- **Three copies of stage, submit, then retain or delete:** `run_table`
  (`client.py:445-579`), `update_table` (`:619-798`) and `update_evidence_table`
  (`:842-916`), 390 lines in all.
- **Fallbacks that change what a request means:**
  - 415 falls back to Parquet (`:478`, `:683`).
  - An "unknown field" error strips `partition_by` (`:516-521`) or `merge` (`:734`).
  - `operation_conflict` rewrites the input with legacy row groups (`:522-533`; mode in
    `transport.py:142-185`).
  - "Transient" retries match on substrings (`:534-552`, `:757-770`), with a no-op
    `attempt += 1`.
- **Raw-path retries on `TypeError`** drop `partition_by` (`raw_storage.py:1065-1074`) or
  `merge` (`:1226-1234`). The second turns LATEST_OR_BACKFILL into plain key replacement on
  provenance rows.
- **`pre_admission` comes from the error kind** (engine `error.rs:173` to
  `http.rs:277-286`), and the client mirrors it in `models.py:27-56`.
- **Three binary resolvers:** the `binary.py:20-43` search ladder, a silent fallback at
  `client.py:105-110`, and news_lake's own.

**Order:** fallbacks first, then merge the copies (README hotspot 5, mi03b). syem argued for
collapsing the copies first; the brief settles it.

**First move: tests, which fail today.**
- `_request` is called exactly once for every unknown-outcome error. The stubs in
  `test_docspec_input_custody.py` never count calls.
- An unknown field surfaces as a failure.
- `update_evidence_table` has a custody test.
- A schema-evolved raw-state update sends `merge`.
- A native-loopback test feeds real engine refusal bodies through `cleanup_safe`, including
  a post-admission `invalid_json`.
- Fix the red `test_read_arrow_pin_and_header_verification`, which builds the client with
  `__new__`.

**Steps:**
1. Delete every fallback above. This is pure deletion: one engine is pinned and there are no
   old attempts to resume.
2. Collapse the three copies into one owner: stage, submit once, and keep the input unless
   it was refused. `cleanup_safe` (`:62-72`) stays the single decision point.
3. Engine: set `pre_admission` at the admission point. Errors before the admission commit
   are pre-admission; all others are not. Add a test that a post-admission failure reports
   false; today only `http/tests.rs:294` exists. Then the client keeps inputs on any error
   unless `pre_admission` is true, and `models.py:27-56` is deleted.
4. Producer Parquet: keep one byte-targeted row-group mode, or none if the engine's split
   (`c937ef8`/`c949c67`) is enough. Decide with a native-loopback test of a large table at
   `max_batch_bytes=4 MiB`.
5. Refuse IPC (`run_ipc`/`update_ipc`, which have no custody) for raw writers. Only news
   uses IPC (`lake.py:68,424`).
6. Keep one binary resolver: an explicit binary whose digest matches, outside tests. Delete
   the search ladder and the silent fallback. Test-only resolution moves into conftest.

**Delete:** `models.py:27-56` (30 lines) certain. The fallback branches, the legacy sizing
mode, the `TypeError` retries and the consolidated copies are counted at cut.
**Replace with:** one submission owner and an engine-supplied `pre_admission`.
**Raw check:** R-check 1–3, plus the custody tests.
**Depends on:** steps 1–2 can land on the `c949c67` pin. Step 3 needs an engine change, so it
ships with WS9's single pin bump.

### WS4. Provenance pinning

**Addresses:**
- Hotspot 6.
- standalone H1 and H6, d8z3b H3, czsd's fingerprint finding, d8z3a H3.
- ct-esm4, ct-ma8a, ct-r46l, ct-o24q, ct-unv0, ct-4r1c.

**Current model:**
- **The recovery import pins code from a hand list** (`dispatch_corpus_recovery_import.py:107-122`):
  `congress_api/src` plus seven named modules. It misses `docspec_client` and
  `congress_shared` custody and storage, which is the code that writes raw datasets and
  `indexes/raw.json`.
- **The catalog fingerprints hash shims:** `source_fingerprint()` (`catalog_cache.py:233-261`)
  and `source_update_requirements()` (`source_update_proof.py:14-23`) hash the 60-line
  `document_index.py` re-export and the 25-line `raw_catalog.py` facade, not `index/*`. So
  changes to interpretation code no longer invalidate reused derived results. The oracle
  also calls `source_fingerprint` (`historical_raw_catalog.py:124`).

**First move.** Replace the self-referential test
(`scripts/corpus_recovery/tests/test_dispatch_corpus_recovery_import.py:111-117`, which
checks only the modules it names) with a completeness test: every repo-owned module loaded
during an import dry run is covered by the pin.

**Then:**
- One `code_identity()` helper, used by the import pin and both fingerprints.
  - Reviewers split. standalone's third pass would reuse the publication dispatcher's
    folder digest (`SelectedRuntime.PACKAGES`); d8z3b and standalone H6 prefer the git tree
    hash.
  - Recommendation: the git HEAD tree hash, plus the `uv.lock` digest, plus a refusal when
    `packages/` or `scripts/` has uncommitted changes. That leaves no list to drift. Use the
    folder digest only if imports must run from a dirty live checkout (Q4).
- Recovery admission (d8z3a H3): validate the event shape once, where events are parsed
  (`admission.py:75-95`), and normalize pin keys. Tighten the 7-case test
  (`test_dispatch_corpus_recovery_publication.py:286-303`) to assert which check fired.

**Delete:** the hand list and its test lines, counted at cut. The release identity goes in
WS6.
**Replace with:** one helper.
**Raw check:** R-check 1–3, since the import path writes raw data. A dry-run import must show
that the identity covers `docspec_client`.
**Depends on:** must land before WS10 deletes `document_index.py` and `raw_catalog.py`. If
the folder digest wins, extract it before WS6 deletes `SelectedRuntime`.

### WS5. WAF allowlist single source

**Addresses:** hotspot 7; kl2a1aa H1; ct-te1p, ct-84xa, ct-1qbq.

**Context (decision 5).** `r2.dev` serves every key, so the custom-domain rule does not
protect the bucket. This workstream is about one source of truth and an `apply` that can't
wipe other rules, not about exposure.

**Current model:**
- The deployed expression (`infra/cloudflare/congressional-data-r2-edge.json:35`) allows
  any `/viewer-publications/*` except `accepted-*`, and any `/exports/*`.
- The Python simulator `evaluate_waf_request` (`r2_edge_rules.py:64-105`) allows only exact
  shapes.
- The tests check the simulator (`test_r2_public_edge_and_pdf_storage.py:253-356`,
  `test_r2_edge_rules.py`). Line 299 asserts that a path is blocked which the real rule
  allows.
- `apply` PUTs the zone-wide entrypoint ruleset (`apply_r2_edge_rules.py:278,284`) through
  a 464-line hand-written REST client.

**First move.** Add a test that the generated expression's prefix set equals the JSON
allowlist. Fix or delete the simulator assertions, starting with line 299.

**Steps:**
- Make the JSON's exact-prefix allowlist the only authority. It must include WS6's release
  layout.
- Generate the expression from it, and delete the simulator.
- `apply` reads the existing entrypoint ruleset and merges by rule `ref` before writing.
  Moving `apply` onto Cloudflare's maintained Python SDK is the plainer end state. Do that in
  the same PR only if merge-by-ref would otherwise grow the custom client.

**Delete:** 42 lines of simulator source, up to 104 lines of simulator-only tests, and the
custom REST plumbing (at cut).
**Replace with:** one allowlist and a generated expression.
**Raw check:** R-check 1–2. This workstream writes nothing to R2.
**Depends on:** WS6's key layout.

### WS6. Finish export-pins; delete the journal and resume route

**Addresses:**
- Hotspot 9; decision 3.
- d8z3a H1, H2 and H5; d8z3b H3 and H4; standalone H3; syem's ct-wxhg finding.
- ct-1dsp, ct-1mbc, ct-atjy, ct-idhg, ct-hm4b, ct-v6ao, ct-30pw, ct-5jqd, ct-2ut4, ct-76n5,
  ct-bpyj, ct-h73z, ct-piku, ct-zkzt, ct-m59w, ct-zb9y, ct-o24q.

**What export-pins lacks today:**
- The pointer names `releases/<version>/manifest.json`, which is never uploaded
  (`publication_cli.py:155-172`).
- `--version` defaults to the placeholder `v-export-01` (`:41`), so release keys are not
  content-addressed.
- `ConditionalManifestPublisher` treats a 412 as success and returns the local digest
  (`client.py:344-349`).
- Its writes bypass the key policy (`client.py:128-134`).
- The ExportPin reader branch returns no `technical`, `review` or `matchUrls`, which the
  audit named. Reading it directly, `entryOrigin` and `sourceIdentity` are also missing
  (`catalog-v6.ts:378-390` against `worker.ts:30-40`).
- The recovery index and the `accepted.json` mapping still publish through the journal
  route (`dispatch_corpus_recovery_publication.py`, and `corpus_recovery/publication.py`
  through `native.py` and `plan.py`).
- No workflow runs it.

**First move. Safe whichever way the rest goes: delete the resume axis.**
- `resume.py` (50) and `prepare_workflow_resume.py` (40).
- `describe-attempt` and `--resume-descriptor` (`publication_cli.py:53-83`).
- The workflow's resume inputs and steps.
- `test_workflow_resume.py` (179); its historical case has been red on main since
  `fb9ed402`.

**Evidence before the rest.** These are contract tests. Port them from
`test_viewer_publication_attempt.py` before deleting it.
- The pointer advances only after every release object is uploaded and verified.
- A second concurrent publisher loses the pointer compare-and-swap, and the old pointer
  stays.
- Every writer refuses `bodies/`, `receipts/` and `indexes/raw.json`. Today only `raw.json`
  is tested, through one client.
- A 412 on an immutable asset holding different bytes fails.
- A mapping `IfMatch` conflict is refused (keep `test_publish_corpus_recovery_mappings.py:186-270`).
- Replace the fake-module assertion at `.github/tests/test_viewer_r2.py:46` with a
  behavioral check.

**Finish:**
1. **Release keys and pointer:**
   - The release id is the digest of the export manifest.
   - Objects go under `viewer-publications/releases/<id>/` with `IfNoneMatch`, and the
     manifest is uploaded before the pointer.
   - The pointer flips once, with `IfMatch`. On any failure, rebuild and republish.
   - Nothing is written when the id equals the current pointer's.
2. A 412 triggers a byte comparison (WS2's verifier).
3. All writes go through WS2's policy function.
4. Reader parity: add the five missing reader methods to the ExportPin branch.
5. Move the recovery index and the mapping into the same release-and-pointer flow, once P5
   settles whether `accepted.json` is provenance.
6. Export-pins reads the catalog filenames/documents pair, not native selection internals,
   so WS7 can swap what produces it. `export_viewer_pins` has two paths, a native engine
   export (`filename_exports.py:763-818`) and local tables (`:820` on). Time both on the
   real catalog and keep one.
7. **Workflow:**
   - One job: build the export, publish the release, flip the pointer.
   - Trigger it on capture completion and on push.
   - Drop the 30-minute cron and the stdlib preflight with its hand-signed SigV4.
     Recommended: content-addressed releases make the "nothing changed" skip free.
8. Fix the retired workers.dev origin defaults (`viewer_publication/constants.py:6`,
   `pipeline_status.py:297`). Have `verify.control` call `bounded_control_read`.
9. End-to-end check: the custom-domain `manifest.json` returns 200 and the site loads. This
   also fixes the viewer that has been broken since the Oct 24 deploy.

**Delete. Certain: 2,786 source lines and 2,005 test lines.**
- Source:
  - `attempt.py` 346, `continuation.py` 492, `local.py` 161, `resume.py` 50,
    `reconciliation.py` 84, `plan.py` 67.
  - `publish_viewer_r2.py` 612 (including its v1 branches), `release_identity.py` 107.
  - `scripts/publication_preflight.py` 402, `prepare_workflow_resume.py` 40,
    `scripts/viewer_release_identity.py` 12.
  - `SelectedRuntime` (`dispatch_corpus_recovery_publication.py:21-149`, 129).
  - `ContinuedPublicationClient` (`client.py:244-309`, 66).
- The v1 recovery path, after freezing the v1 outputs used as an oracle by
  `test_filename_native_recoveries.py:58-72` into explicit expected values:
  - `AliasIndex` (`filename_alias_index.py:17-170`, 154);
  - `catalog_aliases` (`filename_aliases.py:21-29`, 9);
  - `index_recoveries` (`filename_recoveries.py:34-88`, 55).
- Tests:
  - `test_viewer_publication_attempt` 635, `test_publication_state_bounds` 312,
    `test_local_continuation` 245, `test_reconciliation_progress` 188.
  - `test_recovery_publication_continuation` 139, `test_checkpoint_costs` 79,
    `test_workflow_resume` 179, `test_runtime_ownership` 139, `test_filename_aliases` 89.
- `publish-filename-viewer.yml` (233) is rewritten; the net change is counted at cut.

**Delete. Conditional, if reader parity leaves the v6 pages unused: 1,695 source lines and
1,112 test lines.**
- `filename_native.py` 1,067, `publish_filename_viewer.py` 231, `native.py` 108.
- The v6 branch of `catalog-v6.ts` (`:392-680`, 289).
- The v6 tests.

**Replace with:** a content-addressed release and one conditional pointer flip.
**Raw check:** R-check 1–3, the refusal tests across every writer, and the P4 lock.
**Depends on:** WS2 steps 1–2; P5 for step 5; the WS5 allowlist.

### WS7. Move incremental catalog updates onto the engine (decision 6)

**Addresses:**
- Hotspot 8.
- czsd hotspots 1, 3 and 4; mi03a H5 (manufactured consumers).
- ct-si9g, ct-v5kb, ct-upte, ct-7e7q, ct-rcs8, ct-5kb2, ct-9vtu, ct-y32m, ct-l5q1, ct-gd8v,
  ct-dat9, ct-13cn, ct-gziq, and ct-bwac's catalog side.

**Rule.** congressional-tech keeps no incremental machinery of its own. The catalog is the
engine's job. The application supplies specs (keys, SQL, merge rules, the `document_id`
expression) and calls engine operations.

**First move: delete the manufactured consumers.**
- The scratch-scope dataset blocks (`catalog_dependency_storage.py:684-826`,
  `source_observations.py:700-760`).
- `last_change_report` and `last_refresh_summary`.
- The streaming change count (`native_capacity.py:281-316`).
- Their self-referential assertions (`test_native_features.py:913-994`).

The tests on `prepare()`'s result must stay green.

**Then:**
1. **Map the derivation onto the engine.** For each step that turns captures and state into
   the filename and document tables, name the engine operation that does it:
   - keyed `UpdateMergeSpec` merges with key pruning;
   - `CollectSet`, list and struct aggregates;
   - `ConnectedComponents` for document grouping;
   - partition specs.

   Write the map as a table in the PR. Any step with no engine operation becomes a
   **generic** docspec-rs ticket (WS9), not congressional-tech code.
2. **Prototype one table on real data.** Pick the documents table. Run an engine-native
   incremental update from the current selection with one day's change set. Compare the
   output with the Step 0 rebuild using the harness's `--compare-only`. Record time,
   memory, and objects read and written.
3. **Promote the rebuild as the oracle and recovery tool.**
   - Move the oracle and lineage files (403 lines) into a production module, behind an
     explicit `rebuild` operation.
   - Delete the refusals (`raw_sync.py:373-374`, `document_index.py:41-42`) and the hidden
     `--rebuild-only`/`--repair` flags.
   - It reads captures and state from the native raw selection.
4. **Evidence before deleting:**
   - Keep the differential test (`test_catalog_raw_updates.py:63-86`), retargeted to
     compare engine-native incremental output with the rebuild.
   - Add a raw-to-catalog invariant test: every retained capture yields its source row, and
     `source_id`/`document_id` are identical across two rebuilds.
   - Add a frozen ID fixture for a PDF row (kl2a1aa H3).
   - Add a shared `document_id` golden vector (WS9).
5. **Delete the Python incremental layer: 22 modules and the `catalog/` facade (9,248 lines).**
   - The `catalog_*` modules: dependency_storage, rows, raw_updates, batches, dependencies,
     dependency_preparation, scope, memberships, selection, adoption, updates, partitions,
     qualification, inputs.
   - The `source_*` modules: observations, replay, update_proof, capture_inputs.
   - `raw_adoption`, `raw_adoption_inputs`, `raw_readings_adoption`, `raw_catalog`.
   - Also delete:
     - 35 test files, 6,744 lines;
     - `scripts/incremental_boundary_proof.py`, 261 lines;
     - the adopt, qualify-sources and upgrade-source-rules CLI modes;
     - the native branches in `catalog_publication`, `catalog_types`, `catalog_validation`
       and `raw_storage.py:1304` (at cut).
   - `native_features.py` (1,270 lines today) shrinks to thin calls into the engine (at cut).
6. **Keep:**
   - `partition_routing.py` and the raw-side routing pages, which are raw provenance.
   - The oracle's own modules: catalog_staging, catalog_publication, catalog_cache,
     catalog_availability, catalog_validation, catalog_types, source_inputs,
     document_recovery, document_evidence and `index/*`.

   Re-check each against decision 6 as it is touched.
7. **Performance helpers.** The DuckDB external sort, typed-preparation resume, the spill
   arena (ct-4g55) and the reuse cache (ct-3bfx) stay only if the rebuild's profile needs
   them. If the engine prototype needs them, they belong in the engine.

**Raw check:** R-check 1–3. The rebuild and incremental updates only read raw data; their
derived writes go through WS2's policy and sit under the P4 lock.
**Depends on:**
- Step 0, for the oracle output and the baseline.
- WS6, so that the v6 consumers of `catalog_*` (`filename_native`, `filename_viewer`,
  `native.py`) are already gone.
- WS4, for the fingerprint.
- Any WS9 tickets for missing engine primitives.

### WS8. news_lake under decision 2

**Addresses:**
- Hotspot 10.
- mi03a H6 and H9, mi03b H4, kl2a1aa H4, standalone H4.
- ct-xu1o, ct-ur7v, ct-jo8n and the ct-a1aa group.

**First move.** Parametrize the conftest `lake` fixture over both backends
(`tests/conftest.py:147-150`, which today builds the PyIceberg `Lake`). Run the
Python-owner suites against `DocSpecLake`: `test_releases.py` (414),
`test_coordinator_replay.py` (295), `test_recovery.py` (255) and
`test_partitions_and_bridges.py` (1,012). This is the port of the crash, fence and merge
tests. Expected values come from the contract, not from the Iceberg run.

**Evidence:**
- Reproduce bug 1: an old release must stay readable after automatic lifecycle compaction
  (`no_release`).
- Reproduce bug 2: an existing append id is accepted again from a fresh process. First fix
  the order-dependent test at `test_docspec_backend.py:1461-1468`.
- A lease stolen mid-publish. Today the epoch is checked once (`lake.py:656`); never in
  `commit_records` (`:498-575`); and only before and after the block in `fenced_commit`
  (`:242-246`).
- A C5 subset read. `analysis/export.py:83-88` computes expiry from whatever tables happen
  to be loaded.
- Delete or fix the self-referential tests: the static receipt (`:2070-2100`) and the
  test-local `_ArrowHttpStream` (`:738-753`). Pin the schema by digest against git, not
  against a symlinked copy (`test_contract_records.py:25`).

**Fixes:**
1. **Bug 1:** remove the automatic `compact_lifecycle` call on commit (`lake.py:222-235,574`).
   Lifecycle compaction stays an explicit operator action that keeps release-pinned records.
2. **Bug 2:**
   - Revert ct-xu1o's time-keyed append keys (`APPEND_UPDATE_KEYS`,
     `docspec/schema.py:30-40`) to `['id']`.
   - Delete the `_known_ids`/`_known_upsert_records` caches (`lake.py:88,323-337`).
   - Measure the cost of `['id']` lookups with compaction on. It was never measured;
     ct-pgxn ran without compaction.
3. Re-check the epoch on every dataset commit.
4. **C5:**
   - Always load captures for the exported versions.
   - Python `export_release` stays the single C5 authority (third-pass call).
   - Delete the native computed-column policy (`docspec/schema.py:~245-300`) after a
     differential test that includes `retain_until == now`.
5. **Compaction:** run a poll loop with the app's table compaction off. If engine tail
   coalescing keeps active files bounded, delete `docspec/compaction.py` (260 lines).

**Delete: 375 source lines and 145 test lines certain.**
- PyIceberg backend: `storage/catalog.py` 125, `partitions.py` 123, `arrow_patch.py` 41.
- The `docspec_backend.py` shim, 86.
- The `hasattr` dispatch (`releases.py:185-197,293,314`; `coordinator.py:281`) and the
  PyIceberg scans and deletes in `coordinator.py` (`:15,183,245,346`), at cut.
- The PyIceberg parts of `mapping.py` (241 lines; `context.py` still imports it), at cut.
- The `pyiceberg` dependency.
- news_lake's binary resolver (`storage/docspec/client.py:35-36,56`), replaced by
  `docspec_client`'s.
- Tests: `test_evolution.py` 116 and `test_storage_catalog.py` 29. Iceberg-only parts of
  other files are counted at cut.

**Keep:** the pure-Python view evaluators in `analysis/views.py`, which import no
PyIceberg, as the `--verify-oracle` reference. Reviewers split here: mi03a keeps them as a
differential seam; standalone would replace them with direct contract assertions. Decision 2
removes only PyIceberg (Q5).

**Raw check:** news_lake never touches R2; captures keep only `payload_uri` and a hash
(`adapters/common.py:83-93`). R-check 1.
**Depends on:** the engine pin (its tests run the real engine) and WS3 step 5 (IPC).

### WS9. docspec-rs cuts

**Addresses:**
- Hotspot 11; docspec H1–H7.
- ss-yjut, ss-55jg, ss-7rnt, ss-8tjo, ss-8ani, ss-1txq, ss-k3mg, ss-r9b4, ss-e2it.

**How it runs.** One move per commit, with `scripts/check` green between moves. The app's pin
bumps once, at the end, together with WS3's client changes.

| Step | Move | Evidence first | Measured |
|---|---|---|---|
| 1 | A route-contract test lists every route `docspec_client` calls. Delete every other route and every alias. | The test enumerates the paths in `client.py` | 77 routes are registered; `client.py` references about 34 distinct path strings. The audit said ~15; the test decides. Handlers at cut. |
| 2 | Delete the lifecycle families no consumer writes: the retirement planners (`changes/retirement.rs`, plus `retention/{availability,compaction_recovery,export_recovery,grants,recovery,retirement,seals}` and their tests); restore points and remote restore; the succession archive and checkpoints; remote removal *execute* (keep *plan*) | A table-driven test: every family a consumer-used operation writes is accepted by inventory and survives compaction for as long as resume needs it (decision 1). A property test: GC never removes a path reachable from the selected release or a reader pin. | Retirement 5,547; restore 3,042; succession up to 2,101 (the whole `engine/history` module; exact at cut) |
| 3 | Type what survives: parse once into a `LifecycleKey` enum. That replaces the 612-line prefix chain in `Inventory::record` (`inventory/expand.rs:54-663`) and the prefix checks in `owners.rs` (24) and `compaction.rs` (10). GC reachability uses typed references instead of substring matching (`compaction.rs:686-726`). | Step 2's tests | at cut |
| 4 | Delete `adapters/dagster` and its block in `scripts/check` | The app uses `docspec_client` | 1,583 |
| 5 | Replace `remote_build_provider_tests` with one isolation smoke test: every write and delete stays under `owned_prefix`, and a `receipts/` key is refused. Add an `owned_prefix` overlap refusal for `receipts/` and `bodies/`. | The new smoke test | 3,792 |
| 6 | Split `write_batches_inner` (`storage.rs:359-659`) into normalize, route and identity stages, with no behavior change | Storage tests (skew split `:1107`), the fanout bound (`381108c`), the update_pruning oracle, `partitioning_and_cc.rs:90,280`, plus a new 20 MB byte-equality test through `/run` and `/exports/run` | 301 lines moved, about 0 net |
| 7 | Delete `cli_args.rs` and take positional `hash` through clap | `tests/remote_cli.rs:20`; delete the shim's own test (`:161`) | 203 |
| 8 | Replace the hand-written SHA-256 with the `sha2` crate (0.10.9 is already in `Cargo.lock`). `d17c855` records no reason for writing it by hand. | The FIPS vectors in the `sha256.rs` tests, plus a golden `document_id` vector from Python `compute_document_id` (`bipartite.py:197`) | 114 |
| 9 | Compute Year/Month/Day with `iceberg::transform::create_transform_function`, which is already used for Bucket (`partitioning.rs:289`) | A differential test against the current output over a wide date range | 102 (`partitioning.rs:94-169,335-360`) |
| 10 | Delete legacy formats: the Format 10/11 readers, `CompletedGroups::Legacy`, AST alias spellings, `--occurrences`/`--values` | Existing tests | at cut |
| 11 | Remove success-shaped fallbacks: `retention/compaction.rs:146` (`unwrap_or_default`; return the error) and `http/ipc.rs:535` (substring classification) | Targeted tests | at cut |
| opt. | The duplicated export sanitizer and the three copies of footer accounting (mi03a H7) | A descendant-metadata test on the pipeline path | at cut |

**Step 2 and decision 1.** The retirement routes end recovery records explicitly. No
consumer calls them, and crash resume doesn't need them: lifecycle compaction reclaims the
records of finished operations. Confirm this by counting records after N operations.

**Keep:** `Strict<T>`, remote scope with create-only writes and the digest-verified delete
actor, key pruning, the `UpdateMergeSpec` merge, tail coalescing, `BackendCapability`,
`deny_unknown_fields`, ss-wie5's bloom-filter decision, and the flat
`execute_engine_command` dispatch.
**Raw check:** the engine holds no raw bytes uniquely. Rely on the isolation smoke test, then
R-check 1 after the pin bump.
**Depends on:** WS1's engine half.

### WS10. Shims and legacy formats

**Addresses:**
- syem hotspots 5 and 6, czsd hotspot 3, d8z3a H5, d8z3b H4.
- ct-4fcl, ct-fsbf, ct-0bce, ct-unv0, ct-jufk, ct-8od2, ct-q29c, ct-wxhg.

**First move.** Point the 42 monkeypatch calls on shim and publisher modules at the owning
modules, or better, at behavioral seams. Then retarget the shims' importers;
`retention/docspec.py` alone has 8 production importers.

| Delete | Lines |
|---|---:|
| `retention/document_index.py` (`_CompatibilityShim`), after WS4 | 60 |
| `retention/docspec.py`, `retention/docspec_host.py` | 83 |
| `docspec_client/docspec.py`, `docspec_client/docspec_host.py` | 124 |
| `scripts/publication/*.py` (7 wrappers, including the `gc.get_referrers` swap); workflows call `python -m viewer_publication…` | 131 |
| `scripts/publication/tests/test_cli_wrappers.py` | 107 |
| `tests/historical_viewer_publication.py` (test-only v5 generator, imported by src `filename_test_fixture.py`) | 204 |
| ct-8od2's unwired compaction helpers (`filename_exports.py:1012-1254`) plus `test_catalog_compaction.py` | 243 + 332 |
| Weekly retention mirror (ct-q29c): `retention/weekly_tables.py`, `cli/sync_weekly_tables.py`, `test_weekly_retention_tables.py`, and the `update-data.yml:196` step. First confirm nothing reads the weekly datasets. | 1,087 + 336 + 415 |
| The `--streamed-recovery` flag (keep the module and its tests) | at cut |
| In-process proof registries: `InventoryValidation` (`viewer_inventory.py`), the `CatalogPairValidation` class (keep `validate_catalog_pair`, which `corpus_recovery/diagnostics.py` uses), `GuardedPublicationClient._receipts`, `VerifiedFile._issued`. First measure the re-hash cost on the real 1.09 GB catalog pair. | at cut |
| `verify-live-publication.mjs`'s acceptance of manifest versions 2 and 5 | at cut |

**Also:** move `filename_test_fixture.py` (117 lines) into tests, or retarget it.
**Keep:** the legacy raw-table readers (`LEGACY_CAPTURE_SCHEMA`, `LEGACY_STATE_SCHEMA`,
`raw_schemas.py:48-74`), because old raw tables are raw data. Delete
`tests/historical_raw_archive.py` (214) only if no surviving test needs a legacy-format
raw fixture.
**Raw check:** R-check 1–2, plus R-check 3 when imports in `raw_schemas` or `raw_storage`
change.
**Depends on:** WS4 for the fingerprints; WS6 for the publication shims and registries.

### WS11. Browser and performance freeze

**Addresses:**
- The README's "Freeze" call.
- The browser tickets: ct-9at7, ct-15wc, ct-bs70, ct-lvvr, ct-p6aq, ct-zika, ct-qyey,
  ct-4zer, ct-m9ry, ct-o6d1, ct-2bhh, ct-rrfm.
- Engine performance: ct-xl0y, ct-wmtx, ct-wjce, ct-vt7i, ct-mpsp.
- ct-sv16.

**Rule.**
- No browser, viewer or engine performance work, and no new performance counters, until
  there is a user or a measured failure on real data.
- "Don't extend, don't revert": existing sound code stays (Section 4).
- The broken public viewer is not fixed separately. Its custom-domain manifest returns 404,
  the site expects v6 and the live catalog is v5. WS6's end-to-end check covers it.

**Delete as their subjects go.** Source total 1,862; tests 723.

| Group | Scripts (lines) | Goes with |
|---|---|---|
| Imports test fixtures | `measure_publication_control.py` 188 | now |
| Journal-route costs | `compare_publication_costs.py` 236, `publication_costs.py` 134 | WS6 |
| Browser benchmarks | `benchmark_viewer_publication.py` 291, `benchmark_viewer_browser.mjs` 161, `viewer_benchmark_server.py` 248 | the freeze |
| v6 preparation | `measure_preparation_decoded.py` 191, `measure_preparation_resources.py` 90 | WS6 (v6 preparer) |
| v1 aliases | `measure_alias_preparation.py` 109 | WS6 |
| Incremental catalog | `benchmark_catalog_grouping.py` 77, `measure_catalog_partition_reuse.py` 137 | WS7 |

The tests for these scripts (723 lines) go with them.

**Keep:** `benchmark_core_rebuild.py` (Step 0) and `compare_raw_keyed_updates*.py`.
**Raw check:** R-check 1.
**Depends on:** nothing. The deletions follow WS6 and WS7.

### WS12. Ticket process

**Addresses:** "Patterns seen in every batch." Keep the ceremony to these points:
1. Create the ticket before the first code commit. An epic closes only after its children
   close; ct-8kl2 closed before 9 of its 15 children existed.
2. Acceptance criteria name an observable behavior and the test or measurement that shows
   it. For performance work, record a baseline on real data and write the decision rule
   before writing code. The audit's best examples are ct-tuez, ss-wie5, ss-g9sn, ss-1txq,
   ct-m9td, ct-jl1m and ct-qspb.
3. Commit evidence, under `docs/` or in the ticket. Never cite the gitignored `output/`
   folder; its evidence is already gone.
4. A retirement ticket closes only when the old path is gone. Its closing note gives before
   and after `wc -l`. The retention package grew from 9.0k to 27.8k lines under
   "retirements".
5. An invariant named in a ticket becomes a test named in its acceptance criteria.
6. Drop self-assigned grades and size metrics as goals: parameter counts, docstring
   percentages, "<120 LOC".
7. Add one cheap check: commit SHAs cited in a closed ticket must resolve
   (`git cat-file -e`). It can't tell whether a commit does what the note claims. Review
   does that, by reading the code rather than the note.
8. Every reviewer brief names the project runners (`scripts/dev.py`, `scripts/check`).

## 4. Keep list

These are sound, or not worth moving. The README's leave-alone list is honored in full.

**Raw path:**
- Create-only body and receipt writes, MD5-verified uploads and verified `.gz` collisions.
- Immutable receipt batches and orphan-receipt replay (`raw_archive.py:670-677`).
- Recovery `checked_put` with readback, and no second PUT after a lost acknowledgment.
- RecoveryGuard (ct-jl1m), the body-key shard check (ct-qspb), recovery admission (ct-4r1c,
  with only the WS4 boundary fix), ct-fqgf and ct-vxzu.
- Raw-side routing (`partition_routing.py`, `raw_state_routes.py`) and the legacy raw-table
  readers.
- `derive_body_key` and its golden test.
- The `docspec_client` transport, with `cleanup_safe` as the single decision point.
- ct-n7la capacity admission, ct-wjce's `chunk(0)`, ct-snh8, ct-8w0g, the ct-d3un fixes.

**Derived and publication:**
- The publication raw-key allowlist, which becomes a rule inside WS2's policy function.
- `--verify-publication`'s Chromium checks, retargeted to export-pins manifests.
- The decoded-memory budget. Revisit it on the next false refusal on real data.
- Review-asset staging (ct-vp92).
- The browser reader: `cache.ts`, `withVerifiedJson`, `startup.ts` (ct-tdsx), and the
  ExportPin path. Only the dead route's branch goes, in WS6.
- ct-h23e's pread arena, ct-csyg's pruning, and the bounded control reads.
- Export rights (C5) in Python.
- `validate_catalog_pair`.
- Typed-preparation resume, the DuckDB external sort, the spill arena and the reuse cache,
  while their host code exists (see the WS7 tension).
- The Pages lock files. Give the duplicated npm pin one owner when Pages is next touched.
- ct-gesp, ct-d2lk, ct-hfrv, `publication-budget.py`, and ct-eauq's fresh-target check.

**Engine:**
- Merge (`UpdateMergeSpec`), CollectSet, partitions, tail coalescing, key pruning, export
  child tables.
- `Strict<T>`, kept while GC exists.
- The remote scope boundary, create-only writes and the digest-verified delete actor.
- Lifecycle compaction, `/retention/inspect` and `/retention/removal/plan`.
- `BackendCapability` and `deny_unknown_fields`.
- The connected-components topology scans, until measured.

## 5. Open questions for the owner

**Answered on Oct 24:**
1. **Catalog freshness.** Decision 6 settles this. Incremental updates use the engine, so
   the rebuild's duration only has to fit its role as oracle and recovery tool.
2. **Ingest policy.** No exclusion list will exist, so WS2 deletes the gate (162 lines).
   Whether to write PDF siblings (`.pdf` beside `.gz`) always or never is still open.
3. **Repair or regenerate the raw index.** Repair rows with a wrong `stored_sha256` in
   place; don't regenerate the index.
4. **Code identity for recovery imports (WS4).** Imports refuse uncommitted code and record
   the git commit plus `uv.lock`.

**Still open:**
5. **PDF siblings:** always write them, or never?
6. **news_lake's Python view oracle.** Decision 6 says congressional-tech should not
   duplicate engine views. Keep `analysis/views.py` only as a test oracle, or replace it
   with direct contract assertions against engine output?
7. **Only if needed.** If per-phase commits make raw Builds too slow after the revert, do you
   approve moving the raw index from one dataset per leaf to one partitioned dataset per
   kind? That would be a staged raw-index migration.
8. **Only if needed.** If Step 0 finds catalog facts that exist only in earlier derived
   tables, should we capture them into receipts first, or accept losing them?

**Under decision 6, revisit these keep calls** that today duplicate engine behavior:
- the export-rights policy, implemented in both Python and the engine (prefer the
  engine's);
- ct-csyg's hand-written key pruning (prefer engine pruning);
- the Python retention planner (delete it; use engine retention);
- the news_lake view oracle (question 6).

## 6. Measured size of the cut

**How to read the table:**
- "Certain" means whole files or whole functions whose deletion this plan commits to.
- "Conditional" depends on Step 0, a measurement or an open question.
- "At cut" is code inside larger files; it is counted in the PR and left out of the totals.
- Replacement code, such as new tests and helpers, is not subtracted.

| WS | Certain source | Certain tests | Conditional | At cut (not in totals) |
|---|---:|---:|---|---|
| 1 Divergence | 18 | — | 43 (inside WS7's modules; counted there) | 75 Python and 60 Rust branch sites |
| 2 Raw write rules | 345 + 162 (exclusion gate, answered) | — | — | per-layer probes; planner tests |
| 3 Custody client | 30 | — | — | fallbacks inside the 390-line copies; legacy sizing; `TypeError` retries |
| 4 Provenance | — | — | — | hand list and its test |
| 5 WAF | 42 | — | up to 104 test lines | REST client |
| 6 Export-pins | 2,786 | 2,005 | 1,695 source + 1,112 tests (v6 preparer and reader) | workflow rewrite |
| 7 Incremental catalog (decision 6) | 9,509 | 6,744 | — | native branches; `native_features` |
| 8 news_lake | 375 | 145 | 260 (app compaction) | dispatch; `mapping.py`; native C5 policy |
| 9 docspec-rs | 14,383 (Rust source and tests; the Dagster adapter) | — | up to 2,101 (succession) | routes; legacy formats; typing |
| 10 Shims and legacy | 2,064 | 1,058 | — | registries; fixture |
| 11 Freeze | 1,862 | 723 | — | — |
| 12 Process | — | — | — | — |

**Totals:**

| | Lines |
|---|---:|
| congressional-tech, certain | 17,193 source + 10,675 tests = 27,868 |
| docspec-rs, certain | 14,383 |
| **Certain total** | **42,251** |
| Other conditionals (WS5 104, WS6 2,807, WS8 260, WS9 2,101) | +5,272 → up to **47,523** |
