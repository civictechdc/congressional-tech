# kl2a1aa: evolutionary-refactoring audit (Audit mode, greenfield lens)

Scope: the hotspots found by passes 1–2 across ct-8kl2 and ct-a1aa, re-read through the skill's loop. Nothing was changed. No tests were run in this pass.

Coverage note: I re-inspected the raw-write path, the edge policy, body_key derivation and the news_lake backend dispatch. The derived-data stacks are taken from the earlier passes without new inspection.

Ground rule (greenfield): only raw bytes in R2, their receipts and their provenance must survive. Everything else can be rebuilt. One consequence matters in several places below: legacy *raw* table shapes are themselves raw data. Readers for them are required compatibility, not sediment.

---

## H1. Public exposure policy for the raw bucket (ct-te1p, ct-84xa, ct-1qbq). Severity 1.

**Contract and current model.**
- The custom domain fronts the whole `congressional-tech-raw` bucket.
- What may be public:
  - content-addressed bodies (`bodies/sha256/<xx>/<sha>.{gz,pdf}`)
  - published viewer and export releases, plus their manifests
- What must stay private: receipts, indexes, state, quarantine, publication attempts (`viewer-publications/attempts/`, continuation.py:367) and recovery inputs (`viewer-publications/recoveries/accepted.json`).
- The retired Worker encoded this as one strict regex (worker.mjs:2 at 4ed77e3f^).

**Design pressure.**
- *Parallel implementations of one policy.* The deployed WAF expression (edge json:35) and the Python simulator (r2_edge_rules.py:64-105) disagree:
  - The expression allows any `/viewer-publications/*` except `accepted-*`, and any `/exports/*`.
  - The simulator allows only exact shapes.
- *Handwritten infrastructure replacing established behavior.* There is a bespoke Cloudflare REST client, and it PUTs the zone-wide entrypoint rulesets (apply_r2_edge_rules.py:278, 284). A hand-written evaluator stands in for Cloudflare's own rule evaluation.
- *Self-referential tests.* test_r2_public_edge_and_pdf_storage.py:253-356 and test_r2_edge_rules.py:67-96 check the simulator, never the expression. test:299 asserts that `/exports/accepted-internal.json` is blocked, but the real rule allows it. test_r2_edge_rules.py:36-38 only checks that substrings are present.

**Cheapest safe intervention.** First move: make one exact-prefix allowlist the single authority, then generate the WAF expression from it.
- The allowlist entries: `/viewer-publications/manifest.json`, `/viewer-publications/catalogs/`, `/viewer-publications/releases/`, `/bodies/sha256/`, `/exports/manifest.json`, `/exports/releases/`, `/exports/snapshots/`.
- Delete the regex simulator rather than keep a second policy.
- In `apply`, read the existing entrypoint and merge by `ref` before writing, so it cannot wipe other hosts' rules.
- Moving private prefixes to a private bucket is the platform-primitive end state. It moves raw data, so it is a staged redesign (copy, verify by digest, then cut over), not a cleanup.

**Behavioral evidence needed first.**
- Fix or delete the simulator-based assertions, starting with test:299.
- Add one test that pins the generated expression's prefix set to the expected allowlist.
- Record a live `verify-live` run that probes `/viewer-publications/attempts/x`, `/viewer-publications/recoveries/accepted.json` and `/exports/accepted-x`. This is an owner action; network access was off-limits in this review.

**Change to earlier calls.** Severity confirmed. The earlier "split buckets" call is narrowed: split buckets is the end state, but tightening the prefixes comes first because it moves no raw data.

---

## H2. Raw ingest policy has no single owner (ct-te1p, ct-ec91). Severity 2 (raised).

**Contract and current model.**
- Raw bytes are written once, immutably, under a sha-keyed `.gz` key.
- They are never deleted or overwritten.
- An existing object is re-verified by digest (body_files.py:137-149, which is sound).
- An optional `.pdf` sibling holds the same bytes.

