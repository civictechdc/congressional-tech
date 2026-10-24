# d8z3a evolutionary-refactoring audit (Audit mode, greenfield lens)

**Scope.** I reviewed the hotspots that `d8z3a-verdicts.md` and `d8z3a-greenfield.md` found in epic ct-d8z3, on `main` c858a5a2. I read code and tests and changed nothing. The greenfield rule still holds: only raw/source data in `congressional-tech-raw` (captured bodies, receipts, provenance) must survive, and everything derived can be rebuilt.

**Baseline evidence from earlier passes**, all run with `.venv/bin/python -m pytest … -p no:cacheprovider`:
- 137 catalog and preparation tests passed (fork C).
- 116 continuation, CLI, control-read and verification tests passed, and 42 attempt tests passed (fork B).
- 9 admission tests and 5 budget tests passed.
- `scripts/publication/tests/test_workflow_resume.py`: 1 failed, 20 passed. **This was already failing before any change.**

No checks were run for this pass beyond reading code.

---

## H1. Two publication authorities, plus a hand-rolled journal and resume layer (ct-1dsp, ct-1mbc, ct-atjy, ct-idhg, ct-hm4b)

### Contract and current model

What this code is for now: publish a *derived* viewer release that readers see either completely or not at all.

The only behaviour that must be kept for raw data is the **raw firewall**. Publication writes are restricted to derived key prefixes and must carry an explicit `IfMatch` or `IfNoneMatch` condition (`viewer_publication/client.py:128-134`). Viewer publication and corpus recovery publication both use it (`dispatch_corpus_recovery_publication.py:396`).

What can be dropped under greenfield:
- resuming a publication attempt
- describing an attempt
- re-running a historical attempt
- reconciling uncertain writes
- the per-PUT full readback

A rebuild and republish replaces all of these.

There are two authorities in the current model.
- **v6 release route (wired).** `attempt.py` (346 lines), `continuation.py` (492), `resume.py` (50), `local.py` (161), `reconciliation.py` (84) and `prepare_workflow_resume.py` (40), driven by `publish-filename-viewer.yml`.
  - The workflow has 14 `if:` conditions spread across three axes: push event, resume, and preflight status (`:89-172`).
- **ExportPin route (unwired; manual `export-pins --publish-to-r2`).** This is the CLI at `publication_cli.py:45,155-159` writing through `ConditionalManifestPublisher` (`client.py:310-391`).
  - The browser reader has a matching second mode, chosen by manifest shape (`catalog-v6.ts:148,150,160,214-219`).
  - That mode is missing the `technical`, `review` and `matchUrls` routes (`:380-390`), so `worker.ts:34-37` would throw.
  - ct-te1p planned this as the successor that would let `continuation.py` retire. No removal condition was recorded, and both routes are still live.

### Design pressure

- **Parallel implementations / compatibility sediment.** There are two write authorities and two reader modes, with no owner and no removal condition.
- **Handwritten infrastructure replacing established behaviour.** A write-ahead journal re-implements what immutable keys plus one conditional pointer swap already provide. docspec-rs `Objects::Remote` already provides create-only writes and lifecycle.
- **Branch accretion / multi-axis dispatch** in the workflow: event × resume × preflight.
- **Success-shaped fallback.** `ConditionalManifestPublisher` treats a 412 as success and returns the *local* digest as if verified (`client.py:344-349`).
- **Defensive sediment.** Process-local receipt registries (`client.py:57` `_receipts`, `continuation.py:131` `_reconciled`), and every event rewrites and fsyncs the full state (`continuation.py:143-154,217-223`).

### Cheapest safe intervention

1. **First move (safe whichever writer survives): delete the resume axis.**
   - Remove the `resume_descriptor` input and the resume steps in the workflow, `prepare_workflow_resume.py`, `resume.py`, `describe-attempt` and `--resume-descriptor` (`publication_cli.py:53-83`), and `scripts/publication/tests/test_workflow_resume.py`.
   - This removes one of the three workflow axes, plus the failing test.
