# Batch d8z3b — evolutionary-refactoring audit (Audit mode; nothing changed)

Lens: greenfield. Only the raw/source data in R2 (bodies, receipts, provenance) must survive; everything derived can be rebuilt. Scope: hotspots from d8z3b-verdicts.md and d8z3b-greenfield.md, plus the callers, callees and tests needed to follow their invariants. This is not a repository-wide audit.

Baseline, run through the project venv at c858a5a2 (`.venv/bin/python -m pytest -q -p no:cacheprovider …`):
- Earlier passes: 252 passed + 2 subtests on the publication, guard and catalog suites; 5 passed on test_measure_publication_fixture.
- This pass: test_filename_native_recoveries, test_r2_archive_store, test_r2_body_files and test_workflow_resume gave **81 passed, 1 failed**. The failure is pre-existing on main: `scripts/publication/tests/test_workflow_resume.py::test_workflow_fixture_paths_belong_to_selected_current_or_historical_checkout[True]`. The test expects resumed historical checkouts to run `tests/<name>`; the workflow now lists only current paths (`.github/tests/...`). So the explicit-resume-into-an-older-revision feature is already broken, and its own characterization test is red.
- No JS tests were run.

---

## H1 (rank 1, raw) — Raw write policy is cloned across five entry points and selected by a boolean

**Contract.** Raw objects (`bodies/`, `receipts/`, `quarantine/`) are write-once. A new raw write must either create the exact bytes or fail. It must never replace existing bytes. Selectors (`indexes/*.json`) are CAS-replaced. Derived immutables are create-only.

**Current model.** Every adapter re-derives policy from key-prefix strings plus an `immutable=False` default:

| Entry point | Location | Behavior |
|---|---|---|
| `R2Store.put` | r2.py:338-397 | Three prefix-dependent outcomes: unconditional write when `immutable=False` outside `indexes/` (372-383); CAS for `indexes/`; IfNoneMatch otherwise. On 412, accepted as success for `bodies/` (386-387). |
| `R2Store.put_file` | r2.py:408-444 | On 412, returns False (438-440). |
| `R2Store.put_pdf_body` | r2.py:402-406 | — |
| `AsyncBodies.put` | r2.py:150-161 | On 412, returns False (157-158). |
| `LocalStore.put` | catalog_cache.py:84-110 | `os.replace` unless immutable. |

Prefix rules are also restated in client.py:62-64 and 128-131, derived_files.py:18, index_selector.py:4-8, and roughly 8 more prefix tests inside r2.py.

**Pressure.**
- Cloned workflows: one policy, five copies, with no single owner.
- Boolean accumulation: `immutable` means different things depending on the prefix.
- Success-shaped fallback: a 412 on a body is reported as "already retained" without checking the existing bytes.

No production path writes raw keys with `immutable=False` today; every raw writer passes `True`. The harm is latent. One forgotten flag, or a new adapter, silently overwrites raw data.

**Cheapest safe intervention.** Preparatory refactoring with one policy owner.
- **First move:** add a single namespace-policy function (key → `create_only` | `cas_selector` | `mutable_status`) that every adapter consults. Raw prefixes map to `create_only`, so `immutable=False` on a raw key raises before any I/O.
- This changes behavior only for calls that do not exist today, so it is low-risk.
- **Second, separate and explicit behavior change:** on a 412 for a raw key, verify the existing object (size, plus the stored sha256 metadata or the ETag-MD5) before returning "already retained".

**Behavioral evidence.**
- Existing tests that characterize the current fallback, and must be updated deliberately when step two lands (not silently regenerated):
  - test_r2_archive_store.py:84-105 (412 → False)
  - test_r2_body_files.py:50-63
  - test_async_capture_native.py:261
- Local immutability is characterized by test_catalog_files.py:95 and 214.
- Missing: one parametrized test over {put, put_file, put_pdf_body, AsyncBodies.put, LocalStore.put} × {bodies/, receipts/, quarantine/} asserting that a non-create-only write is refused and that no unconditional `put_object` is issued.

**Change to earlier call.** Severity rises. Greenfield listed this as R2, medium-low; the skill's framing (a cloned policy plus a boolean) makes it the cheapest, highest-value move that protects raw data. The earlier "refuse non-immutable raw writes" recommendation is confirmed, now with a named owner and an ordering.

---

## H2 (rank 2, raw) — An application allowlist stands in for an IAM boundary (shared bucket and credential)

**Contract.** Derived publishers must not be able to modify raw data.

**Current model.**
- One bucket holds both (constants.py:3), and the viewer workflow gives preflight, prepare and publish a write-all credential.
- Isolation is handwritten: client.py:128-135 (allowlist plus required condition), publish_viewer_r2.py:244-246 and :501 (PREFIX checks), publication_preflight.py:36-49 (GET allowlist).
- The preflight even hand-signs SigV4 (83-128) with that write credential.

