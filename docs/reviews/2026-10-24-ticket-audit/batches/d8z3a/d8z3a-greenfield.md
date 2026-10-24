# d8z3a greenfield addendum

This file adds to `d8z3a-verdicts.md` and does not replace it. The verdicts (whether each ticket landed) are unchanged. What changes is how much each problem matters.

The lens: nothing in this project is used yet. Only the raw source data must survive: the captured bodies and bytes in R2 `congressional-tech-raw`, their receipts and their provenance. Everything derived from them can be rebuilt.

## 1. Risks to raw data

**Result: no ticket in this batch can lose, corrupt, overwrite, delete or expose raw data on any path that runs today.**

Epic ct-d8z3 is almost entirely about *derived* data: the catalog, the viewer publication, the browser and Pages. Its write paths are fenced away from raw keys.

### Raw protections that exist (keep all of these)

**Publication can only write derived keys (ct-1dsp, ct-idhg, ct-atjy, ct-1mbc, ct-4r1c paths)**
- **Where:** `packages/viewer_publication/src/viewer_publication/client.py:128-134`.
- **What it does:** `GuardedPublicationClient.put_object` writes only to an allowlist of key prefixes: `catalog-generations/`, `catalog-history/sha256/`, `indexes/processing/`, `viewer-publications/`, `indexes/native-manifests/` and the exact key `indexes/catalog.json`.
  - Every other key fails with `ValueError('Publication cannot write raw/source object')`.
  - Every write must also carry an explicit `IfMatch` or `IfNoneMatch` condition.
- **Reachable today:** yes. Viewer publication goes through `attempt.py`. Corpus recovery publication goes through `ContinuedPublicationClient` (`scripts/corpus_recovery/dispatch_corpus_recovery_publication.py:396`).
- **Test:** `test_recovery_viewer_transfers.py:141-146` refuses `indexes/raw.json`.
- **Gap:** no test sends a `bodies/` key. The allowlist covers that case anyway.
- **History:** predates the batch (a01f139a, Oct 16), and the batch kept it.

**The second write route stays in its own prefix**
- `export-pins --publish-to-r2` uses `ConditionalManifestPublisher`, which writes only under `viewer-publications/releases/` (`client.py:320`) and the pointer `viewer-publications/manifest.json` (`:383`).
- It treats a 412 as success without comparing bytes (`:344-349`). That can only hide a mismatch in derived data.

**`R2Store.put_derived_file` (ct-fw0m) cannot reach raw objects**
- `require_derived_key` limits it to the two exact catalog table keys (`congress_api/retention/derived_files.py:16-20`).
- It writes with `IfNoneMatch='*'` (`r2.py:558-560`), so it cannot overwrite.

**Recovery-import admission (ct-4r1c) is read-only and fails closed**
- It checks receipts on the raw-import boundary: sealed-batch file pins, readiness against source-record coverage, import completion counts and the readback of the raw selector (`corpus_recovery/admission.py:98-249`).
- Its known defects all fail closed:
  - A non-object event value raises an `AttributeError` (`:218-223`) instead of a named error.
  - Pins are keyed on the unnormalized path (`:245`), so a pin can fail to match. That gives a false refusal, never a false acceptance.

### Raw-adjacent findings (none reaches raw data today)

**Forgeable `VerifiedFile` proofs (ct-fw0m, ct-1dsp, ct-3djs): downgraded from high to low**
- **The flaw:** `custody.py:66-83,99-100` issues a proof without hashing.
- **Where it is used:** the only production positional constructions are in *derived* catalog preparation (`catalog_dependency_preparation.py:208,370`). The skip in `derived_files.py:34` and `r2.py:545-555` covers derived files only.
- **Raw writers are not exposed:**
  - `raw_readings_adoption.py:35,62` uses `file_identity`, which hashes.
  - The body uploads `r2.py:407-444` (`put_file`) and `:338-399` (`put`) check MD5 independently and use `IfNoneMatch`.
- **Why it still matters:** it is a trap. The first raw writer to construct `VerifiedFile(path, sha, size)` would get a free "verified" proof.

