# Ticket audit, 2026-10-24

An independent review of every ticket closed between Oct 18 and Oct 23, 2026: 216 in
congressional-tech (`ct-*`, including one epic counted in two batches) and 37 in
docspec-rs (`ss-*`, tracked in `spicy-stack/.tickets`). Nine reviewers each took one
batch, read-only, and graded the original proposal and the finished work separately,
the way a CS300 professor would. They then made two more passes:

1. **Greenfield lens.** Nothing uses this project yet. Only the raw/source data in R2
   (`bodies/`, `receipts/` and their provenance) must survive; everything derived can
   be rebuilt.
2. **Evolutionary-refactoring lens** (audit mode). Each hotspot is named by its design
   pressure, the cheapest safe first move is chosen, and the evidence needed before
   moving code is listed. See `batches/*/*-evolutionary.md`.

Tickets and closing notes were treated as claims. Verdicts cite `file:line` or
commits. Code was read at congressional-tech `c858a5a2` and docspec-rs `d9c6719`.

## Results

| Batch | Area | Tickets | Sound | Concerns | Partial | Superseded | Not landed | Proposal (1st → greenfield) | Work (1st → greenfield) |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| mi03a | ct-mi03: reuse DocSpec execution | 24 | 11 | 9 | 4 | 0 | 0 | 86.2 → 84.2 | 77.2 → 77.3 |
| mi03b | ct-mi03 (rest + epic) | 24 | 5 | 8 | 10 | 1 | 0 | 87.7 → 83.5 | 79.4 → 79.7 |
| d8z3a | ct-d8z3: publication efficiency | 22 | 6 | 10 | 1 | 5 | 0 | 79.8 → 75.7 | 80.1 → 79.2 |
| d8z3b | ct-d8z3 (rest + epic) | 23 | 13 | 6 | 2 | 2 | 0 | 82.0 → 78.4 | 83.7 → 82.4 |
| standalone | tickets with no epic | 32 | 13 | 15 | 2 | 2 | 0 | 80.4 → 76.0 | 80.5 → 80.7 |
| czsd | ct-czsd, ct-snh8, ct-8w0g | 29 | 22 | 7 | 0 | 0 | 0 | 88.9 → 85.9 | 88.0 → 87.5 |
| kl2a1aa | ct-8kl2 (single bucket), ct-a1aa (news_lake) | 29 | 3 | 14 | 9 | 0 | 2 | 84.4 | 75.0 |
| syem | ct-syem (CS300 audit), ct-d3un, ct-4t6s | 33 | 11 | 6 | 15 | 0 | 1 | 78.7 | 72.9 |
| docspec | docspec-rs (ss-yjut, ss-55jg, others) | 37 | 6 | 18 | 12 | 0 | 1 | 82.5 → 81.5 | 77.4 → 77.2 |
| **All** | | **253** | **90** | **93** | **55** | **10** | **4** | **83.3 → 80.9 (B-)** | **79.1 → 78.9 (C+)** |

kl2a1aa and syem applied the greenfield lens in their first pass. One kl2a1aa ticket
could not be verified. All averages are weighted by ticket count (`compiled.json`).

## Raw-data status (checked directly, not by a reviewer)

- **Receipts are complete.** All 2,289 receipt objects referenced by the legacy capture
  table (`output/incremental-updates-20261019/adoption-inputs/captures.parquet`,
  3,909,134 rows) exist in `congressional-tech-raw/receipts/` (1.08 GB). None are
  missing, and no receipts exist that the table doesn't reference.
- **No new raw captures since about Oct 19.** Hosted capture failed from Oct 21 to
  Oct 24, first on packaging and then on a stale engine pin. The engine pin was fixed
  on Oct 24; the next scheduled capture is the first chance to resume.
- No finding showed a raw body or receipt being lost, overwritten or deleted.

## Actions taken on Oct 24

- **`54a68ac7`, pushed to main:**
  - The capture schema carries `stored_sha256`, and the two places that inferred it now leave it null when unknown (risk 3).
  - Hosted setup refuses any engine revision other than `QUALIFIED_DOCSPEC_RUNTIME` (risk 2).
  - `delete_gzip` is removed (risk 5).
  - Checks: capture workflow offline suites (6207 + 84 passed); the affected raw, edge, recovery and e2e files (175 passed); engine-backed raw storage tests (38 passed); the hosted capture validation passed.
- **Recovery decisions backup:** a verified create-only copy is at
  `provenance/recoveries/accepted-00922c1e….json` (9,638,187 bytes, sha256
  `00922c1eb29d84cdf68b1d17fb00e050f443942f13b3d35e775192ff42b73864`), with a local copy
  in `output/provenance-backup-20261024/`.