**Pressure.** Handwritten infrastructure replacing established behavior. A platform primitive (separate buckets with bucket-scoped tokens, plus a read-only token for the preflight) provides the boundary that code currently simulates.

**Cheapest safe intervention.** Bounded replacement. This crosses deployment and storage boundaries, so it is a staged redesign that needs the owner's agreement.
- **First move:** create a derived bucket and repoint the derived prefixes. Raw stays where it is, so no raw data migration is involved.
- Until then, keep the allowlist. It is the only barrier.

**Behavioral evidence.**
- test_guarded_recovery_publication_client.py:43-50 (raw and unconditional writes blocked) characterizes the barrier. Keep it until the split lands.
- Missing: a workflow test asserting that the publish job's credential secret names differ from the capture job's (a cheap guard against re-merging them).

**Change to earlier call.** None. This confirms greenfield R1, reframed as a platform primitive and kept as rank 2 because it needs agreement, unlike H1.

---

## H3 (rank 3) — Viewer publication pipeline: compatibility sediment, parallel deciders, and a stale hand-maintained identity

**Contract (greenfield).** Rebuild derived viewer output from the selected catalog and publish it under a new immutable prefix. Verify it, then CAS one pointer. Never write raw keys. Nothing else is required, including resuming old attempts and historical formats.

**Current model.** About 3.3k lines: attempt.py 346, continuation.py 492, client.py 391, verify.py 384, publish_viewer_r2.py 612, publication_preflight.py 402, publication_cli.py 219, local.py 161, release_identity.py 107, plan, resume, reconciliation, prepare_workflow_resume.

**Pressure.**
- **Compatibility sediment.**
  - 13 `version == 6` / non-native branches remain in publish_viewer_r2.py, although attempt.py:74 refuses non-v2 catalogs. The v1 `index_recoveries` fallbacks are at publish_viewer_r2.py:302-305, 341-343 and 355-356.
  - Explicit resume into historical checkouts is already broken: see the red test above.
- **Parallel implementations.**
  - Two "unchanged" deciders: publication_preflight.py:208-330 (stdlib) and attempt.py:64-73 → check_selected_publication (publish_viewer_r2.py:577+).
  - Two identity entry points: the scripts/viewer_release_identity.py shim and the package module.
- **Structural erosion.**
  - release_identity.py:36-58 is a hand-maintained file list. It went stale after the package move (ac7e09a9): 14 loaded modules are missing, including the builder and the publisher (d8z3b-closure.py).
- **Handwritten infrastructure.** The SigV4 signer, the continuation journal and original-condition replay (client.py:244+).

**Cheapest safe intervention.**
- **First move, local and safe:** fix the identity's representation, not its list. Hash the whole package directory (`packages/viewer_publication/src/viewer_publication/*.py`), `docspec_client`, and the engine pin instead of named files. This is one representation change that closes the regression today, regardless of the larger redesign.
- **Next:** delete the unreachable non-native branches. This is compatibility sediment, pinned only by tests of v1 behavior.
- **Then, staged with agreement:** delete explicit resume and the continuation and replay machinery, and replace the 30-minute schedule and preflight with event triggers (raw-capture completion, code push, and the local recovery dispatcher invoking `gh workflow run`). The identity and preflight then disappear with them.

**Behavioral evidence.**
- Characterizing: test_viewer_publication_attempt.py (pointer CAS, no second index scan, refuses changed mappings), .github/tests/test_viewer_r2.py, test_guarded_recovery_publication_client.py.
- **Self-referential, fix first:** test_workflow_resume.py:147-152 asserts that two named files are in the identity. It cannot detect omissions. Replace it with a closure test: import the publisher entry points and assert every loaded repo module is covered (the d8z3b-closure.py logic).
- **Delete with the feature, do not fix:** test_workflow_resume.py:124-144 (historical-checkout resume, currently red).
- **Documentation-only:** test_publication_control_reads.py:66-85 asserts that the cross-object gap exists. Keep it while the pipeline exists.

**Change to earlier call.** Revised.
- Greenfield said "delete release-identity hashing". The skill favors the cheapest safe correction first, so the order is now: glob the package now (it fixes ct-o24q in one move), and delete the identity only when the preflight and schedule go.
- The "simplify radically" direction stands but is now explicitly a staged redesign, sequenced v1 deletion → resume deletion → trigger change.

---

## H4 (rank 4) — Two recovery-index implementations; the native one is cross-checked only against the legacy one