2. **Then a staged redesign that needs the owner's agreement**, because it crosses the storage format and the browser contract: choose one authority.
   - The evidence favours the ExportPin / docspec-rs direction (ct-te1p, ct-2yl5) *only if* reader parity is either built or explicitly dropped.
   - Otherwise delete the ExportPin route end to end: `publication_cli export-pins --publish-to-r2`, `ConditionalManifestPublisher`, and the `catalog-v6.ts` ExportPin branch.
3. **Whichever survives:**
   - Keep `client.py:128-134` as the **single** owner of key policy. Route every writer through it.
   - Replace the journal with: write immutable release objects (`IfNoneMatch`), compare bytes on a 412, then swap the pointer once (`IfMatch`).

### Evidence needed before moving code

**Tests that characterize behaviour to keep:**
- `test_recovery_viewer_transfers.py:141-146`: refuses `indexes/raw.json`; immutable rewrite refused.
- `test_guarded_recovery_publication_client.py`: conditional writes.
- `test_filename_exports.py:352-370`: streamed immutable assets.

**Tests that are missing:**
- Every writer refuses `bodies/sha256/...` and `indexes/raw.json`. Today only the guarded client is tested, and only with `raw.json`.
- A 412 on an immutable asset with *different* bytes must fail.
- A pointer swap that loses the `IfMatch` race leaves the old pointer in place.