**Dormant raw-deletion path, outside this batch (ct-te1p)**
- `raw_storage.migrate_pdf_bodies_to_uncompressed(delete_gzip=True)` deletes the original `.gz` body (`raw_storage.py:314-316,330-331`).
- On the "already present" branch it deletes without checking the `.pdf` bytes it is keeping.
- **Unreachable today:** `R2Store` has no `delete` method, so `hasattr(store,'delete')` is false. No production store defines `delete`.
- **Recommendation:** do not add `R2Store.delete` until that branch re-verifies the `.pdf`. Flag this to whoever owns ct-te1p.

**Lost evidence (provenance of the work, not of the data)**
- The batch's audit and qualification evidence lived in untracked `output/` folders that are now gone: `publication-exam-20261018`, `publication-remediation-20261018` and `decoded-memory-final8-20261018`.
- Raw recovery batch receipts also live under untracked `output/` (for example `output/corpus-retry-20261015/publication-batches/*`).
- If any of those receipts are not also captured in the R2 raw archive tables, they are one cleanup away from being lost.
- **Not verified here.** It belongs to the corpus_recovery preservation owner.

## 2. Re-ranking: earlier problems that drop away

| Earlier finding | Old rank | New status |
|---|---|---|
| ct-fw0m/1dsp/3djs forgeable proof | 1 (high) | Low. Derived data only; fix by deleting the positional issuance (§4). |
| ct-1mbc historical resume broken, guard test fails | 2 | **Irrelevant.** Resuming old attempts of a derived publication nobody uses. Delete the historical test case with the resume machinery. |
| ct-1mbc unguarded `--publish-to-r2` | 2 | Low. Confined to `viewer-publications/releases/`. Its only real problem is being a second write path. |
| ct-9at7 cancellation bound regressed | 3 | Backlog. Viewer UX with no users. |
| ct-idhg journal cost quadratic in writes | 4 | Low as a performance issue; the right move is to delete the write-ahead journal (§4). |
| ct-hnxb no hosted memory qualification for native C5 | 5 | Low. A failed or out-of-memory derived build loses nothing; rerun it. |
| ct-8uwj/ct-d8z3 measured a revision that is not on main | 6 | Irrelevant. |
| ct-fcxg/hm4b defaults point at the retired workers.dev | 7 | Low (live-site default), but it is a one-line fix. |
| ct-15wc/ct-bs70 criteria not carried over | 8 | Irrelevant. |
| ct-hbxu npm pin drift | 9 | Low. Lock files still matter because they keep derived rebuilds reproducible. |
| ct-4r1c bare `AttributeError`, weak test | 10 | **Raised slightly.** This is the only code in the batch on the raw-import provenance boundary; tighten it. |

## 3. Re-grades (only those that change)

The standard: work that protects rebuildable derived data, or keeps resume and compatibility nobody needs, loses points. Work on the raw boundary gains.

| Ticket | Proposal | Work | Reason |
|---|---|---|---|
| ct-d8z3 | C 70 → D 60 | C+ 74 → C 68 | An epic of efficiency and recovery work on derived publication for zero users. Most of it went dormant within 3 days, and none of it targeted raw custody. |
| ct-1dsp | C+ 72 → D 64 | C+ 75 → C 70 | Process-local, forgery-resistant proofs to avoid re-hashing a derived inventory that can be rebuilt. A re-hash costs seconds. |
| ct-fw0m | C 70 → D 64 | unchanged | Custody plumbing for derived catalog files. The later forgery hole cannot reach raw data. |
| ct-3djs | C+ 74 → D+ 68 | unchanged | Proof reuse to skip validating derived catalog files the same process had just written. |
| ct-atjy | C+ 74 → D+ 66 | B+ 87 → B- 80 | Careful hardening of a derived-publication write-ahead journal that should be deleted. The craft is fine; the effort was aimed at the wrong thing. |
| ct-1mbc | B 83 → C- 72 | B- 80 → C+ 76 | A resume descriptor, attempt lookup and original-revision checkout so derived publications can resume. Greenfield answer: rebuild and republish. |
| ct-idhg | B+ 86 → B- 80 | unchanged | Well measured, but it optimizes a journal that should not exist. |
| ct-hnxb | B 83 → C+ 78 | unchanged | Preserving every value is right, but the elaborate admission machinery guards an artifact that can be rebuilt. |
| ct-9at7 | B 84 → C+ 76 | unchanged | Premature optimization of viewer UX. |
| ct-15wc | C+ 76 → D+ 68 | unchanged | Premature and unmeasured, on a UI that was later deleted. |
| ct-bs70 | B- 80 → C- 72 | unchanged | Premature byte-level tuning of the browser with no users. |
| ct-fcxg | B- 78 → C 74 | unchanged | The link from raw run to catalog identity is valuable. The Chromium and live-loader checks are ceremony while there are no users. |
| ct-8uwj | B 80 → C 74 | unchanged | A rigorous comparison of a derived pipeline's speed before anyone used it. |
| ct-4r1c | B- 78 → B- 81 | B 82 → B 84 | Sits on the raw-import provenance boundary (receipt pins, sealed-batch coverage) and fails closed. |