- **Owner action pending:** R2 bucket lock rules on `receipts/`, `bodies/` and
  `provenance/` (indefinite).
- **Still to check:** whether the selected native capture index holds rows written
  with the wrong `stored_sha256` between Oct 22 and Oct 24.

## Raw-data risks, ranked (consensus across batches)

| # | Risk | Reachable today? | Verified by |
|---|---|---|---|
| 1 | One bucket holds raw, derived, engine warehouse and public data, with bucket-wide write credentials. Raw safety rests on code checks such as the publication allowlist and create-only flags. | Structural | 5 batches |
| 2 | Hosted setup checks the engine binary against its own descriptor, never against `QUALIFIED_DOCSPEC_RUNTIME`. A stale engine can write raw provenance. | Yes (pin correct as of Oct 24, but unenforced) | mi03b, czsd, and this audit's own CI work |
| 3 | `raw_values._to_legacy_capture_table` fills `stored_sha256` with the content hash when a new capture row has none, which is wrong for gzip bodies. Receipts are correct; the native capture index can be rebuilt from them. Since `48137619` (Oct 22). | Yes, for new captures | syem; confirmed in code |
| 4 | `raw_sync --upgrade-source-rules` rewrites the raw-state selector with no old/new comparison. Production-only branches trust local raw files by row count, and `R2Store.read` can serve raw checks from a local cache. | Yes | mi03a, standalone |
| 5 | Latent traps: `migrate_pdf_bodies_to_uncompressed(delete_gzip=True)` deletes the `.gz` body without verifying the `.pdf`; the retention planner treats unknown objects as reclaimable; the `VerifiedFile` constructor trusts caller-supplied hashes; engine `pre_admission` is set by error kind; `R2Store.put` overwrites by default. | No callers today | Several batches; delete_gzip, VerifiedFile and pre_admission confirmed in code |
| 6 | `viewer-publications/recoveries/accepted.json` is mutable and sits under a derived prefix. Checked directly: only 11,597 of its 24,028 recoveries appear in receipts (`record.recovery_evidence` or `source_associations`). **12,431 exist nowhere else**, 12,419 of them `user_accepted_url_variant`. 1,172 receipt recoveries are missing from the file, and 269 bases and 57 recovered URLs differ. | Yes; backed up Oct 24 | d8z3b, standalone; checked directly |
| 7 | docspec-rs after `c949c67`: 60 `cfg(all(not(test), not(feature = "test-util")))` production branches that `scripts/check` never runs, including name-based verification skips for `raw-`, `catalog-`, `obs-` and `source-observations-`. The pinned engine has 1 such branch. | Only if the pin moves past `c949c67` | docspec; confirmed in code |

## Problems confirmed directly (derived data; low priority under greenfield)

- The public viewer has been broken since the Oct 24 Pages deploy. The site reads `https://congressional-data.spicygov.ai/viewer-publications/manifest.json`, which returns 404, while the bucket and `r2.dev` serve it. The live catalog is also v5, and the site accepts only v6 (the v5 decoder was deleted in `3089e771`).
- `scripts/publication/tests/test_workflow_resume.py::...historical_checkout[True]` fails on main (removed fallback, `fb9ed402`).
- news_lake: an older release is unreadable after automatic lifecycle compaction (`no_release`), and an existing append id is accepted twice from a fresh process. Both were reproduced with the local engine build.
- The release fingerprint in `release_identity.py` omits modules the publisher loads (`publish_filename_viewer.py`, `publish_viewer_r2.py`, `constants.py`, `docspec_client`).

## Patterns seen in every batch

- Tickets were created after the work, or created and closed in the same commit.
  Acceptance criteria restate the implementation.
- Measurement was skipped, run after building, or run on fixtures (4–4,096 rows
  against a 1.68M-row catalog) too small to show the motivating cost. Later rewrites
  overrode decisions without re-measuring.
- Tests agree with themselves: a WAF simulator stricter than the deployed rule, mocks
  of guessed engine responses, a stress test that never spills, tests asserting a bug.
- Invariants lived in ticket prose, not tests, so the Oct 20–24 refactors broke them
  silently.
- "Retirements" added a new path beside the legacy one, so code grew instead of
  shrinking (retention went from 9.0k to 27.8k lines).
- Closing notes cite methods, commits and hashes that don't exist. The self-awarded
  "CS300 A+" grades did not hold up.
- Evidence lived in the gitignored `output/` folder and has since been deleted.
- The best work measured first: ct-tuez, ss-wie5, ss-g9sn, ss-1txq, ct-m9td, ct-jl1m
  and ct-qspb.

## Keep / simplify / delete (greenfield consensus)

