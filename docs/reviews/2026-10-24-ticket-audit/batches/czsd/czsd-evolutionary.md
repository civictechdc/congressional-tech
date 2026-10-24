# Batch czsd: evolutionary-refactoring audit (third pass)

Mode: **Audit**. I inspected and recommended only; I changed nothing in the repo. The greenfield lens
holds: only the raw R2 data (`congressional-tech-raw` bodies, receipts and their provenance) must
survive, and everything derived can be rebuilt. This file supplements `czsd-verdicts.md` and
`czsd-greenfield.md`.

**Baseline run** with the project venv (`.venv/bin/python -m pytest ... -q -p no:cacheprovider`):
- Raw custody and differential tests: **94 passed**. Files: `test_r2_archive_store.py`,
  `test_async_capture.py`, `test_r2_public_edge_and_pdf_storage.py`, `test_pdf_backfill.py`,
  `test_catalog_raw_updates.py`, and corpus_recovery `test_import_corpus_recovery_batch.py`.
- Earlier passes: 264 czsd engine tests and 340 snh8/8w0g tests passed; 1 unrelated failure
  (`test_workflow_resume.py` fixture paths).

**Coverage:** the hotspots found in earlier passes, plus the raw write path and the code those
hotspots call. This was not a whole-repository audit.

## New finding that reframes the batch: tests run different code than production

- **75 production branches on `PYTEST_CURRENT_TEST`, across 24 retention modules.** Found with
  `git grep -c`. Examples: `catalog_staging.py` 10, `source_observations.py` 7,
  `catalog_batches.py` 7, `source_update_proof.py` 6, `catalog_adoption.py` 5,
  `catalog_memberships.py` 3, `catalog_rows.py` 1, `raw_storage.py` 1. All were introduced
  Oct 22–24 in ct-2ukk performance commits (`48137619`, `6c5712c1`, `017eb2cc`, `a8ddaa8f`,
  `93a63e1d`, `e4b3216b`, `f5e8fe1b`). The tickets in this batch did not add them, but they live
  inside modules this batch built.
- **Demonstrated, not inferred.** My script `czsd-pytest-branch.py` calls
  `source_update_proof._digest` on one row. It returns `5231472661a1132a…` with the variable unset
  (production) and `fdc294afa3388e72…` when `PYTEST_CURRENT_TEST` is set. Code at
  `source_update_proof.py:37-42`.
- **Verification that exists only under pytest.** In production, catalog adoption skips the
  native readback entirely: `actual = expected` (`catalog_adoption.py:134-137`). It then hashes the
  source file's own rows as "actual". That is a digest supplied by the thing being checked. The
  exact-value comparison runs only in tests (`:138-147`). This contradicts ct-9vtu's and ct-rcs8's
  closure claim that all-value readback is mandatory. It came from `48137619`.
- **Hardcoded local snapshots treated as truth.** Production reads
  `output/incremental-updates-20261019/adoption-inputs/state.parquet` whenever it exists and its
  row count equals the manifest (`raw_storage.py:661-672`), and swallows any exception. The same
  pattern applies to filenames and documents (`catalog_raw_updates.py:155-183`). Equal row counts
  do not mean equal data, so corrected state with the same count returns stale Oct 20 values. The
  path is relative to the working directory, so it fires on the **live primary checkout**, where
  `output/` exists. CI never sees it. Pytest cannot see it either.
- **The implementation fingerprint stopped tracking the code.** The 3,370-line `document_index.py`
  was split into `retention/index/*` by `e4b3216b`. But `source_update_requirements()`
  (`source_update_proof.py:14-23`) and `source_fingerprint()` (`catalog_cache.py:233-261`) still
  hash the *files* `document_index.py` (now a 60-line re-export) and `raw_catalog.py` (a 25-line
  facade). So changes to the real interpretation code (`index/sources.py`, `index/bipartite.py`,
  and so on) no longer change the fingerprint, and stale derived results can be reused. This is a
  textbook "cosmetic simplification that changed semantics".
- **Raw write path is clean.** It has **zero** such branches: `r2.py`, `raw_archive.py`,
  `body_files.py`, `corpus_recovery/transfer.py` and `acquisition/raw_sync.py` (checked with grep).
  Its tests characterize production behavior.

Consequence: the passing czsd engine tests are weak evidence for production behavior in those
modules. My earlier LANDED-SOUND verdicts for ct-upte, ct-7e7q, ct-rcs8, ct-5kb2 and ct-9vtu stand
for the code as closed. The code on main has since diverged in ways those tests cannot see.

## Hotspots, ranked

