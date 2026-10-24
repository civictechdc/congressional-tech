# mi03b — evolutionary-refactoring audit (Audit mode; nothing changed)

Lens: greenfield. Only the raw/source data in R2 must survive: bodies, capture state/provenance rows, receipts. Everything derived can be rebuilt.

Coverage: the hotspots from my two earlier passes, plus the code they touch. Checks in this pass were greps and reads only; no new tests were run. Earlier evidence still stands: 20 targeted tests pass, and my two probes failed (P1, P2) as documented in `mi03b-verdicts.md`.

Ranked by raw-data and contract risk first, then by how much each change multiplies future edits.

---

## H1. Runtime identity of the raw writer (ct-oxg6, ct-ugqq, ct-x0nk) — top

**Contract (greenfield).** Any process that writes raw capture state to `congressional-tech-raw` runs exactly the pinned engine revision and digest, and refuses before touching R2 otherwise. Nothing else about the runtime matters yet.

**Current model.** Several authorities answer "which binary":
- `QUALIFIED_DOCSPEC_RUNTIME` (`docspec_client/models.py:16-25`) is the app pin, but nothing on the hosted path compares against it.
- `setup-native-runtime.py:126` verifies the artifact against its *own* descriptor (`expected_source_revision=artifact['source_revision']`).
- `resolve_docspec_binary` (`binary.py:7-46`) searches env, then `target/release|debug` in several roots, then `PATH`.
- `NativeDatasets.__init__` silently falls back to `Path(binary).resolve()` when resolution fails (`client.py:105-110`).
- news_lake has its own resolver (`news_lake/storage/docspec/client.py:35-36,56`, env or `shutil.which`).
- Pins are optional. They are enforced only when present (`client.py:312-320,337`).

**Design pressure.**
- *Parallel implementations*: three resolvers and two pin sources.
- *Success-shaped fallbacks*: silent path fallback; dev-build and PATH search.
- A *self-referential verification*: the descriptor is checked against itself.
- This is the "digest supplied by the thing being checked" failure, on a production raw-writing path (`capture-raw-sources.yml:271-278,441-455`).

**Cheapest safe intervention: change the source of truth, don't add checks.**
- **First move:** setup must compare the descriptor's `source_revision` and `sha256` to the single app constant, and fail before any R2 access.
- Then collapse to one resolver that accepts only an explicit binary with a matching digest outside tests. Delete the search ladder (`binary.py:20-43`), the silent fallback (`client.py:107-110`) and the news_lake resolver.

**Behavioral evidence before moving.**
- *Existing:* descriptor-shape refusals (`test_native_features.py:580-620`, 8 cases); credential refusals (`:614`); `verify_runtime` digest test (`test_docspec_runtime.py`, about lines 290-320).
- *Missing:* a test that setup refuses a well-formed descriptor whose revision or digest differs from the pinned constant; a test that `NativeDatasets` with no binary refuses rather than searching.
- *Self-referential:* the descriptor tests cannot see staleness. Extend them; don't delete them.
- Test conftests rely on the search (`news_lake/tests/conftest.py:14-16` sets `DOCSPEC_BINARY` from `target/release`). Keep test-only resolution in the test layer.

**Revision.** Confirms H1 as the top risk. Adds a deletion I hadn't called for: the news_lake resolver is a parallel implementation, so remove it (or delete it with H4).

---

## H2. Producer-custody submission in `docspec_client` (ct-m9td, ct-q968, ct-xq1y) plus raw-state fallbacks

**Contract.** For raw-state writes (`raw_storage.py:1066-1075` `run_table`; `:1217` `update_table`):
- persist `request.json` and producer files before dispatch;
- keep them on an unknown outcome;
- clean up only on a definitive refusal;
- never alter the request's meaning on retry.

Engine-side `deny_unknown_fields` (all listed specs, `model/operations.rs:46-255`) is part of this contract: a refused field must stay refused.

**Current model.**
- *Cloned workflow.* `run_table` (`client.py:445-578`), `update_table` (`:619-797`) and `update_evidence_table` (`:842-915`) each reimplement the same sequence: mkdtemp → write Parquet → hash → `request.json` → retry loop → retain or rmtree.
- *Custody-free twins.* `run_ipc` and `update_ipc` (`:465,589,668`) skip custody entirely.
- *Fallbacks inside the loop:*
  - `'unknown field' in msg and 'partition_by' in msg` → strip the field and resubmit (`:516-521`). This re-creates the silent field-drop that ct-xq1y removed in the engine.
  - `operation_conflict` → rewrite the producer with legacy row-group sizing and a new digest (`:522-533`). This is compatibility for resuming pre-`79911af5` attempts.
  - Substring "transient" matching (`:534-549`).
- *Boolean accumulation:* `stream_ipc`, `native_types`, `row_group_size`, `partition_by`.
- *Raw-path sediment* in `raw_storage.py`: `except TypeError` retries without `partition_by` (`:1065-1069`) and **without `merge`** (`:1226-1233`). Dropping merge silently changes LATEST_OR_BACKFILL into plain key replacement on provenance rows.