- **Keep:**
  - the raw capture and custody path (create-only body and receipt writes, verified
    uploads, recovery `checked_put`);
  - the publication raw-key allowlist;
  - the docspec_client transport;
  - the engine's core features: merge, CollectSet, partitions, coalescing.
- **Simplify:**
  - give derived data and the engine warehouse their own bucket and scoped
    credentials, a put-only capture key, and R2 bucket locks on `receipts/` and
    `bodies/`;
  - rewrite publication as an immutable release plus one conditional pointer flip,
    rebuilding on failure;
  - check the runtime pin once, against the application pin.
- **Delete:**
  - compatibility shims and legacy formats;
  - the news_lake DocSpec stack, or at least its PyIceberg oracle;
  - the publication journals, resume and fingerprints;
  - manufactured consumers (ct-13cn, ct-gziq);
  - `delete_gzip`;
  - the five in-process proof registries;
  - in the engine: the 60 test-excluded branches, most of retention, restore points,
    the succession archive and the Dagster adapter.
- **Measure first:** time a full rebuild from raw before keeping any of the
  incremental catalog machinery.
- **Freeze:** browser and performance work until there are users.

## Third pass: evolutionary-refactoring audit

Each reviewer re-read its batch with the `evolutionary-refactoring` skill in audit
mode: recover the contract, name the design pressure, choose the cheapest safe first
move, and list the behavioral evidence needed before code moves. The hotspots below
are merged across batches and ranked by risk to raw data, then by how many places a
change must touch.

| # | Hotspot | Pressure | First move | Raised by |
|---|---|---|---|---|
| 1 | **Production and tests run different code.** congressional-tech has 75 pytest-only branches in 24 modules (from the Oct 22–24 ct-2ukk commits). docspec-rs has 60 `cfg(not(test-util))` branches after `c949c67`. In production, raw state is read from a hardcoded Oct 20 local snapshot whenever its row count matches (`raw_storage.py:655-672`, `catalog_raw_updates.py:155-183`). A capture cache stands in for receipts (`source_capture_inputs.py:61-74`). Catalog adoption hashes the source against itself (`catalog_adoption.py:134-137`). | Parallel implementations; success-shaped fallbacks | Delete the raw substitutions and the pytest gates, behind a characterization test that reads more than 512 URLs. In the engine, delete the dataset-name predicates, then run one integration suite without `test-util`. | mi03a, czsd, docspec |
| 2 | **Raw write rules are scattered.** There are five storage entry points, each with an `immutable` flag. Overwrite is the default outside `indexes/`. A 412 counts as success without comparing bytes. Collision checks are copied in three places and missing for PDFs. Exclusion and PDF policy is probed in 8 files. The exclusion gate fails open. `delete_gzip` exists. | Boolean accumulation; cloned workflows | Delete `delete_gzip`. Then one owner for per-prefix write rules, refusing overwrite of `bodies/`, `receipts/` and `quarantine/` before any I/O, and one owner for verifying existing bytes. Set ingest policy once, at store construction. | d8z3b, kl2a1aa, czsd, syem |
| 3 | **The lossy capture schema** drops `stored_sha256` and backfills it with the content hash (`raw_schemas.py:11-31`, `raw_values.py:37-39`). | Representation exhausted | Delete `CAPTURE_SCHEMA`'s lossy round trip and write the stored format directly. Fix first the tests that assume stored hash = content hash (`test_raw_archive_schema_tuning.py:49-51,228-244`, `e2e/harness/contracts.py:276`). | syem |
| 4 | **Engine binary and pin:** three resolvers and two pin sources. Hosted setup checks only its own descriptor. | Parallel implementations | Make setup compare the descriptor's revision and digest with `QUALIFIED_DOCSPEC_RUNTIME` before any R2 access. Delete the binary search paths and the news_lake resolver. | mi03b, czsd |
| 5 | **Custody client:** three copies of submit/retry logic (`client.py:445-578,619-797,842-915`), with fallbacks that change what a request means. These strip `partition_by`, rewrite row-group sizing, retry raw-state writes without `merge`, or retry on substring matches. | Cloned workflows; defensive sediment | Delete the fallbacks first, then merge the copies. Then: keep inputs on any error unless the engine refused at validation. | mi03a, mi03b, syem, standalone |
| 6 | **Provenance pins are hand lists.** The recovery import omits `docspec_client`, `congress_shared.custody` and `congress_shared.storage`. The release fingerprint omits publisher modules. | Cloned workflows | Reuse the publication dispatcher's folder pinner, or the git tree hash plus `uv.lock`, and delete the hand lists. | standalone, d8z3b |
| 7 | **The storage boundary is code, not credentials.** The public WAF expression allows more than its Python simulator, and `apply` replaces the whole zone's rulesets. | Handwritten infrastructure | Generate the WAF expression from one exact-prefix allowlist and delete the simulator. Later, a staged derived bucket with scoped keys. | kl2a1aa, d8z3b, standalone |
| 8 | **The incremental catalog engine** (~27.8k lines) diverges from tests and fingerprints facade files. | Structural erosion | Make the existing full-rebuild oracle (`tests/historical_raw_catalog.py`) a production operation. Time it on the real corpus, then delete the incremental engine rather than repair it. | czsd |
| 9 | **Viewer publication has two routes,** plus ~1,560 lines of journal and resume. | Parallel implementations | Delete resume (its test already fails), pick one route, then use an immutable release plus one conditional pointer flip. | d8z3a, standalone, d8z3b |
| 10 | **news_lake keeps two backends,** chosen with `hasattr`. | Parallel implementations | Reviewers disagree about which backend survives (see Decisions). | mi03b, kl2a1aa, standalone |
| 11 | **docspec-rs lifecycle records** are string-keyed, with ~35 families and 8 cloned retirement planners. `write_batches_inner` has taken 18 commits since Oct 18. | Branch accretion; structural erosion | Delete the families no consumer writes, then type the rest. Split `write_batches_inner` into stream stages without changing behavior. | docspec |

