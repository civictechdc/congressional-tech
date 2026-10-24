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
| **All** | | **253** | **90** | **93** | **55** | **10** | **4** | **≈81 (B-)** | **≈79 (C+)** |

kl2a1aa and syem applied the greenfield lens in their first pass. One kl2a1aa ticket
could not be verified. All averages are weighted by ticket count.

## Raw-data status (checked directly, not by a reviewer)

- **Receipts are complete.** All 2,289 receipt objects referenced by the legacy capture
  table (`output/incremental-updates-20261019/adoption-inputs/captures.parquet`,
  3,909,134 rows) exist in `congressional-tech-raw/receipts/` (1.08 GB). None are
  missing, and no receipts exist that the table doesn't reference.
- **No new raw captures since about Oct 19.** Hosted capture failed from Oct 21 to
  Oct 24, first on packaging and then on a stale engine pin. The engine pin was fixed
  on Oct 24; the next scheduled capture is the first chance to resume.
- No finding showed a raw body or receipt being lost, overwritten or deleted.

## Raw-data risks, ranked (consensus across batches)

| # | Risk | Reachable today? | Verified by |
|---|---|---|---|
| 1 | One bucket holds raw, derived, engine warehouse and public data, with bucket-wide write credentials. Raw safety rests on code checks such as the publication allowlist and create-only flags. | Structural | 5 batches |
| 2 | Hosted setup checks the engine binary against its own descriptor, never against `QUALIFIED_DOCSPEC_RUNTIME`. A stale engine can write raw provenance. | Yes (pin correct as of Oct 24, but unenforced) | mi03b, czsd, and this audit's own CI work |
| 3 | `raw_values._to_legacy_capture_table` fills `stored_sha256` with the content hash when a new capture row has none, which is wrong for gzip bodies. Receipts are correct; the native capture index can be rebuilt from them. Since `48137619` (Oct 22). | Yes, for new captures | syem; confirmed in code |
| 4 | `raw_sync --upgrade-source-rules` rewrites the raw-state selector with no old/new comparison. Production-only branches trust local raw files by row count, and `R2Store.read` can serve raw checks from a local cache. | Yes | mi03a, standalone |
| 5 | Latent traps: `migrate_pdf_bodies_to_uncompressed(delete_gzip=True)` deletes the `.gz` body without verifying the `.pdf`; the retention planner treats unknown objects as reclaimable; the `VerifiedFile` constructor trusts caller-supplied hashes; engine `pre_admission` is set by error kind; `R2Store.put` overwrites by default. | No callers today | Several batches; delete_gzip, VerifiedFile and pre_admission confirmed in code |
| 6 | `viewer-publications/recoveries/accepted.json` is mutable, sits under a derived prefix and may hold manual recovery decisions found nowhere else. | Unknown | d8z3b, standalone |
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

## Files

- `batches/<batch>/tickets.txt`: the tickets in that batch.
- `batches/<batch>/<batch>-verdicts.md`: first pass, per ticket, with evidence and
  grades. Some batches also have fork or part files.
- `batches/<batch>/<batch>-greenfield.md`: second pass.
- `batches/<batch>/<batch>-evolutionary.md`: third pass.
- `compiled.json`: every ticket, verdict, grade and raw risk in one file.