New batch averages: proposal 79.8 → **75.7**, work 80.1 → **79.2**.

Unchanged: ct-gesp, ct-d2lk, ct-hfrv, ct-hbxu, ct-eauq, ct-dpks, ct-gubr, ct-hm4b.

## 4. Going forward: keep, simplify or delete

**Viewer publication write path: SIMPLIFY radically**
- Replace the 492-line `continuation.py` write-ahead journal and `DurableJournal`, the per-PUT full readback, `ContinuedPublicationClient`, `attempt.py` resume/describe-attempt, `resume.py`, `prepare_workflow_resume.py` and the historical-resume test with one writer:
  1. Write immutable release objects under `viewer-publications/releases/<id>/` with `IfNoneMatch='*'`.
  2. Swap the pointer once with `IfMatch`.
  3. On any failure, rebuild and republish from scratch.
- That is `ConditionalManifestPublisher` plus a byte comparison on 412. docspec-rs create-only writes cover the rest.
- **Keep** the prefix allowlist and the explicit-condition rule from `client.py:128-134`. That is the raw firewall.

**Process-local proof registries: DELETE**
- Delete:
  - `VerifiedFile._issued` and its positional issuance (`custody.py:40,66-83,99-100`)
  - `InventoryValidation` code-object registry (`viewer_inventory.py:13,28-30`)
  - `CatalogPairValidation`/`validate_catalog_pair`
  - `GuardedPublicationClient._receipts`
  - `Continuation._reconciled`
- Replace them with plain `file_identity` hashing or passing digests in memory.
- At minimum, make the positional constructor hash, so no future raw writer inherits a forgeable proof.

**Decoded-memory budget (`filename_budget.py`, ArrowStager): SIMPLIFY**
- Rely on native/docspec-rs streaming plus a process memory cap.
- Keep a clear failure message; delete the hand-tuned estimates that refused real data three times.

**Dead and legacy code: DELETE**
- `historical_viewer_publication.py` (test-only v5 generator)
- `repack_and_verify`
- the `verify(validation=)` branch
- the retired `publish-filename-viewer` CLI and its `scripts/` shim
- `docs/experiments/publication-remediation/*`: archive it. It is not load-bearing, and parts are stale (`browser.md:42-44`).

**`pipeline_status --verify-publication`: SIMPLIFY**
- Keep the read-only raw-run → selected catalog/viewer identity link.
- Delete the Chromium and live-loader checks until there are users.
- Fix the workers.dev defaults (`pipeline_status.py:297`, `constants.py:6`).

**Keep**
- Bounded control reads (`control_documents.py`); fold the duplicate reader `verify.control` into it.
- Recovery admission (`admission.py`). Fix the `AttributeError` shapes at `:218-223`, normalize pin paths, and assert error messages in `test_dispatch…py:286-303`.
- Resource cleanup from ct-gesp.
- The review-byte pin from ct-d2lk.
- The worker restart from ct-hfrv.
- `publication-budget.py`.
- The Pages lock files (reproducible rebuilds).

**Simplify in Pages**
- Drop the separate npm bootstrap; use the npm that ships with Node 22.22.2.

**Browser reader (v6): KEEP AS IS**
- No further performance work until there are users. Don't reopen ct-9at7, ct-15wc or ct-bs70.