**Design pressure.**
- *Compatibility sediment* (the legacy rewrite has no greenfield consumer).
- *Success-shaped fallbacks* (the field strip and the TypeError retries change meaning in order to succeed).
- *Cloned workflow* (one custody policy, three copies; the IPC twins violate it).

**Cheapest safe intervention.**
- **First move: delete the meaning-changing fallbacks.** That is the `partition_by` strip, the legacy row-group rewrite, and both `raw_storage` `TypeError` retries. Greenfield has no old attempts to resume, and the current client accepts every kwarg involved. Pure deletion, no new structure.
- Second move: extract one "submit with custody" skeleton used by all three methods. Ordering and failure rules already agree across them.
- Third: either give IPC the same custody or forbid it for raw writers. Today only news uses IPC (`lake.py:68,424`).

**Behavioral evidence before moving.**
- *Existing:*
  - `test_docspec_input_custody.py`: 25 tests, including the `operation_conflict` refusal at `:98`.
  - `test_docspec_runtime.py:322,360`: update retains replacements and deletions on an unknown outcome; cleans up on refusal.
  - `test_raw_storage.py:33` and `test_catalog_chunk_preparation.py:96`: `operation_conflict` surfaces as a failure.
  - `test_wave2c_bwac.py:192,260`: merge-spec construction.
- *Missing:*
  - No test exercises the `partition_by` strip or the legacy rewrite. Deleting them changes untested behavior, so add a refusal test first: an unknown field must surface as a failure.
  - No custody test for `update_evidence_table`.
  - No test that a schema-evolved raw-state update actually sends `merge`.
  - No test that IPC refuses, or keeps custody, for raw callers.
- *Self-referential:* none here. These tests drive the real request and failure boundary through stubs of `_request`, which is acceptable.

**Revision.**
- Confirms "keep custody". Changes the **order**: delete the fallbacks *before* any consolidation, because they are where meaning changes.
- Promotes the raw-state `merge` TypeError fallback from a footnote to part of this hotspot. It sits on the raw path.

---

## H3. Python retention planner and maintenance callers (ct-qdkd/ct-a70m, ct-lcbc, ct-gfv8, ct-wmtx)

**Contract (greenfield).** Operators need visibility: retained producer inputs, incomplete operations, capacity. Nothing derived needs reclaiming yet. Raw objects must never be removal candidates.

**Current model.**
- `plan_protected_retention` (`native_capacity.py:430-575`) labels every candidate "reclaimable" unless a caller-supplied pin, engine status or substring match protects it (`:522-541`). Substring matching (`any(pin_id in path …)`, `:533,556`) is fragile.
- With `removal_id` it asks the engine for a removal plan (`:543-557`).
- The engine already owns retention: `inspect_retention`, `plan_removal`, `remove_objects` (`retention/removal.rs:433`). It reports objects it doesn't know as "unmatched".
- The only consumer is `raw_sync --mode retention-plan`, which passes neither objects nor `removal_id` (`raw_sync.py:431-439`). So today the reclaim branch is unused.
- The test `test_native_capacity.py:~314-333` *asserts* that an unknown `orphan-01.parquet` is reclaimable, encoding the unsafe default as the spec.
- Engine lifecycle compaction is sound and well characterized (`retention/tests.rs:451,635,688`). Its one automatic caller is news_lake (`lake.py:222-235,574`), which made old releases unreadable (probe P1).

**Design pressure.**
- *Handwritten infrastructure duplicating an established authority*: a Python re-derivation of engine retention.
- *Wrong representation*: "reclaimable" is the complement of the caller's knowledge, so it cannot express "not owned by the engine".
- The auto-compaction caller is a *success-shaped* maintenance side effect.

**Cheapest safe intervention.**
- **First move:** delete the reclaim classification and the `removal_id` branch from the planner. Keep only the protection inventory that `inspect_operator_status` needs, or fold it there.
- Leave the engine compaction and removal code alone. It is sound and has no app caller.
- Delete news_lake auto-compaction with H4.
- Leave the gfv8 route alone: a thin, correct delegation.
- Bucket isolation (move the derived catalog out of the raw bucket) is a deployment boundary, so it is a *staged* change that needs agreement, not cleanup.

**Behavioral evidence before moving.**
- The planner test at `test_native_capacity.py:257` must be rewritten first. It currently characterizes the hazard; under the new contract an unknown object must never be reclaimable.
- `inspect_operator_status` coverage (`:148`) stays as is.
- Engine tests stay as they are.

**Revision.** Changes my earlier call from "make the planner protect by default *or* delete it" to **delete the reclaim branch**: it duplicates the engine's authority and has no consumer. Severity moves **above** news_lake, because the latent hazard sits on the raw-bucket operator path.

---

## H4. news_lake dual backend (ct-jo8n, ct-n6lj, ct-nloa, ct-qkvr, ct-mpsp app side, ct-vt7i receipt)

**Contract (greenfield).** None live. Nothing reads it, and there is no provider wiring. The only future obligation: if news capture goes live, raw captures need immutable receipts and unique ids.

