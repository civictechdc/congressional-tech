# mi03a: evolutionary-refactoring audit (Audit mode, greenfield lens)

This pass only inspects and recommends; it changes no code. It applies `evolutionary-refactoring` to the hotspots found in `mi03a-verdicts.md` and `mi03a-greenfield.md` (both unchanged). The greenfield rule still holds: only the raw/source data in R2 `congressional-tech-raw` (captured bytes, receipts, provenance) must survive. Paths are relative to `/Users/mikewolfd/Work/congressional-tech` unless prefixed with `rs:` (`/Users/mikewolfd/Work/spicy-stack/docspec-rs`).

Coverage: 9 hotspots across the 24 tickets. Sound tickets with no structural pressure are left alone and listed at the end.

---

## H1. Raw reads replaced by unverified local copies, and production behavior that differs from tested behavior (rank 1)

- **Contract.** Raw state and capture reads must return exactly the pinned, digest-verified native rows that the raw selector names. That is the provenance of every derived build.
- **Current model.** 75 `PYTEST_CURRENT_TEST` branches sit in 20 production modules. The worst are:
  - `retention/raw_storage.py:655-672`: when 512 or more URLs are requested and `output/incremental-updates-20261019/adoption-inputs/state.parquet` has the same row count, rows are read from that local file. Errors are swallowed by `except Exception: pass`.
  - `retention/source_capture_inputs.py:61-74`: `.cache/docspec-catalog/captures-0.parquet` is used whenever the schema and per-row-group row counts match.
  - `retention/catalog_dependency_preparation.py:195-210,348,362,525`: receipts are trusted without hashing, and the reader batch size is unbounded in production.
- **Pressure.** Two parallel implementations: tests exercise one path and production runs another. On top of that sit **success-shaped fallbacks** (substitution matched by row count, swallowed exceptions). This is the worst kind of sediment, because no test can observe the production branch.
- **Cheapest safe intervention.** Delete the production-only branches so one code path remains. Where a branch carried a real performance knob (batch rows, thread pool), pass it as an explicit parameter that the test also sets.
  - **First move:** delete the two raw substitutions (`raw_storage.py:655-672`, `source_capture_inputs.py:61-74`). They are the only places that can change raw provenance silently.
- **Evidence needed first.**
  - The existing tests (for example `packages/congress_api/tests/test_catalog_raw_updates.py`) characterize only the generic path.
  - Missing: a characterization test for `iter_states_for` with more than 512 URLs, asserting the ordering by `STATE_ORDER` and exact rows. Add it, then delete the branch. Nothing should change under pytest.
  - Missing: a guard test that fails if `PYTEST_CURRENT_TEST` appears in `packages/*/src`.
- **Change to earlier calls.** This **rises to rank 1**; in the greenfield pass it was R2, behind R1. The greenfield pass also proposed deleting the typed-preparation receipt/resume machinery. That is **revised to leave alone**: resume serves large rebuilds and is sound once the pytest branches are gone, so deleting it would be churn with no concrete gain.

## H2. Raw producer submission in `docspec_client` (rank 2)

- **Contract.** Write the producer file and submit it once. If the outcome is unknown, keep the file and an exact replay request. Delete it only after a proven pre-admission refusal or success (the ct-3faj ACs). This is the custody layer that every raw capture and state write goes through.
- **Current model.** `packages/docspec_client/src/docspec_client/client.py:445-578` (`run_table`) and `:619-780` (`update_table`) are two copies of the same skeleton. Both contain, in order:
  1. a 415 → Parquet fallback (:478, :683);
  2. an "unknown field" retry that strips `partition_by` or `merge`;
  3. a rewrite of the producer file with legacy row groups after `operation_conflict` (:521-534);
  4. message-substring "transient" retries (:536-552, :~757-770), with a no-op `attempt += 1` inside a `for` loop.

  There is also `except TypeError:` in `retention/raw_storage.py:1216-1233`, which silently retries without the merge spec.
