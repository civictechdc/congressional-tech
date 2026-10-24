# syem batch: evolutionary-refactoring audit (Audit mode, nothing changed)

Scope: the hotspots found in syem-verdicts.md (ct-syem, ct-d3un and ct-4t6s groups), re-read through the evolutionary-refactoring loop. Lens: greenfield, so only raw/source data (R2 bytes, receipts, provenance) must survive, and everything derived can be rebuilt. Read-only at c858a5a2. New checks this pass, all through the project `.venv`:
- An in-memory capture round trip: `prepare_capture_table` → `capture_table`.
- Searches over consumers, tests and monkeypatch sites.

Coverage is the hotspots only. This was not a repository-wide audit.

## Ranked hotspots

### 1. Raw capture receipts: a lossy intermediate schema (ct-v9ua; ct-4t6s)
- **Contract:**
  - A capture row is the receipt for an R2 body. It records `sha256`/`bytes` of the content and `stored_sha256`/`stored_bytes` of the stored (gzip) object.
  - Both digests are independent facts, and a body is stored as gzip unless it is a PDF (raw_storage.py:263,274).
  - That independence must hold. Body lookup derives `body_info` from capture rows (raw_storage.py:527-533, 957-964), and corpus_recovery reuses `stored_sha256` (transfer.py:125).
- **Pressure:**
  - *Representation exhausted* by a false premise, and *cosmetic simplification that changed semantics*.
  - `CAPTURE_SCHEMA` (raw_schemas.py:11-31) drops `stored_sha256`, keeping only `is_stored`, on the assumption that it equals `sha256`.
  - `_to_legacy_capture_table` then re-derives it as `stored_sha = sha_hex` (raw_values.py:37-39).
  - *Parallel implementations:* CAPTURE, LEGACY and NATIVE schemas, with translation sitting in the core instead of at the edge.
- **Reproduced this pass:**
  - `stored_sha256 = 'b'*64`, `stored_bytes = 8` goes in. `stored_sha256 = 'aaaaaaaa…'`, `stored_bytes = 8` comes out.
  - The receipt is now internally inconsistent: one object's size beside another object's digest.
  - Every `RawArchive.save` takes this path (raw_archive.py:781).
- **Cheapest safe intervention:**
  - *Delete the lossy intermediate.* The first move: make `prepare_capture_table` emit the schema that is actually stored (`LEGACY_CAPTURE_SCHEMA`, carrying `stored_sha256`) and remove the derivation at raw_values.py:37-39. That leaves one capture representation in the write path.
  - Repairing rows written since Oct 22 (re-hashing the R2 objects) is a data repair, not a cleanup: stage it separately, with agreement.
- **Evidence needed first:**
  - **Missing:** a characterization test that `stored_sha256 ≠ sha256` survives `RawArchive.save` and `RawStorage.prepare`. test_raw_storage.py:198 sets `'b'*64` but never asserts it.
  - **Self-referential, fix or delete first:** test_raw_archive_schema_tuning.py:49-51 and :228-244 (uses `stored == sha`); tests/e2e/harness/contracts.py:276 `FORBIDDEN_RAW_ARCHIVE_COLUMNS`; test_f18 "is_stored replaces stored_sha256". All four encode the false premise.
  - **Good existing anchors:** test_file_backed_capture.py:176 and test_async_capture.py:236 assert the stored-object digest.
- **Earlier call:** confirmed as the #1 severity. Refined: the fix is to delete the lossy schema, not to patch the backfill.

### 2. Retained producer inputs: one deletion policy cloned three times (ct-0n0y, ct-4fcl)
- **Contract:** a staged producer input, which may be a raw capture batch, must survive any failure whose commit state is not proven, so it can be replayed exactly.
- **Pressure:**
  - *Cloned workflows.* The stage → submit → `except BaseException` → `cleanup_safe` → `rmtree` skeleton appears three times (client.py:482-578, 686-797, 856-915), so any change to the deletion rule needs three synchronized edits.
  - *Defensive sediment.* The Python allowlist (models.py:27-56) mirrors the Rust code→kind table (error.rs:20-80).
  - `pre_admission` is derived from the error *kind*, so a serde failure during execution is reported as pre-admission (error.rs:173 → http.rs:284).
- **Cheapest safe intervention:**
  - **First move (structural):** collapse the three blocks into one owner of "stage, submit, retain unless proven refused", with no behavior change.
  - **Second move (behavior):** default to retain. Delete only on an engine signal set at its validation boundary, then remove the Python allowlist.
- **Evidence needed first:**
  - **Existing behavioral tests to keep green:** test_docspec_input_custody.py:56,87,204 (retained_input).
  - **Self-referential:** test_cleanup_safe_matrix only checks the Python classifier against itself, never a real engine error body.
  - **Missing:** a loopback-lane test that feeds real docspec-rs refusal bodies (including a post-admission `invalid_json`) through `cleanup_safe`.
  - **Fix first:** test_read_arrow_pin_and_header_verification currently fails because it builds the client with `__new__` (red on main since f5e8fe1b).