**Current model.**
- Two complete backends coexist: pyiceberg `Lake` (`storage/catalog.py`, exported at `storage/__init__.py:7`) and `DocSpecLake` (`storage/docspec/*`, about 4,265 LOC, plus a test file of about 2,500 lines).
- Duck-typed dispatch chooses between them: `releases.py:185-187,293,314`; `coordinator.py:281`.
- Views exist twice, as Python oracle and DocSpec views (`cli.py:113-123` `--verify-oracle`).
- Inside the DocSpec path there are two selection authorities: `.news_lake_committed.json` and native-latest fallbacks (`lake.py:371,429,588,815`; `incremental.py:918`).
- In-process caches act as correctness inputs: `_known_ids` (`lake.py:88,329`, which caused probe P2) and `_known_upsert_records`.
- Automatic compaction runs as a side effect of commits (P1).

**Design pressure.**
- *Compatibility sediment and parallel implementations* (two backends, hasattr dispatch).
- *Structural erosion* (scale tickets kept adding branches to `lake.py` / `incremental.py`).
- An *exhausted representation* (uniqueness simulated with an in-memory set).

**Cheapest safe intervention.**
- **First move:** collapse to one backend. Delete the DocSpec adapter (`storage/docspec/*`, the `docspec_backend.py` shim, the DocSpec CLI branches) and the `hasattr` dispatch. Keep the Python owner and oracle views as the contract.
- If DocSpec adoption for news is wanted later, rebuild a thin adapter against that oracle, starting with durable id uniqueness and raw-capture custody.
- Freezing the whole package is the acceptable alternative.

**Behavioral evidence before moving.**
- *Keep as the spec:* the oracle parity assertions (for example `test_docspec_backend.py:1062-1146`, `pa == politician_articles_views(read)`), and the Python-owner suites (`test_releases.py`, `test_coordinator_replay.py`, `test_analysis_views.py`).
- *Delete or fix first (self-referential):*
  - `:2070-2100` asserts a static receipt file;
  - `:738-753` tests the test-local `_ArrowHttpStream`;
  - `:1463-1468` uses an ordering that hides P2.
- *Missing:* none needed for deletion. Characterization of the Python owner already exists.

**Revision.** Confirms deletion and sharpens it: delete the **DocSpec adapter and the dispatch**, not "the news stack". The Python owner is the simpler surviving authority, and the earlier "delete or freeze" wording was ambiguous about which half to keep. Severity moves below H3 (pilot only).

---

## H5. Leave alone (sound, or not worth moving)

- **Engine `BackendCapability`** (`engine.rs:211-231,370-392`): one owner, two variants, used consistently. No change.
- **Engine `deny_unknown_fields`** (`c0de1bd`): sound. The only defect lives in the client (H2).
- **Engine lifecycle compaction, Update pruning, Month partitions** (ct-lcbc, ct-xl0y, ct-mpsp engine side): sound and characterized. The earlier "stop perf work" call becomes **don't extend; don't revert**. The fix belongs at the callers (H3/H4).
- **ct-n7la capacity admission** (`native_capacity.py:30-137`, wired at `catalog_adoption.py:241-264`): sound. Leave it.
- **ct-wjce `chunk(0)`** (`catalog_rows.py:39`): tiny and correct; buffer-identity test present. Leave it.
- **ct-tcfg**: leave the code. The one useful move is a bare `cargo test --no-run` line in `scripts/check`. Not run here.
- **ct-vt7i hot-group test**: the code is fine, but the test claims more than it shows. Rename or reword the claim rather than add machinery. Low priority.
- **ct-sb0s receipt helpers**: opt-in, derived. Delete only if H4-style cleanup reaches `congress_api` review tooling. Otherwise leave them inert. This is a softer call than my greenfield pass, because the helpers carry no live risk and deleting them is not the cheapest safe move.

---

## Changes to earlier calls

| Earlier call | Now | Why (skill framing) |
|---|---|---|
| Planner: "protect by default or delete" | **Delete the reclaim branch**; keep the inventory | It duplicates the engine's retention authority; no consumer; its test encodes the hazard. |
| news_lake: "delete or freeze the DocSpec stack" | **Collapse to one backend**: delete the DocSpec adapter and `hasattr` dispatch, keep the Python oracle owner | Two authorities make the dispatch the problem. Keep the simpler owner as the spec. |
| Custody: "keep; ban streaming; delete fallbacks" | Same, **ordered**: delete the meaning-changing fallbacks (client strip, legacy rewrite, raw `merge` TypeError) first; then one custody skeleton; then the IPC decision | The fallbacks are where semantics change; consolidating first would preserve them. |
| Runtime: "one constant; delete search paths" | Same, plus **delete the news_lake resolver** | Parallel implementation. |
| Engine perf: "stop" | **Leave the existing engine code alone; don't extend** | Sound, characterized code; reverting it has no benefit. |
| sb0s: "delete" | **Leave inert unless already cleaning that area** | No live risk; deletion is not the cheapest safe move. |
| Ranking | H1 > H2 > H3 > H4 (H3 now above news_lake) | The latent hazard is on the raw-bucket operator path. |