- **Pressure.** Compatibility sediment from older engines (one engine is now pinned). Success-shaped fallbacks: retries that guess from message text, and silently dropping the merge semantics. A **cloned workflow**: any custody rule change needs two synchronized edits.
- **Cheapest safe intervention.**
  - **First move:** delete the compatibility fallbacks and substring retries in both copies, so each submits exactly once.
  - Then collapse them into one `_submit_with_custody(request, files)` owner. Keep `cleanup_safe` (`client.py:62-72`) as the single decision point.
  - Delete the `except TypeError` fallback.
- **Evidence needed first.**
  - `packages/congress_api/tests/test_docspec_input_custody.py:29-131` characterizes retention and cleanup, but it is **blind to resubmission**: its `_request` stubs never count calls.
  - Before moving anything, add a parametrized assertion that `_request` is called exactly once for every unknown-outcome error. It will fail today; that failure confirms the defect.
  - Keep the real-binary tests in `test_docspec_host.py` as the boundary check.
- **Change to earlier calls.** Confirms "keep and simplify". It adds the merge into one submission owner as the follow-up move.

## H3. Raw-state schema evolution plus manufactured backfills (ct-dmca) (rank 3)

- **Contract.** Raw URL-state leaves are provenance. They must stay readable as they were written, and the raw selector must never point at rows whose values differ from the receipts.
- **Current model.** `rule-upgrade` evolves the raw state in place (`retention/raw_storage.py:1300-1450`) and republishes the raw selector (`:1279-1298`). Every rule upgrade also backfills `has_body`, `is_saved_capture` and `has_source_url` over every catalog chunk (`retention/catalog_raw_updates.py:96-135,707-721`), and nothing reads them.
- **Pressure.** A wrong abstraction: the general native schema-evolution machinery is pointed at raw provenance. It adds verbosity (dead outputs) and a representation question: does an old leaf without `links_scanned` mean False, or unknown?
- **Cheapest safe intervention.**
  - **First move:** delete the default scalar backfills and their pins in `native_schema_backfill`. That is pure dead output.
  - Second, replace in-place evolution with **normalization at the read boundary**. Old-schema raw leaves get `links_scanned` filled when read. New rows are written with the current schema. The selector is never republished just to change a schema.
  - Per the skill, raw R2 data with the old schema is a supported legacy input. Normalize it at the edge; don't migrate it.
- **Evidence needed first.**
  - `test_catalog_raw_updates.py:506-600` and `test_native_features.py:253` check that source files are unchanged and old pins are readable. That is good characterization.
  - However, `test_catalog_raw_updates.py:~565` asserts that historical rows read `links_scanned is False`. That bakes in a provenance claim ("not scanned") that may be wrong. Decide False versus NULL explicitly before keeping that assertion.
  - Missing: a test that, for every pre-existing column, an evolved or normalized leaf's rows equal the base leaf's rows.
  - The backfill assertions (`:36-41`) only check that the manufactured backfill ran. Delete them together with the backfill.
- **Change to earlier calls.** The greenfield pass said "delete evolution; write a new raw generation verified row for row". That is **revised to normalization at the read boundary**. A raw data migration is a riskier move than the problem needs. Deleting the backfills is confirmed.

## H4. Retention planner (ct-a70m) (rank 4)

- **Contract.** None that a greenfield project needs. The raw policy is "never delete", and derived data is rebuilt.
- **Current model.** `retention/native_capacity.py:430-575` re-implements protection in Python. It uses guessed response fields (`path/protected/status/reasons`), while the engine returns `objects:[{object, blocker}]` (`rs:src/model/retention.rs:83-99`). It protects by substring match (`any(pin_id in path …)`). Its only caller passes no objects (`cli/raw_sync.py:437`).
- **Pressure.** Handwritten infrastructure duplicating established behavior: the engine already decides protection and reports `protected_bytes`. A loosely shaped dict represents a typed native record. **Self-referential tests**: `test_native_capacity.py:257-300` builds a fake native that returns the guessed schema.
- **Cheapest safe intervention.** **Delete** the planner, the `retention-plan` CLI mode and the fake-native test together.
  - **First move:** add a guard test asserting that `NativeDatasets` exposes no `/retention/removal/execute` call and no raw-prefix deletion. It passes today (grep of `client.py`). Then delete.