**Design pressure.**
- *Boolean accumulation and cloned enforcement.*
  - `excluded_body_hashes` and `store_uncompressed_pdfs` appear 40 times across 8 files.
  - Each layer probes them with `getattr` and enforces them itself: r2.py:370-372 and 413-416; catalog_cache.py:85-87; body_files.py:129-136 and 150-154; raw_archive.py:366-367 and 382; raw_storage.py:191-198, 787-797 and 950-954; pdf_backfill.py:171-176.
  - Production turns both off (raw_sync.py:320-325).
- *Success-shaped fallback.* A missing default exclusion file returns an empty set (raw_storage.py:134-137), and that file has never existed in git (raw_storage.py:76-83). The gate fails open.
- *Defensive sediment on the streaming path.* When enabled, the gate calls `path.read_bytes()` (body_files.py:133; r2.py:416), which loads whole large bodies into memory and defeats streaming.
- *Dormant destructive option.* `delete_gzip` deletes the canonical `.gz` once a `.pdf` merely exists, with no digest check (raw_storage.py:313-316, 330-331). It only stays inert because no store defines `delete`.
- *Cloned workflow.* There are two decompress-and-verify functions (pdf_backfill.py:102-156) and two PDF migration paths (`migrate_pdf_bodies_to_uncompressed` and `backfill_uncompressed_pdfs`).

**Cheapest safe intervention.** First move: delete `delete_gzip`. It is pure deletion, has no callers and removes the only raw-delete code path in this area.

Then settle each flag once at the store boundary (the R2Store/LocalStore constructor) and remove the per-layer probes:
- **Exclusions:** either an explicit, versioned input that fails closed when missing, or delete the gate entirely if no review list will exist.
- **PDF siblings:** always or never. Do not leave it as a per-call option.

Then collapse the two migration paths into the backfill.

**Behavioral evidence needed first.**
- Keep `test_pdf_backfill_rejects_sha256_mismatch` and the idempotency tests (test_pdf_backfill.py:73-178); they are good characterizations.
- Missing:
  - a test that builds the store through raw_sync's factory and asserts the intended policy;
  - a test that a missing exclusion source fails closed;
  - a guard test that no `bodies/` key is ever deleted.
- test_r2_public_edge_and_pdf_storage.py:201 passes the exclusion file directly, so it cannot see production wiring.

**Change to earlier calls.** Raised from 4 to 2. The pressure sits on the active raw-capture path and spans 8 files, not just one dormant flag.

---

## H3. body_key provenance became a read-time derivation (later regression, ct-te1p invariant). Severity 4 (unchanged).

**Contract.** `body_key` equals `'bodies/sha256/<xx>/<sha>.gz'` forever, and it feeds every source_id and document_id.

**Current model.**
- The normalized raw schemas no longer store it; `derive_body_key` and `with_derived_body_keys` reconstruct it on read (raw_schemas.py:176-216).
- Legacy raw schemas still carry the literal key (raw_schemas.py:48-74). Those readers are *required* compatibility, because old raw tables are raw data.

**Design pressure.** *A cosmetic change that changed semantics.* f2fea711's "normalization" routed the derivation through `physical_body_object_key`, which produced `.pdf` keys. It also added a test asserting that bug. The unused `media_type` parameter (raw_schemas.py:176) keeps inviting per-format logic.

**Cheapest safe intervention.** Leave the derivation alone; it is now a pure function with a golden test (test_raw_archive_schema_tuning.py:183-195).
- First move, evidence only: add a frozen source_id/document_id fixture for a PDF row through the read path, so an ID change fails loudly.
- One-time verification: check the persisted raw-bodies routing index for `.pdf` keys written during Oct 22 20:16 to Oct 23 18:44 (`_prepare_bodies`, raw_storage.py:943-966).
- Optional: drop the dead `media_type` parameter.

**Change to earlier calls.** Confirmed. The skill adds one point: keep the legacy raw-schema readers. An earlier instinct to delete "compatibility" here would have endangered raw data.

---

## H4. news_lake: two storage backends, with guarantees on the bypassed one (ct-a1aa, ct-1h4g, ct-upl1, ct-07eg, ct-fyid, ct-owh2, ct-5yof, ct-a3le). Severity 3 (was 2).

**Contract.**
- News captures and versions are raw source data.
- There is a single fenced writer.
- Upserts are monotonic.
- A version's text expires with its capture (C5).