**Contract.**
- Recovery status links accepted and derived saved copies to documents.
- Precedence: accepted over saved-original; ambiguity refuses; invalid or self resolutions are conflict evidence.
- Output must stay within 32 MiB.

**Current model.**
- filename_alias_index.py (SQLite AliasIndex) plus filename_recoveries.index_recoveries (v1) are reachable only from the dead v1 publisher branches, from catalog_aliases (test-only), and from the benchmark server.
- filename_native_recoveries.py re-implements the same rules with its own SQLite spill.
- Both import content_kind, valid_body, resolution_candidates, saved_response and allowed_url (filename_alias_index.py:8-12; filename_native_recoveries.py:8-13).

**Pressure.** Parallel implementations / compatibility sediment.

**Cheapest safe intervention.** Delete v1, but in this order.
- **First move:** test_filename_native_recoveries.py:58-72 builds its expected results by calling v1 `index_recoveries` as an oracle (a differential test). Deleting v1 first would remove the only cross-check of native rule semantics.
- So first freeze the oracle's outputs for the parametrized cases (test_filename_native_recoveries.py:75+) into explicit, contract-derived expectations.
- Then delete AliasIndex, catalog_aliases and v1 index_recoveries together with H3's v1 branches.

**Behavioral evidence.**
- test_filename_native_recoveries.py (passes; oracle-based)
- test_filename_recoveries.py (v1-only; delete with v1, except the accepted_rows/body-key tests at :224-228, which belong to H6)

**Change to earlier call.** The delete call is confirmed, with a new ordering constraint: convert the oracle test first.

---

## H5 (rank 5, raw-adjacent) — Recovery provenance has two authorities

**Contract.** The original → recovered → body association is provenance and must survive.

**Current model.**
- Import receipts (raw) carry `source_associations` (prepare_corpus_recovery_source_records.py:178).
- A separate mutable `viewer-publications/recoveries/accepted.json` is CAS-replaced (corpus_recovery/mappings.py:14, 76-78). It has no R2 history, and only local before/after copies (mappings.py:69-70), which are already pruned.
- Merge can only append (mappings.py:30-32), and writes are fully read back.

**Pressure.** Exhausted representation / dual authority. A mutable document under a derived prefix shadows raw receipts.

**Cheapest safe intervention.** Leave the code alone until the duplication is proven.
- **First move:** a read-only differential. Rebuild accepted rows from the import receipts and compare them byte-for-byte with live `accepted.json`.
- If they match, derive the mapping from receipts and retire the mutable copy. If not, the missing fields are provenance that receipts lack, and they should be added to the receipts. Do not delete anything until then.

**Behavioral evidence.**
- mappings merge tests in packages/corpus_recovery/tests (not run in this pass)
- test_filename_recoveries.py:224-228 (wrong-shard refusal)
- Missing: the receipts-vs-mapping differential above. This is a hypothesis, not a confirmed issue.

**Change to earlier call.** Greenfield R4 ("derive from receipts or make it append-only") is softened to "prove equivalence first".

---

## Leave alone (sound in the inspected scope)

- **corpus_recovery/guards.py (ct-jl1m).** Raw-import guard: pins rehashed under unchanged custody, freshness windows, CAS acknowledged as the real authority. Behavioral tests at test_recovery_guards.py:22-110. Confirmed keep.
- **Body-key validation (ct-qspb).** body_keys.py:11-18, reused by accepted_rows. Confirmed keep.
- **client.py dual-failure diagnostics (ct-pd8n).** Small and correct. Keep while the guarded client exists.
- **Review-asset staging (ct-vp92), filename_reviews.py:108-157.** Greenfield said "simplify". The skill says that is speculative benefit on sound, small code. **Revised: leave alone**, and delete it only if the review pipeline itself is replaced.
- **Browser v6 reader (ct-lvvr, ct-p6aq, ct-zika, ct-qyey, ct-rckw, ct-l3s4, ct-p6ns).** There are real clones: an export-pin search with unbounded `matched` (catalog-v6.ts:290-320) versus the bounded main search (540-579), and two occurrence readers wired hybrid at 434-460. But nobody uses the site, and the fix crosses the publisher's format contract. **Revised from "freeze and simplify" to leave alone.** Collapse to one reader only when the publisher picks one occurrence format. ct-p6aq's severity drops further.
- **Measurement runner (ct-sv16).** measure_publication_control.py:48-58 imports test-module fixtures (indirection without responsibility). Delete when next touched. Not worth a move now.

## Next-change question (grounded)

"Where would a new raw source family be written?" Today that means at least five adapters (r2.py:150, 338, 402, 408; catalog_cache.py:84), each re-deciding immutability by prefix string. After H1's first move, it is one policy entry. That is the clearest change-amplification point in this batch, and it is the one that protects raw data.
