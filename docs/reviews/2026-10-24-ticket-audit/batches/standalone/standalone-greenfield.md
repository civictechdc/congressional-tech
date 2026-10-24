# Standalone batch: greenfield addendum

New premise: nothing uses this project yet. Only the raw/source data in R2 bucket `congressional-tech-raw` must be kept: the captured bodies, their receipts and their provenance. Everything derived can be rebuilt. This addendum revises the earlier verdicts file (`standalone-verdicts.md`); that file is unchanged. Checked read-only against main c858a5a2.

## 1. Raw-data risks in this batch

**Context for every risk below: derived output and raw data share one bucket and one set of credentials.**
- Viewer publication writes to `congressional-tech-raw` (`packages/viewer_publication/src/viewer_publication/constants.py:4`, `publish_filename_viewer.py:70`, `scripts/corpus_recovery/dispatch_corpus_recovery_publication.py:350`).
- That bucket is also the public bucket (`packages/congress_api/src/congress_api/retention/r2_edge_rules.py:17`).

| # | Risk | Evidence | Can production reach it today? | Severity |
|---|---|---|---|---|
| R1 | **Code that writes raw data runs unrecorded (ct-esm4).** The import dispatcher's hand-written pin list leaves out `docspec_client`, the real transport behind the `congress_api/retention/docspec.py` shim, and `congress_shared.custody`/`storage`. That code writes the raw native datasets and the raw selector `indexes/raw.json`. So the import's code-provenance record and its runtime check miss it. | `scripts/corpus_recovery/dispatch_corpus_recovery_import.py:107-122`; selector CAS at `packages/corpus_recovery/src/corpus_recovery/transfer.py:94-101`; `RAW_KEY` at `congress_api/retention/raw_storage.py:364` | Yes, on every recovery import run. | Medium: a provenance gap, not data loss |
| R2 | **A derived writer has no raw-prefix guard.** The local recovery publication's catalog phase writes through a plain `R2Store` subclass. `R2Store.put` adds a condition only for `immutable=True` or `indexes/` keys; any other key is overwritten unconditionally. The only real barrier for derived writes is the allowlist in `GuardedPublicationClient`, which the catalog phase does not use. I found no current call that writes a raw key; the risk is structural. | `packages/corpus_recovery/src/corpus_recovery/publication.py:88-104`; `congress_api/retention/r2.py:338-378`; allowlist `viewer_publication/client.py:124-135` | Path reachable on every local recovery publication; no raw-key write found. | Medium |
| R3 | **The accepted recovery mapping may not be rebuildable.** It merges each batch with the current remote copy and preserves "fresh edits/deletions". If any of those edits are not in a retained batch, the file is provenance stored in the derived namespace. Writes are protected by conditional If-Match and bounded reads. | `packages/corpus_recovery/src/corpus_recovery/mappings.py:14`, `:77-79` | Yes, in the mapping phase. | CANNOT-VERIFY: decide whether this file counts as provenance |
| R4 | **Engine pruning now trusts 64–127-byte string bounds (ct-tuez).** Raw captures are keyed by 64-hex sha256 and 74-byte body_key, so Update and read_keys on raw native datasets depend on this pruning being correct. The bounds are used only as intervals (`key_pruning.rs:735-746`), and Parquet's truncated min/max stay valid as interval endpoints. Tests cover both sides. | docspec-rs `src/storage.rs:97,451`; `src/engine/key_pruning.rs:735-746`; `tests/update_pruning.rs:283` | Yes, in raw-source-sync and recovery import. | Low |
| R5 | Adjacent, outside this batch (the ct-2ukk cache work): `R2Store.read` serves `receipts/` and `bodies/sha256/` from a local disk cache when `cache_dir` is set, and raw_sync sets it. Readback "verification" of raw writes in the capture path can then compare against the local cache, not R2. The recovery import does not set `cache_dir` and is unaffected. | `r2.py:247-255,272-278`; `congress_api/cli/raw_sync.py:323`; no cache at `dispatch_corpus_recovery_import.py:140` | Yes, in capture runs with `--native-config`. | Medium: hand to the ct-2ukk reviewer |

**Checked and safe in this batch:**
- Raw bodies and receipts from recovery import are written immutable, with `IfNoneMatch='*'`, and read back exactly (`transfer.py:26-46`, `:132`, `:147`).
- No R2 delete exists in corpus_recovery, viewer_publication, news_lake or docspec_client (grep).
- No batch ticket widens public exposure. The edge rules expose only `bodies/sha256/`, release and manifest paths under `viewer-publications/`, and `exports/`; `receipts/` and journals are not public (`r2_edge_rules.py:19-27`).
- news_lake never touches R2. Its captures hold only a `payload_uri` and hash (`news_lake/adapters/common.py:83-93`), so it is outside the salvage set.

## 2. Re-ranking: earlier problems that drop away