- **Earlier call:** severity unchanged (#3 for raw data). The recommendation changes order: collapse the clones first, then change the policy once.

### 3. Weekly retention mirror: a write-only table that fills gaps with invented values (ct-q29c)
- **Contract:**
  - It mirrors pipeline-data files, and pipeline-data remains the source.
  - It is written by update-data.yml:196, by default into `$RUNNER_TEMP`.
  - The retention readers accept a `tables`/`weekly_tables` parameter (tables.py:32,88,127; jsonl.py:37,68; committees.py:36), but no caller passes one.
- **Pressure:**
  - *Indirection without responsibility:* the mirror has no reader.
  - *Success-shaped fallbacks:* `observed_at` defaults to `"2026-09-27"` (sync_weekly_tables.py:83; weekly_tables.py:736-739) and `congress = 118` (weekly_tables.py:421-423). Both make the data look complete when it is not.
- **Cheapest safe intervention:** *delete* the CLI step and `WeeklyRetentionTables`. If the mirror is kept, the first move is to replace each invented default with null or a refusal.
- **Evidence:** first confirm that no published reader consumes the docspec weekly datasets. The tier4 "real-world" tests re-implement the extraction and never import `weekly_tables`, so they cannot characterize it; delete them along with it.
- **Earlier call: changed** from "fix or delete" to **delete**.

### 4. Raw-body deletion option without a content check (ct-te1p, out of slice; moved by ct-fsbf)
- **Pressure:** a missing guard on the only raw-data delete. `delete_gzip=True` removes the canonical gzip body when a `.pdf` sibling merely *exists* (raw_storage.py:312-316), without reading or hashing that sibling.
- **Cheapest safe intervention:** *delete the `delete_gzip` option.* No caller passes it, and raw bodies never need deleting.
- **Evidence:** the only tests are test_r2_public_edge_and_pdf_storage.py:185,196, and they never exercise deletion.
- **Earlier call:** raised from a footnote to a ranked raw-data item. It is latent today.

### 5. Re-export shims kept alive for monkeypatching (ct-4fcl, ct-fsbf, ct-0bce, ct-unv0)
- **Contract:** none external. `scripts/publication/*.py` are workflow entry points and do have external callers. The `document_index` / `docspec_host` / `docspec_backend` shims are internal.
- **Pressure:**
  - *Compatibility sediment* and *indirection without responsibility*.
  - `_CompatibilityShim.__setattr__` forwards attributes into 8 submodules (document_index.py:51-60).
  - The `gc.get_referrers` class swap (publish-viewer-r2.py:16-25) and the empty `sys.modules` stub (release_identity.py:12-16; reproduced ImportError) exist only so tests can monkeypatch the old module names.
  - Importers: document_index has 8 production and 22 test importers; docspec_host 4 and 2; docspec_backend 2 and 2. There are 42 monkeypatch calls on shim or publisher modules.
- **Cheapest safe intervention:** first retarget the monkeypatching tests to the owning modules, or better, to behavioral seams. Then *delete* the forwarding hacks and shims. Keep the thin workflow entry points, or switch the workflows to `python -m viewer_publication…`.
- **Related:** the release fingerprint's hand-listed file set (release_identity.py:36-58) is where the move drifted. Replace the list with a package glob.
- **Earlier call:** confirmed **delete**, with the order made explicit: tests first. The workflow entry points are a real boundary and should stay thin rather than be deleted.

### 6. Hand-written duplicates of existing infrastructure (ct-8v02, ct-imdo, ct-8od2, ct-wxhg)
- **Body writers:** four new CAS writers (parquet.py:406-428, weekly_tables.stage_body_bytes, senate seed_fetch, the e2e harness) duplicate `raw_storage.put_body` / `physical_body_object_key`. **Delete** them, and set `retained` to the existing raw digest.
- **copy_checked:** `congress_shared.custody.copy_checked` has zero production callers. **Delete it, and do not unify** it with `derived_files.copy_checked`. That one owns a different policy: exclusive hard-link publication restricted to derived catalog keys, with partials kept for diagnosis (derived_files.py:16-20, 79-125). *Revision:* earlier I offered "or migrate derived_files to it". Withdrawn, because these are distinct domains.
- **Unwired code:** the ct-8od2 compaction helpers (lazy exports only) and the `export-pins --publish-to-r2` path. **Delete.**
- **Raw recovery CLI:** `--streamed-recovery` is broken wiring around a tested module. Remove the flag, and keep the module and its tests.

### 7. A shared helper that changed meaning (ct-imdo `parse_utc_timestamp`)
- **Pressure:** *cosmetic simplification that changed semantics.* `reported_time` lost its source offset and now rejects naive input (reproduced).
- **Intervention:** keep an offset-preserving parse at that one boundary. Do not add a mode flag (*boolean accumulation*).
- **Evidence:** add characterization cases for `-05:00` and naive inputs; the fixtures only contain `Z`.
- **Earlier call:** severity stays low (derived data). Confirmed.

### 8. Leave alone
- **ct-d3un fixes:** sound. ct-u7gg's proof object is carried as an attribute on a dict subclass, and `dict(...)` strips it. The only cost is a redundant validation pass on derived catalogs. Leave it.
- **dev.py clean:** its posture is right for raw data. The only issue is that the walk descends into `.cache`/`output` before filtering.
- **ct-4g55 spill arena and ct-3bfx reuse cache:** *revision.* Earlier I floated deleting both. The arena has a documented bounded-memory rationale (ct-4g55 architect note), the reuse key is now correct with an end-to-end test, and no failure was observed. Deleting them is speculative until a full rebuild is measured.
- **The `AppearanceRow` facade and `noImplicitAny`:** fix them only when that code is next touched.

## Changes to earlier calls
1. **ct-q29c:** fix-or-delete → **delete**.
2. **raw_storage `delete_gzip`:** promoted to a raw-data item; delete the option.
3. **ct-v9ua:** the fix is to delete the lossy schema, not to patch the backfill.
4. **ct-0n0y:** collapse the three clones before changing the policy.
5. **copy_checked:** delete the unused copy only; no unification.
6. **Spill arena and reuse cache:** delete → **leave alone**.
7. **Shims:** retarget tests first, and keep the thin workflow entry points.