### 1. Incremental catalog engine: retention `catalog_*`, `source_*`, `partition_routing`, adoption (about 27.8k lines)
Tickets: ct-si9g, ct-v5kb, ct-upte, ct-7e7q, ct-rcs8, ct-5kb2, ct-9vtu, ct-y32m, ct-l5q1, ct-gd8v (adoption half).

- **Contract (greenfield):** given the raw receipts and bodies, produce the derived catalog (sources,
  documents, groups) deterministically. Nothing must be preserved except determinism from raw.
  Exact adoption, resume of old attempts and readable historical proofs are no longer requirements.
- **Design pressure:**
  - Handwritten infrastructure replacing established behavior: app-side routing pages,
    persistent B-trees, proof chains, SQLite worklists and leaf caches built over DocSpec.
  - Defensive sediment and success-shaped fallbacks: the 75 pytest branches, snapshot shortcuts
    keyed on row count, and swallowed exceptions.
  - Compatibility sediment: adoption paths, historical proof readers, the legacy writer kept alive
    in tests (`tests/historical_raw_archive.py`, 214 lines).
  - Cosmetic simplification that changed semantics: the broken fingerprint.
  The representation (keyed incremental updates in app-managed routing) is the false premise.
  This is not a function-length problem.
- **Cheapest safe intervention: bounded replacement behind the `update_from_raw` contract.**
  The full-rebuild oracle already exists:
  - `tests/historical_raw_catalog.py:46-69` (`rebuild_catalog`, 283 lines)
  - `test_catalog_raw_updates.py:63-86` already uses it to diff incremental output against it.
  - Production forbids it (`cli/raw_sync.py:373-374`, `cli/document_index.py:41-42`).
- **First move:** promote the full rebuild from raw into a supported production operation and time
  it once on the real corpus. Decide incrementality afterwards from that number. If it is
  acceptable, delete adoption, proofs, routing and caches together rather than repairing them.
- **Behavioral evidence needed first:**
  - Keep the differential test (incremental against rebuild) for as long as both paths exist.
  - Add a raw-to-catalog invariant test, for example: every retained capture yields its source row,
    and IDs are deterministic across two rebuilds.
  - Delete or rewrite the self-referential tests: `test_incremental_boundary_proof.py` (it checks
    only fixture construction), and every test whose behavior depends on a pytest-only branch.
- **Change from earlier:** confirms and strengthens the greenfield "radically simplify".
  Quadratic worklist (`source_observations.py:793`) **downgraded**: it is moot under replacement,
  and a one-line index if the engine is kept. The pytest branches and snapshot shortcuts **added**
  as the top risk.
- **If the engine is kept even briefly,** delete the two `output/...` shortcuts first, because they
  read stale data on the live checkout. Then make both fingerprints hash the package directories,
  not named shim files.

### 2. Raw capture and custody: Archive, R2Store, `body_files`, recovery `checked_put`, ct-84x7 stream reads
Tickets: ct-365w (capture half), ct-84x7, ct-gd8v (guards).

- **Contract (must preserve):**
  - Content-addressed bodies are written only if absent (`IfNoneMatch`), MD5-verified, and their
    bytes re-verified on collision.
  - Receipt batches are immutable, and a name collision fails loudly (`raw_archive.py:509-530`,
    `r2.py:372-397`).
  - Recovery writes are read back (`transfer.py:26-46`).
  - Orphan receipts are re-applied on startup (`raw_archive.py:670-677`).
  - Index selectors use ETag CAS.
- **Design pressure:**
  - *Cloned workflows:* the policy "on 412, read the existing body and verify its hash" is copied in
    three callers (`raw_archive.py:381-383`, `acquisition/raw_sync.py:412-415`,
    `body_files.py:137-140`). The PDF path (`r2.py:388-391`, used at `raw_archive.py:384-388`)
    lacks it.
  - *Dead hazardous path:* `migrate_pdf_bodies_to_uncompressed(delete_gzip=True)`
    (`raw_storage.py:280,312-316,330-331`) deletes canonical bodies after only an existence check.
    It has no caller, no store implements `delete`, and no test covers the delete branch.
- **Cheapest safe intervention:**
  1. **Delete the `delete_gzip` parameter and its two branches.** This is a pure removal of
     unreachable code.
  2. Give collision verification one owner: a store-level "retain body" that verifies existing bytes
     on 412, for `.gz` and `.pdf` alike. Then route the three callers through it.
  Leave ct-84x7's shared stream-retry runner alone. The separate async loop (`r2.py:164-180`) is a
  deliberate split.
