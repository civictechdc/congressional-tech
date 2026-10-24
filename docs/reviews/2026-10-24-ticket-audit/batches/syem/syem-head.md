# syem batch verdicts: ct-syem, ct-d3un, ct-4t6s epics and children (33 tickets)

Reviewed read-only at congressional-tech `main` c858a5a2 (2026-10-24) and docspec-rs d9c6719. The work was split across four reviewers. Each part file keeps its own method notes, probe scripts and limits:
- syem-part-syemA.md: ct-syem, 0n0y, unv0, 3bfx, imdo, 4g55, sbdp, bzl9
- syem-part-syemB.md: ct-4fcl, fsbf, 0bce, wxhg, ne06, tcs4, elhm
- syem-part-d3un.md: the ct-d3un group
- syem-part-4t6s.md: the ct-4t6s group

All tests were run through the project `.venv`. The rows below are merged from those files by syem-merge.py, with columns reordered and nothing else changed.

## Counts
- **Verdicts:** LANDED-SOUND 11, LANDED-CONCERNS 6, PARTIAL 15, NOT-LANDED 1, SUPERSEDED 0, CANNOT-VERIFY 0.
- **Average proposal grade:** 78.7 (C+). By epic: d3un 84.2, 4t6s 79.9, syem children and epic 74.2.
- **Average work grade:** 72.9 (C). By epic: d3un 87.5, 4t6s 60.3, syem children and epic 68.1.
- **Lowest combined grades:** ct-8od2 (P 80 / W 38), ct-bzl9 (66/56), ct-v9ua (72/50), ct-fsbf (67/57), ct-elhm (60/66).

## Severity, ranked for a greenfield project where only raw/source data must be salvaged
1. **ct-v9ua: raw capture receipts are being written wrong.**
   - The surviving legacy round-trip writes `stored_sha256 = sha256` on every new gzip capture (raw_values.py:21-73). It should hold the digest of the stored gzip object.
   - Reproduced through `prepare_capture_table` → `capture_table`.
   - corpus_recovery consumes this field (transfer.py:125,136).
   - Affects every capture since Oct 22.
   - **Action:** fix now, then re-derive stored_sha256 for affected rows from the R2 objects.
2. **ct-q29c: invented provenance in the weekly retention mirror.**
   - `observed_at` is hardcoded to 2026-09-27, outcome is `present` on every row, and there are congress=118 and 1970 sentinels.
   - `payload_json` was dropped, and bodies are only staged in an ephemeral workspace.
   - The source pipeline-data still exists, so this corrupts a mirror, not the originals.
   - **Action:** remove the made-up defaults (leave nulls), or delete the write-only mirror.
3. **ct-0n0y residual: retained producer input can still be deleted after admission.**
   - `pre_admission` is derived from the error kind. Any serde error becomes `invalid_json`, which maps to 422 with pre_admission=true (error.rs:173, http.rs:284).
   - `cleanup_safe` then lets `shutil.rmtree` remove the retained producer input (client.py:555-578).
   - **Action:** set pre_admission by request phase, and never rmtree a retained input on error.
4. **ct-fsbf: the raw-recovery `--streamed-recovery` mode cannot run.** It raises TypeError on every call (cli/raw_sync.py:469 vs streamed_recovery.py:31). It fails closed, so no data is harmed. **Action:** delete the mode or fix it with a CLI test.
5. **ct-wxhg: a write into the raw bucket that points at nothing.** `export-pins --publish-to-r2` repoints `viewer-publications/manifest.json` in bucket congressional-tech-raw at a manifest it never uploads, using placeholder defaults (publication_cli.py:41-42,155-170). The prefix is derived, but the bucket is shared with raw data. **Action:** delete the command.
6. **Low (derived data, rebuildable):**
   - ct-8v02: lost source facts/links, 404 saved-original links.
   - ct-unv0: publisher dropped from its release fingerprint.
   - ct-3bfx: duplicate review-identity JSONs.
   - ct-imdo: `reported_time` now shifts dates and times to UTC and rejects naive timestamps.
   - ct-4g55: site-wide `noImplicitAny: false`.
   - ct-jnw5: one-witness summaries, no page indexes.
   - ct-8od2: about 500 unwired lines.
   - ct-u7gg: double validation on 2 routes.

**Out of slice, raw-data relevant:** `migrate_pdf_bodies_to_uncompressed(delete_gzip=True)` deletes the canonical gzip body as soon as a `.pdf` sibling merely exists, without hashing that sibling (raw_storage.py:312-316; origin ct-te1p, moved in e4b3216b). No caller passes `delete_gzip` today. Also, raw_storage.py:654-672 branches on `PYTEST_CURRENT_TEST` (noted by the 4t6s reviewer).

## Keep / simplify / delete, per epic
- **ct-syem (simplify/delete).**
  - **Keep:** the real bug fixes (cleanup_safe plus the engine `pre_admission` flag, the reuse key, InflationSource, the binary resolver, the house-naming lazy load).
  - **Delete:** every compatibility shim, because nothing external imports them in a greenfield repo:
    - document_index `_CompatibilityShim`
    - docspec_client/docspec.py and docspec_host.py
    - retention/docspec.py
    - news_lake docspec_backend.py
    - the scripts/publication gc shim
    - the release_identity sys.modules stub
  - **Also delete:** the unwired or broken "staged capability" modes (streamed-recovery, export-pins), the unused congress_shared `copy_checked`, one of the duplicate review-identity JSONs, and the metric goals (parameter counts, docstring percentages).
- **ct-d3un (keep).** The 8 small fixes are sound. Drop the ceremony: the 168-entry six-grade rescore and the receipt machinery in gitignored output/. For ct-u7gg, fix the dict-subclass proof carrier or accept re-validation.
- **ct-4t6s (delete most, fix one thing urgently).**
  - **Fix first:** ct-v9ua.
  - **Delete:** the unwired compaction helpers (8od2), the four hand-rolled CAS body writers, and the fabricated weekly defaults.
  - **Instead:** point `retained` at the existing raw CAS bodies (`put_body` / `physical_body_object_key`).
  - Treat explorer and weekly tables as rebuildable outputs of raw data, not as data to migrate.

## Patterns across the batch
1. **Measurement skipped before building (ct-syem and ct-4t6s).**
   - syem proposals leaned on LOC, parameter and docstring counts; at least 9 claims were false. ct-imdo's "4x hashing" was in a function with no production callers.
   - 4t6s measured the problem well, but no numeric AC was measured after the change.
   - d3un is the exception: three follow-ups were rejected on measurement.
2. **Closed in the commit that created the ticket.** syem and 4t6s tickets were born `closed` inside their fix commits, with empty commit bodies and no per-AC notes. ct-syem's gate (`dev.py check`) runs no tests.
3. **Decomposition by re-export shim and facade.** Coupling did not change, and hacks such as `gc.get_referrers`, sys.modules stubs and `__setattr__` forwarding exist only to keep old monkeypatching tests alive.
4. **Gaps "fixed" by fabrication or loosening:** made-up non-null defaults, `noImplicitAny: false`, broadened `except Exception`, index-compatible "typed" rows.
5. **Tests that cannot see the defect:**
   - 15 e2e files import no product code.
   - Fixtures only contain `Z` timestamps.
   - Key-name-only tests for the R2 pointer.
   - A live contract test that skips whenever the binary differs.
   - One ct-0n0y regression test is red on main.

## Table