- **Change to earlier calls.** Confirms delete.

## H5. Manufactured native consumers (ct-13cn, ct-gziq) (rank 5)

- **Contract.** `prepare()` returns the next catalog dependency/observation selection. No other effect is part of its contract.
- **Current model.** Side-effect blocks:
  - `retention/catalog_dependency_storage.py:684-826` writes scratch `catalog-dep-v3-scope-<hash>` datasets plus alias-summary refreshes.
  - `retention/source_observations.py:700-760` writes `source-obs-scope-<hash>` datasets plus summaries.
  - `retention/native_capacity.py:281-316` counts by streaming every change row.
  - The adapter guesses field names (`native_features.py:293`).
- **Pressure.** Verbosity: redundant transformations (re-deriving a diff that is already known) and dead outputs (`last_change_report`, `last_refresh_summary`). Indirection without responsibility.
- **Cheapest safe intervention.** **Delete** the blocks and attributes. Keep at most the thin `compare`/`changes`/`refresh` methods on the client.
  - **First move:** delete the two scratch-scope blocks; they are pure side effects.
- **Evidence needed first.** The prepare-result tests must stay green; the test files that exercise `prepare` are in `packages/congress_api/tests/`. The assertions on `last_change_report` and `last_refresh_summary` (`test_native_features.py:913-994`) are self-referential: they assert the side effect exists. Delete them with it.
- **Change to earlier calls.** Confirms delete. Under this framing, ct-9few's fix also points to a missing representation: typed native response records instead of `dict.get` guesses. That is a narrow boundary fix, worth making only where a native response is consumed after these deletions.

## H6. Two authorities for the C5 export rights policy (ct-4nyy, ct-f11a) (rank 6)

- **Contract.** A public export must contain only what C5 allows (rights, expiry, derived copies). This is about exposure, not raw preservation.
- **Current model.** The Python `export_release` (`packages/news_lake/src/news_lake/analysis/export.py`, tested in `tests/test_export.py:102-175`) produces the returned `tables`. Native `build_c5_export_policy` (`docspec/schema.py:~245-300`; only its shape is tested, at `test_docspec_backend.py:2434`) produces the files.
- **Pressure.** A cloned policy with **shotgun change**: one rights rule needs synchronized edits in two languages, and nothing checks that they agree.
- **Cheapest safe intervention.** One authority. **First move:** add a differential test that the natively exported rows equal `export_release` output for the same release, including the boundary case `retain_until == now`. If they agree, delete the native computed-column policy. Export the Python-filtered rows through the single write path, and still export unchanged tables directly from their pins (that part of ct-f11a stays).
- **Change to earlier calls.** The greenfield pass recommended "keep one native C5 policy". That is **revised: keep the Python domain policy as the authority**. It is the tested domain owner; the native copy is the unverified clone. The O(corpus) memory concern is acceptable for derived data nobody uses yet.

## H7. Duplicate rules in the engine export sanitizer and footer accounting (ct-3li2) (rank 7)