**Tests that are self-referential or coupled to the mechanism (delete with the mechanism; don't port):**
- `test_checkpoint_costs.py:12-25` counts `flush` calls.
- `test_viewer_publication_attempt.py:486-500` counts `file_identity` calls.
- `test_workflow_resume.py` asserts workflow text and paths.

Roughly 1,930 lines of tests are tied to journal, resume and attempt internals.

### Effect on earlier recommendations

- **Confirms** "SIMPLIFY radically".
- **Revises the order:** delete the resume axis first, then get a decision on one authority, then replace the journal.
- **New:** the ExportPin reader branch is part of the parallel-path problem.
- **Severity:** this becomes the #1 hotspot by change amplification. Raw risk is unchanged at none, because the firewall holds on every wired path.

---

## H2. Process-local proof registries and the `VerifiedFile` multi-mode constructor (ct-fw0m, ct-1dsp, ct-3djs)

### Contract and current model

The real contract: "this local file has SHA X and size Y right now," known before a file is trusted or uploaded.

- **Must keep:** `file_identity` hashing semantics. A raw writer relies on them (`raw_readings_adoption.py:35,62`).
- **Current model:**
  - `VerifiedFile` accepts either a Mapping or `(path, sha, size)`, plus optional `pid`, `target` and `identity` arguments.
  - The positional form issues process custody without hashing (`congress_shared/custody.py:66-83,99-100`).
  - `require()` compares only the values the caller supplied (`:114-124`).
- **Registries:** `VerifiedFile._issued` (`custody.py:40`), the `InventoryValidation` registry keyed on code-object ids (`viewer_inventory.py:13,28-30`), and `CatalogPairValidation` (`catalog_validation.py:140-292`).
- **Production positional callers:** derived catalog preparation only (`catalog_dependency_preparation.py:208,370`). Both are gated off when `PYTEST_CURRENT_TEST` is set (`:200,:363`).

### Design pressure

- **Wrong abstraction / boolean accumulation.** One type with several construction modes and optional custody fields.
- **Success-shaped proof.** A proof is issued without the check it certifies.
- **Defensive sediment.** Proof objects carried through every layer to skip re-hashing that costs seconds.
- **A test-mode branch** hides restore behaviour from tests.

### Cheapest safe intervention

**First move:** issue custody only from the hashing factory.
1. The positional constructor either hashes or issues nothing (fails closed).
2. Migrate the two callers to `file_identity`.
3. Remove the `PYTEST_CURRENT_TEST` gates so restore paths can be tested.

Later, if wanted, delete the registries and pass digests in memory. That step should be judged against the measured re-hash cost; nobody has measured it yet.

### Evidence needed before moving code

**Existing tests:**
- `test_catalog_files.py:242`: refuses a mapping-form forgery.
- `test_viewer_publication_attempt.py`: refuses `copy()`, dict and mutation.

**Missing:**
- A test that `VerifiedFile(p, wrong_sha, size).require(p)` raises. Write it against the *intended* contract as part of the fix; today it passes, which is the defect.
- A restore-path test once the gate is removed.

**Coupled to the mechanism:** the hash-count test at `test_viewer_publication_attempt.py:486`. Delete it if the registries go.

### Effect on earlier recommendations

- **Confirms** DELETE as the destination, and severity stays low under greenfield.
- **Refines** the first move: narrow issuance and remove the test gate, rather than wholesale deletion, because `file_identity` is on a raw path and must stay.

---

## H3. Recovery-import admission: the only raw-boundary code in this batch (ct-4r1c)

### Contract and current model

Before deriving anything from a recovery import, prove it covers the sealed capture batch: receipt pins, readiness against source records, completion counts, and readback of the raw selector. It is read-only and fails closed (`corpus_recovery/admission.py:98-249`).

### Design pressure

**Representation, mildly exhausted.** The event and evidence records are loosely shaped dicts read with ad-hoc `.get(...).get(...)` chains (`:216-231`). A non-dict `value` escapes as a bare `AttributeError`. Pins are keyed on the unnormalized `str(path)` (`:245`).

### Cheapest safe intervention

**First move:** validate the event shape once, at the parse boundary in `events()` (`:75-95`). For the event kinds it reads, require that `value` is an object, so the loop can work with a known shape. Then normalize the pin keys, which needs the import writer to agree on the key format.

### Evidence needed before moving code

- **Existing:** `test_dispatch_corpus_recovery_publication.py:265-303,440-463`, which pass.
- **Under-specified (must be tightened first):** the 7-case parametrized test asserts only `pytest.raises(ValueError)` (`:286-303`). It cannot tell which check fired, so match the file/field message per case.
- **Missing:** a malformed event `value`, and pins written with a relative versus absolute batch path.

### Effect on earlier recommendations

**Confirms** KEEP and the small fix, and names the fix more precisely as a boundary-shape change rather than a patch at the call site. This stays the highest-value raw-adjacent item.

---

## H4. Cloned bounded readers and cloned origin configuration (ct-hm4b, ct-fcxg)

### Contract

Read control documents within a size limit and never trust a partial read.

### Design pressure

**Cloned workflows.**
- `verify.control` (`verify.py:12-37`) re-implements `bounded_control_read` (`congress_api/retention/control_documents.py:6-28`).
- `constants.LIMITS` (`viewer_publication/constants.py:10`) duplicates `CONTROL_LIMITS`.
- The public origin is configured in two languages and has drifted: `constants.py:6` and `pipeline_status.py:297` point at the retired workers.dev Worker, while the browser uses `publication.ts:2`.
- `publication_preflight.py` keeps its own stdlib-only copy. That one is justified, because it runs before workspace setup.

### Cheapest safe intervention

- **First move:** fix the origin default. This is a correctness bug, not cosmetic.
- Then have `verify.control` call `bounded_control_read` with a new kind, and drop `constants.LIMITS`.

### Evidence needed before moving code

- **Existing:** `test_publication_control_reads.py`, which covers oversized, truncated, appended and malformed responses, and `test_pipeline_status.py`.
- **Missing:** a `verify.control` test for a malformed `Content-Length` header (`int(declared)` is unguarded at `verify.py:23`).

### Effect on earlier recommendations

**Revised.** I earlier said to delete the Chromium/live-loader checks. Instead, **leave `--verify-publication` alone apart from these two moves.** It has no workflow consumer, so it creates no change pressure, and deleting it buys nothing until someone touches it.

---

## H5. Dormant and legacy code (ct-3djs, ct-gubr, ct-eauq, ct-hnxb remnants)

### Contract

None in production.

- `repack_and_verify` (`publish_filename_viewer.py:115-163`) is used only by `scripts/measure/measure_preparation_decoded.py` and tests.
- The `verify(validation=)` branch (`:44-49`) and `accept_catalog_validation` (`catalog_publication.py:179`) have no production caller.
- The test-only v5 generator `historical_viewer_publication.py` is imported by the *src* module `filename_test_fixture.py:43`, so dependencies point the wrong way.
- The retired CLI shim `scripts/publication/publish-filename-viewer.py` raises `SystemExit`. It is still hashed into the release identity (`release_identity.py:41`) and the restart pins (`dispatch_corpus_recovery_publication.py:139,246`), and it is a path trigger in both workflows.
- `validate_catalog_pair` is still used by `corpus_recovery/diagnostics.py`, so it is **not** dead.

### Design pressure

Compatibility sediment, plus indirection without responsibility (the shim).

### Cheapest safe intervention

Delete `repack_and_verify`, the `verify(validation=)` branch with `CatalogPairValidation`, the `accept_catalog_validation` hook, and the shim.

**Caveat:** the shim's removal must come with a deliberate release-identity change in the same commit. That follows the CLAUDE.md rule for sealed identities. Under greenfield it is acceptable, because the identity is derived data.

Keep `validate_catalog_pair` until `diagnostics.py` is either retired or kept on purpose.

### Evidence needed before moving code

- Run the release-identity and restart-pin tests after the identity change.
- Delete or re-target `filename_test_fixture.py`'s dependency on the historical generator.

### Effect on earlier recommendations

- **Confirms** DELETE.
- **Corrects** my earlier list: `validate_catalog_pair` has a live diagnostic caller, and the shim deletion carries an identity obligation.

---

## Leave alone (sound, or no current pressure)

**Decoded-memory budget** (`filename_budget.py`, ArrowStager; ct-hnxb, ct-gubr): **revised from SIMPLIFY to LEAVE ALONE.**
- It is active in native preparation (`filename_native.py:371-422`).
- Its tests pass, including a real-footer case (`test_filename_decoded_budget.py:55`).
- No refusal has been observed on the current path, so replacing it now is speculative.
- **Triggers to revisit:** the next false refusal on real data, or preparation moving into docspec-rs.
- **Known limitation:** `filename_details.py:96-124` only checks that output reads back the same, not that it was derived correctly. Label it as such; don't count it as derivation evidence.

**Browser reader v6** (ct-9at7, ct-15wc, ct-bs70, ct-hfrv): leave the code alone.
- Delete the stale claims in `docs/experiments/publication-remediation/browser.md:42-44`.
- The ExportPin branch is handled under H1.

**Pages setup** (ct-hbxu): **revised from "drop the npm bootstrap" to LEAVE ALONE.**
- It works, and hosted runs passed.
- The only pressure is the duplicated npm pin: root `npm@11.0.0` versus site `npm@11.19.1`. Give it one owner when Pages is next touched.

**Also sound:** ct-gesp (resource cleanup), ct-d2lk (review-byte pin), ct-eauq (fresh-target check, kept in native at `filename_native.py:899-900`), ct-dpks (`publication-budget.py`).

---

## Next-change question

If another derived artifact must be published (for example a second viewer table), where would it be added today?

- **v6 route:** the inventory proof, `attempt.py` phases, the continuation phases, the guarded client allowlist, the workflow steps, and the reader's v6 route.
- **ExportPin route:** the export-pins CLI and the reader's ExportPin branch.

That is two sets of synchronized edits. After H1, it should be one release writer plus one reader route, with `client.py:128-134` unchanged.