**Leave alone (confirmed sound or not worth moving):** the raw capture and custody
write path, which has no pytest branches. Also the decoded-memory budget,
`--verify-publication`'s Chromium checks, the review-asset staging, the browser v6
reader, ct-h23e, ct-csyg's pruning, the DuckDB sort, the spill arena, the reuse cache,
the ct-d3un fixes, ct-snh8 and ct-8w0g. In the engine: `Strict<T>`, the remote scope
boundary, key pruning, merge and compaction.

**Calls the third pass changed:**
- ct-dmca: fill missing fields at read time instead of writing a new raw generation.
- Export rights stay in Python.
- The retention planner: delete its reclaim branch.
- Typed-preparation resume: keep.
- ct-xu1o: revert to id keys.
- ct-piku: delete.
- Engine route cuts: keep exactly the ~15 routes the client calls.
- `cli_args.rs`: delete, but keep a positional `hash` through clap.

### Owner decisions (2026-10-24)

| Question | Decision |
|---|---|
| Engine commit protocol | Durable per-phase commits; keep resume after a crash. |
| news_lake | Keep the DocSpec backend; port its crash, fence and merge tests; delete the PyIceberg oracle. |
| Viewer publication route | Finish `export-pins` and make it the only route; delete the journal and resume route. |
| Raw protection | R2 bucket lock on `receipts/` and `bodies/`; keep one bucket (no separate derived bucket for now). |
| Public `r2.dev` access | Leave it open. |
| Engine first | congressional-tech always uses docspec-rs and keeps little or no custom code that overlaps it. Incremental catalog updates move onto engine operations; the Python incremental layer is deleted. |
| Raw index rows with a wrong `stored_sha256` | Repair in place; don't regenerate. |
| Exclusion-list hook | Delete it; no list will exist. |
| Recovery-import code identity | Refuse uncommitted code; record the git commit plus `uv.lock`. |

### Decisions the reviewers left to the owner

1. **Engine commit protocol:** durable per-phase commits, or one commit at the end
   with a rebuild on crash. The second is simpler but conflicts with the docspec-rs
   AGENTS.md rule to preserve expensive phases.
2. **Which viewer publication route survives:** the wired journal route or
   `export-pins`.
3. **Separate derived bucket and scoped credentials:** a staged migration.
4. **news_lake:** keep the DocSpec backend, keep the Python/Iceberg backend, or
   delete news_lake.
5. **Repairing capture-index rows** written with a wrong `stored_sha256`: a data fix.
6. **Whether `accepted.json` is provenance:** a read-only rebuild-from-receipts
   check, before moving anything.

### R2 write activity since Oct 22 (checked directly)

`receipts/` has had no writes since Oct 22. `indexes/raw.json` was rewritten
2026-10-23 05:21 UTC. About 141k `indexes/native-manifests/` objects and many
`source-observations-members-*` datasets were written by local runs between Oct 22
and Oct 24. So the selected native capture index may contain rows with the wrong
`stored_sha256`; confirming that means reading the selected capture table.

## Files

- `batches/<batch>/tickets.txt`: the tickets in that batch.
- `batches/<batch>/<batch>-verdicts.md`: first pass, per ticket, with evidence and
  grades. Some batches also have fork or part files.
- `batches/<batch>/<batch>-greenfield.md`: second pass.
- `batches/<batch>/<batch>-evolutionary.md`: third pass.
- `compiled.json`: every ticket, verdict, grade and raw risk in one file.