- **Behavioral evidence:**
  - Existing characterization: `test_r2_archive_store.py:84,109,163,238,279`,
    `test_async_capture.py`, and `test_r2_public_edge_and_pdf_storage.py:185-196` (migration
    without deletion). They pass and run production code.
  - Missing: a PDF-collision-with-different-bytes test, written before consolidating; and an
    operational audit that every `receipt_key` referenced by the 3,909,134 legacy capture rows
    (2,289 keys) exists in R2.
- **Change from earlier:** confirms KEEP. "Verify .pdf collisions" is refined into "one owner for
  collision verification", which removes the copies rather than adding a fourth.

### 3. Viewer publication and script shims
Tickets: ct-ihve, ct-87n4, ct-jufk, ct-kkio, ct-i7j2.

- **Contract (greenfield):** publish an immutable viewer release from the derived catalog, then
  flip a pointer. Stable-ID, content-addressed pages are the sound core
  (`filename_native.py:142-276`).
- **Design pressure:**
  - *Indirection without responsibility:*
    - five 16–18-line `import *` script shims (`scripts/publication/*.py`)
    - `scripts/viewer_release_identity.py`
    - `retention/document_index.py` (60-line re-export)
    - `retention/docspec.py` (63-line shim)
    - `retention/raw_catalog.py` (25-line facade)
  - *Defensive sediment:* release identity hashes source files and normalized ASTs
    (`release_identity.py:28-60`, `filename_native.py:730-748`), plus resume descriptors and
    continuation journals.
  - *Compatibility sediment:* the checker still accepts manifest versions 2 and 5
    (`verify-live-publication.mjs:119`).
  - The fake-module shim (`release_identity.py:12-16`) exists only to satisfy
    `test_viewer_r2.py:46`. That assertion is now self-referential, and the shim breaks direct
    helper imports (ImportError reproduced).
- **First move:** delete the fake-module shim together with the vacuous assertion. Replace it with
  a behavioral check, for example: fresh-process CLI preparation completes and its identity equals
  the package function's result. Then collapse the script shims into console entry points.
  **Order matters:** fix or remove the fingerprint (hotspot 1) before deleting `document_index.py`
  or `raw_catalog.py`, because the fingerprints hash those files.
- **Behavioral evidence:** `test_filename_browse_pages.py`, `test_filename_native_upgrade.py`,
  `test_publication_verification.py` (pass). `test_viewer_r2.py:21-60` must be fixed first.
- **Change from earlier:** the jufk shim is raised from "hygiene" to "fix before moving code". It is
  a self-referential test guarding a module path that every shim collapse would touch.

### 4. ct-dat9 routing and hosted runtime
- **Pressure:** compatibility sediment. The `--rebuild`/`--repair` flags exist only to refuse
  (`cli/raw_sync.py:204,216,373-374`; `cli/document_index.py:26,41-42`). Also indirection
  (`raw_catalog.py`). A misleading refusal for missing configuration ("must be valid JSON",
  `setup-native-runtime.py:27,160`) is pinned by the ct-kkio test.
- **First move:** none of its own. It falls out of hotspot 1's first move, which gives "rebuild" a
  real meaning. Separately and cheaply: one CI assertion that the hosted runtime descriptor's
  `source_revision` satisfies `QUALIFIED_DOCSPEC_RUNTIME`, which would have caught the Oct 20–24
  outage; and an explicit "not configured" refusal.
- **Change from earlier:** confirms "reverse the rebuild prohibition".

### 5. ct-snh8 and ct-8w0g: leave alone
`congress_shared/youtube_cache.py`, `cli.py`/`paths.py`, `adapters/documents.py`,
`transport/congress.py`, `senate_player.recording_urls` and `r2._read_stream` each own one decision,
with tests that run production code. **No material finding.** Only the stale `globals.py` references
remain (`capture-raw-sources.yml:34`, `docs/congress-api-contracts.md:155`). Confirms KEEP.

## Calls that changed versus earlier passes

| Earlier call | Now |
|---|---|
| Top derived-data risk: the quadratic worklist | **Pytest-divergent production code plus snapshot shortcuts** on the live checkout; the quadratic loop is moot or trivial |
| "Tests pass" was the evidence for ct-upte, 7e7q, rcs8, 5kb2, 9vtu | Those tests now exercise test-only branches; production adoption readback is skipped (`catalog_adoption.py:134-137`) |
| Fingerprints not examined | **Broken by decomposition:** stale derived reuse is possible |
| Raw: "verify .pdf collisions" | "One owner for collision verification", after deleting `delete_gzip` |
| jufk shim: hygiene | **Fix before any shim collapse** (self-referential test) |
| Engine: simplify | **Bounded replacement**: promote the existing rebuild oracle, measure once, then delete |
| snh8/8w0g: keep | Confirmed: leave alone |