- **Contract.** Exported schemas carry only allowlisted types and field-id metadata, and footer bytes are counted per leaf. This matters for exposure because the public bucket is the raw bucket.
- **Current model.** The allowlist and metadata stripping exist twice: `rs:src/engine/export/validation.rs:238-306` and `rs:src/engine/export/pipeline/parent.rs:85-150`. They already differ (Utf8View/BinaryView mapping and ID assignment). Footer accounting is copied three times (`rs:src/engine/export.rs:545`, `export/pipeline.rs:527`, `export/pipeline/child.rs:266`).
- **Pressure.** A cloned policy that is already diverging.
- **Cheapest safe intervention.** **First move:** extract the footer-byte computation into one function used at all three sites. That is a mechanical move with identical semantics. Then have both sanitizers share one recursive type-allowlist function. Keep ID assignment as a separate step, not a boolean flag (to avoid boolean accumulation).
- **Evidence needed first.** `rs:src/engine/export/tests.rs:16,181,370` characterize the flat path. Missing: the same descendant-metadata-stripping assertion for the policy/pipeline export path. Add it before merging.
- **Change to earlier calls.** Confirms. Priority stays low.

## H8. Hand-written pruning evaluator (ct-csyg) (rank 8, leave alone)

- **Contract.** Never skip a file that might hold a matching key. Correctness here now guards raw-state Updates (`retention/raw_storage.py:1187-1233`).
- **Current model.** `rs:src/query.rs:600-720` and `rs:src/engine/key_pruning.rs`. Exhaustive oracle tests landed in `rs:381108c`.
- **Pressure.** On reflection, the hand-writing is **genuinely required**. Iceberg's evaluators are crate-private, and multi-key point pruning plus the >200-item IN threshold are not expressible through `with_filter`. One real clone remains: the exactness rule for truncated or NaN bounds lives twice (`rs:src/query.rs:517-540` and `rs:src/engine/key_pruning.rs:735-746`).
- **Cheapest safe intervention.** Leave it alone. Optional first move: have `query.rs` call `key_pruning::untruncated_bound`.
- **Change to earlier calls.** **Severity lowered.** I originally criticized it for reversing its own "reuse" note. Under the skill's guidance not to restore a library blindly when custom behavior is required, and with oracle tests in place, it is sound.

## H9. News lake: parallel backends and two compaction policies (ct-8ax6, ct-dzyf, ct-5fkx) (rank 9)

- **Contract.** Derived and rebuildable. Nothing uses it yet.
- **Current model.**
  - App-level threshold compaction (`docspec/compaction.py:129-245`) overlaps engine tail coalescing (`rs:src/engine/write/compaction.rs:15-28`).
  - `abandon_cycle` exists twice, for PyIceberg (`storage/coordinator.py:288-345`) and DocSpec (`docspec/lake.py:771-900`).
- **Pressure.** Parallel implementations.
- **Cheapest safe intervention.** **First move:** measure. Run a news poll loop through `DocSpecLake` with the app compaction disabled. If engine coalescing alone keeps active files bounded, delete the app compaction.
  - On the PyIceberg backend I hold a **hypothesis only**. The pure-Python view evaluators are a meaningful differential test seam, so keep them. Delete the PyIceberg storage backend only after confirming no oracle test depends on it.
- **Change to earlier calls.** The greenfield pass said "drop the PyIceberg reference oracle". That is **softened**: keep the differential oracle seam and drop only the redundant storage backend, after verification.

## Left alone: no material structural pressure in the inspected scope

These are sound, and touching them would be cosmetic: ct-clvr (occurrence planning reuse), ct-5fkx engine side, ct-csjp, ct-copj, ct-bt1q, ct-egpe, ct-eipa, and ct-cpio (except one stale comment at `rs:src/storage.rs:428-436`). The DuckDB external sort in ct-adu0/ct-ccy4 stays: it is the established library choice.

## Evidence for this pass

- Run this pass: reads and greps only.
- Run in earlier passes, with the project venv: `packages/news_lake/tests/test_docspec_backend.py` (26 passed) and `packages/congress_api/tests/test_catalog_dependency_preparation.py::test_preparation_external_spill_and_recovery_within_staging_budget` (passed).
- Not run: the call-count custody assertion, the differential C5 test, the >512-URL state characterization, and engine tests (no cargo, per the rules).