- **ct-h73z** (failing historical-checkout test): drops. Resuming old attempts is compatibility nobody needs. Delete the `[True]` test case and, preferably, the resume-descriptor path.
- **ct-oc2g** (v5 removed before ct-2ukk closed): no longer a problem. Removing the legacy format is the right move. LANDED-CONCERNS → **LANDED-SOUND**.
- **ct-ma8a / ct-r46l** (fingerprint misses modules; shim): low. The worst case is a stale derived site.
- **ct-xu1o** (duplicate ids): drops from #1 to medium. It affects only derived append tables in a local pilot. Still fix it, or drop the time keys.
- **ct-v6ao / ct-30pw / ct-5jqd / ct-76n5 / ct-2ut4 / ct-bpyj**: concerns about durability of derived publication become irrelevant. A crash means rebuilding.
- **ct-4zer / ct-m9ry / ct-o6d1 / ct-tdsx / ct-2bhh**: viewer performance and memory policy with no users. Irrelevant.
- **ct-2io2** (merged tree never fully green): irrelevant.
- **Rises:** ct-esm4 becomes this batch's top problem (R1).

## 3. Grade changes (old → new). Unlisted grades are unchanged.

| ticket | proposal | work | reason |
|---|---|---|---|
| ct-fqgf | 87 → 91 | – | Protects custody of raw imports by comparing the caller's loaded bytes. |
| ct-vxzu | 86 → 90 | – | Raw writes are never blindly re-PUT; exact-byte reconciliation. |
| ct-esm4 | 82 → 86 | 77 → 70 | Right goal (provenance of raw writes), but its stale pin list is the batch's top raw gap. |
| ct-oc2g | 75 → 80 | 62 → 82 | Deleting the legacy format is correct; the cutover gate was compatibility ceremony. |
| ct-ur7v | 84 → 74 | 86 → 80 | Kept a second engine as an "oracle" instead of deleting it; pyiceberg is still a runtime dependency. |
| ct-v6ao | 90 → 74 | – | Crash-proofing checkpoints for rebuildable output. |
| ct-h73z | 86 → 68 | – | Resume machinery for derived attempts. |
| ct-2ut4 | 85 → 76 | – | Event-log authority for a derived route. |
| ct-76n5 | 78 → 66 | – | Preserves evidence of incomplete derived builds; just delete and rebuild. |
| ct-bpyj | 78 → 68 | – | Custody ceremony for derived viewer plans. |
| ct-30pw | 74 → 66 | – | Optimizes a derived publication journal. |
| ct-5jqd | 72 → 62 | – | Progress reporting for derived reconciliation. |
| ct-4zer | 82 → 70 | – | Browser search performance with no users. |
| ct-m9ry | 88 → 80 | – | Measure-first is still good, but the target was a derived publisher. |
| ct-o6d1 | 74 → 62 | – | Export memory policy for an unused viewer. |
| ct-tdsx | 85 → 78 | – | Sound but low-value hardening. |
| ct-2bhh | 65 → 60 | – | Memory tuning of derived publication with no gain. |
| ct-ma8a | 83 → 74 | – | Preserves pre-`uv sync` preflight for derived publication. |
| ct-r46l | 78 → 66 | – | A fence around derived publication tooling. |

New batch averages: proposal 76.0 (was 80.4), work 80.7 (was 80.5).

## 4. Keep / simplify / delete

- **Corpus recovery raw import** (`import_batch`, `checked_put`, admission and inventory seal checks, `write_recovery`): **KEEP**. Fix R1 by dropping per-file pin lists: record the git commit, a `uv.lock` hash and a clean-tree check, or pin whole package folders.
- **Bucket layout:** **SIMPLIFY.** Move all derived output (viewer publications, catalog generations, journals) to its own bucket, with credentials that cannot write `congressional-tech-raw`. That removes R2 at the root and makes the raw bucket append-only by policy.
- **Viewer publication durability stack:** **DELETE** most of it. That means the remote journal with nonce chain and intents, lost-ack reconciliation for derived files, local events, reconciliation progress, incomplete-build diagnostics, resume descriptors, accepted-plan custody and checkpoint tuning. Replace it with: write the release to a fresh immutable prefix, verify, then CAS one pointer; on failure, rebuild.
- **Browser viewer performance and policy, Catalog tuning, and the efficiency-debt experiment harnesses:** **STOP and archive.** Keep the simple verified loader (`startup.ts`). Delete the lazy-promotion `Catalog` code (ct-2bhh) once the review-binding CLI no longer needs it.
- **Scripts reshape** (shims, `viewer_release_identity` stdlib constraint, hand-written release fingerprint): **SIMPLIFY.** Run preflight after `uv sync`, delete the shims, and fingerprint with the git tree hash.
- **news_lake:** **KEEP** the DocSpec route. **DELETE** the PyIceberg coordinator and views oracle and the pyiceberg dependency. Fix ct-xu1o with an id fallback, or revert to `['id']` keys and rely on compaction.
- **docspec engine and client** (ct-tuez, ct-13g5, ct-nmjc): **KEEP**, because they make rebuilds cheap. Collapse ct-nmjc's three sizing modes into one now that the engine splits oversized batches (docspec-rs c937ef8/c949c67).