**Current model.**
- Production is `DocSpecLake` (cli.py:1-12, 62-69).
- The Iceberg `Coordinator`/`releases` are kept as an oracle, and calls are dispatched to `DocSpecLake` through `hasattr` (releases.py:185-197; coordinator.py:281).
- `DocSpecLake.publish_release` checks the epoch once at the start (lake.py:656). `commit_records` does not re-check it (lake.py:498-575). `fenced_commit` checks only before and after its block (lake.py:242-246).

**Design pressure.**
- *Parallel implementations with `hasattr` multi-dispatch.*
- *Fixes landed on the bypassed path.* The crash matrix, `validated_ids` and `allowed_extra` exist only on the oracle.
- *Representation gap for C5.* Expiry is a cross-table fact computed from whatever tables happen to be in the read (analysis/export.py:83-88).
- *Self-referential qualification.* The schema symlink makes test_contract_records.py:25 compare a file with itself, and docs/checks/validate.py:38-56 delegates to the package it is meant to check.

**Cheapest safe intervention.** First move: make the C5 gate always load captures for the exported versions. This is a known-defect fix and must be scoped as a behavior change.

Then collapse the two backends:
1. Port the crash, fence and merge cases as backend-agnostic contract tests whose expected values come from the contract.
2. Run them against `DocSpecLake`.
3. Re-check the epoch per dataset commit.
4. Delete the Iceberg backend and the `hasattr` dispatch.

Temporary coexistence is justified only until those contract tests replace the differential oracle.

**Behavioral evidence needed first.**
- Pin the schema by digest against git, not by comparison with a file inside the tree.
- Restore an independent packet checker.
- Add tests for a C5 subset read and for a lease stolen mid-publish (both are expected to fail today).
- test_docspec_backend.py's parity suite is the current characterization. Keep it until the contract tests exist.

**Change to earlier calls.** Lowered from 2 to 3. The fencing and `fsync` gaps are confirmed in code, but harm needs concurrent writers or an OS crash, and the CLI is single-writer, so the harm is a hypothesis. The delete-the-oracle recommendation is confirmed, now with an ordering: contract tests first.

---

## H5. Derived publication stacks (ct-2yl5, ct-bwac, ct-gi01, ct-3ttc, ct-6rnk, ct-h23e, ct-s9p2). Severity low.

**Contract.** All of these are projections that can be rebuilt from raw. Nobody consumes them yet.

**Design pressure.** *Compatibility sediment and parallel implementations:*
- viewer `.bin`/details/roots alongside occurrences.parquet (filename_native.py:293-310, 404-406);
- Python-written Parquet alongside an optional, ephemeral ExportPin re-export, whose digests no longer match after f2fea711 (docspec_views.py:683-687; export.py:957-975);
- continuation.py resuming old attempts.

**Cheapest safe intervention.**
- Delete the losing path in each pair.
- viewer: keep one output format and delete `.bin`, details, roots and continuation.
- explorer: delete the optional docspec re-export and export-pins.json rather than "fixing" the second authority.
- s9p2: fix the `source_record` key (IDs are free to change in a greenfield project) and delete the dedup.

**Revisions.**
- **ct-bwac is split.** Catalog-side routing is derived, so delete it: CatalogMemberships, CatalogRows, catalog_staging and catalog_scope with their sqlite. Raw-side routing is raw provenance, so leave it alone: `StateRoutes` and the `raw-bodies-v1`/`raw-deliveries-v1` RoutingPages (raw_storage.py:813-816). Replacing them with Bucket(N) is a staged migration of raw indexes that needs a differential reader test, not a cleanup.
- **ct-h23e:** leave alone. The pread arena works and was measured. Delete it only as part of an explicit explorer redesign, because cleaning up derived code is not worth the risk on its own.

**Evidence.** Rebuild from raw and compare the published file inventory. These derived outputs need no characterization beyond that.

---

## What did not change

- The resolver's unpinned fallback (docspec_client/binary.py:30-45) stays low. The raw write path loads an explicit, qualified binary through `NativeDatasets.from_config` (raw_sync.py:377-381; client.py:242-272), so only derived tools see the fallback.
- The a1aa performance items (ct-07eg, ct-qxqp, ct-3lz2) stay low. They run on oracle or derived paths.
