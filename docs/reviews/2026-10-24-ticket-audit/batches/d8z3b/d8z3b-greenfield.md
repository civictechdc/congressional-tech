# Batch d8z3b: greenfield addendum (epic ct-d8z3)

Lens: nothing is in use. Only the raw/source data in R2 (`congressional-tech-raw`) must survive: bodies, receipts, and their provenance. Everything derived can be rebuilt. This addendum supplements d8z3b-verdicts.md and does not replace it. All checks were read-only at c858a5a2.

## 1. Raw-data risks (batch scope first, then adjacent code)

Nothing in this batch deletes R2 objects. The code paths here contain no `delete_object` or `delete_objects` calls; the only `rmtree` calls remove owned temp directories (catalog_publication.py:47, r2.py:573). The risks below are structural.

| # | Risk | Evidence | Reachable in production today? | Severity |
|---|---|---|---|---|
| R1 | **Derived publishing shares the raw bucket and a credential that can write all of it.** The viewer workflow passes `R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY` to the preflight, prepare and publish steps (publish-filename-viewer.yml, steps `preflight`, `prepare`, `Publish accepted preparation`). `BUCKET='congressional-tech-raw'` (constants.py:3). Only application code stands between the publisher and raw keys: the key allowlist in client.py:128-135, the PREFIX check in put_json (publish_viewer_r2.py:244-246), and PREFIX-scoped transfer keys (publish_viewer_r2.py:501). | The credential is present on every publish job. I found no code path that writes or deletes raw keys today, but one bug or a compromised dependency in that job could overwrite or delete bodies and receipts. | Medium (structural) |
| R2 | **R2Store.put defaults to an unconditional overwrite.** When `immutable=False` and the key is outside `indexes/`, `options` stays empty and put_object runs with no condition (r2.py:338, 372-383). LocalStore does the same with `os.replace` (catalog_cache.py:84, 102-103). | Not reached today: every raw writer passes `immutable=True` (raw_archive.py:378, 387, 522; capture_metadata.py:209; raw_storage.py:221-349; corpus_recovery/transfer.py:132, 147). Raw safety rests on every caller remembering one flag. ct-lu4i named "R2Store mixes namespace-specific policies" but fixed only catalog and derived paths. | Medium-low |
| R3 | **A 412 on an existing body is treated as success with no content check.** See r2.py:387-388 (`put`) and r2.py:436-440 (`put_file`). | Reached on every recapture of a body already stored. A truncated or wrong object at a content-addressed key would never be detected. New uploads are MD5-verified (r2.py:394, 442-443), so the exposure is limited to objects that were already bad. | Low |
| R4 | **Recovery-acceptance provenance is a mutable object stored under the derived prefix.** `viewer-publications/recoveries/accepted.json` (mappings.py:14) is replaced in place with IfMatch (mappings.py:76-78). R2 keeps no history of it. Before/after copies are saved only locally (mappings.py:69-70), and those output directories have already been pruned. Merges can only add rows (mappings.py:30-32), and the guarded client reads every write back. | Reachable by every recovery publication. The same associations also land in raw import receipts as `source_associations` (prepare_corpus_recovery_source_records.py:178), so it can be rebuilt. The danger is that a cleanup of `viewer-publications/` would delete it as "derived". | Low-medium |
| R5 (positive) | ct-jl1m's RecoveryGuard protects the raw import. It pins and rehashes inputs, checks protected object versions, and observes capture writers (dispatch_corpus_recovery_import.py:162-190, guards.py:101-147). The real exclusion on `indexes/raw.json` is CAS (r2.py:375-381). | Yes, on the recovery import path. | Keep |
| R6 (positive) | ct-qspb requires a body key's shard to match its digest before an accepted mapping is written (filename_recoveries.py:14-31, body_keys.py:11-18). ct-lu4i made local immutable writes use exclusive `os.link` (catalog_cache.py:97-101). | Yes. | Keep |
| R7 | The preflight signs GETs with the full write credential (publication_preflight.py:83-128). Exposure is contained: there is a key allowlist (36-49) and redirects are refused so `Authorization` is never forwarded (52-55). | Read-only in practice. A read-only token would be the platform primitive. | Low |

Adjacent risks, outside this batch, for the owning reviewers:
- **(a) Native-manifest disk cache.** It skips the upload when a cached file of the same size exists, and the cache is not keyed by bucket (immutable_metadata.py:85-88; r2.py:212-217, 341-352). RawStorage selects native datasets through `indexes/raw.json` (raw_storage.py:364). A `cache_dir` shared across buckets could therefore leave raw-state manifests unuploaded. `cache_dir` is opt-in (r2.py:185, 192).
- **(b) Public custom domain.** Hiding `receipts/`, `quarantine/` and `indexes/raw.json` on the raw bucket's public domain depends on one WAF allowlist (apply_r2_edge_rules.py:50-71).

## 2. Re-ranking the earlier problems

What drops away or falls to low:
- **ct-o24q identity regression** (was #1). Its effect is only stale derived output nobody sees. The greenfield fix is to rebuild on every code push or raw capture, not to repair the identity list.
- **ct-p6aq, ct-lvvr, ct-zika and ct-qyey memory/perf**: browser-only, no users.
- **ct-x7vx**: the missing prior-job comparison and the pruned rollout evidence.
- **ct-kde5**: preserving the local route; compatibility nobody needs.
- **ct-qxpa**: per-row reads on the native path; local research only.
- **ct-zb9y's 44 MB per poll**: it disappears if the 30-minute schedule is removed.
- **ct-zkzt dead v1 branches and ct-ylaw's thin consolidation**: simply delete.
- **ct-sv16 toy fixture**: still the wrong instrument, but nothing urgent now depends on it.

What rises: R1 to R4 above. None were in any ticket's acceptance criteria, and the epic said "preserve exact data" without ever naming raw durability as a goal.

## 3. Re-grades (only where my judgment changed)

| ticket | proposal | work | reason |
|---|---|---|---|
| ct-d8z3 | C (74) → C- (70) | C+ (78) → C (74) | Effort went to derived resume, compatibility and browser speed. Raw-bucket isolation and the R2 write policy were never raised. |
| ct-jl1m | B (84) → B+ (88) | B+ (87) → B+ (89) | It is the guard on raw import writes, kept honest about CAS being the real authority. |
| ct-qspb | A (93) → A (95) | unchanged | It protects the link from provenance to raw bodies. |
| ct-o24q | A- (90) → B- (80) | unchanged | A correct bug for derived data, but greenfield needs "rebuild on change", not identity machinery. |
| ct-zkzt | A- (90) → B- (80) | B+ (88) → B (84) | Mostly about resuming accepted preparation, which is compatibility nobody needs. The duplicate-scan removal still stands. |
| ct-m59w | C (76) → C- (70) | B (86) → B- (80) | Elaborate single-use receipts to avoid one readback of derived JSON. |
| ct-zb9y | B (86) → C+ (77) | B- (80) → C (74) | 400 lines and a hand-rolled SigV4 signer to save setup time on no-op polls of an unused site. |
| ct-x7vx | B (86) → C+ (78) | unchanged | It qualifies no-op cost for a site with no users. |
| ct-kde5 | C (74) → D+ (68) | C+ (75) → D+ (68) | Explicitly set out to preserve old routes, and the work was deleted in 3 days. |
| ct-vp92 | A- (90) → B (84) | A- (90) → B (84) | The locked two-rename swap with a recoverable backup protects a rebuildable public/ directory. |
| ct-l3s4 | B+ (87) → B- (80) | unchanged | Live-site polish with no live users. |
| ct-lvvr | C+ (78) → C (74) | unchanged | Browser performance before any users exist. |
| ct-p6aq | C+ (78) → C (74) | unchanged | Same. |
| ct-zika | C+ (77) → C (73) | unchanged | Same. |
| ct-qyey | C+ (78) → C (75) | unchanged | Same. |
| ct-qxpa | C (74) → C- (70) | unchanged | Performance of a local research export. |
| ct-rrfm | C- (72) → D+ (68) | unchanged | Engineering for derived memory, now dormant. |

New averages over 23 rows: proposal 82.0 → 78.4; work 83.7 → 82.4.

## 4. Keep / simplify / delete, by area

- **Raw isolation (new; no ticket in this batch): DO FIRST.**
  - Move derived outputs (`viewer-publications/`, `catalog-generations/`, `catalog-history/`, derived `indexes/*`) to a separate bucket.
  - Give the publisher a token scoped to that bucket only, and the preflight a read-only token.
  - Make R2Store and LocalStore refuse non-immutable writes to `bodies/`, `receipts/` and `quarantine/`, and verify the existing object on a 412.
  - Derive `accepted.json` from import receipts, or keep it append-only under a provenance prefix.
- **Corpus-recovery raw import guard (ct-jl1m, ct-qspb, ct-pd8n): KEEP.** It is cheap and protects raw.
- **Viewer publication pipeline (ct-zkzt, ct-m59w, ct-ylaw, ct-o24q, ct-zb9y, ct-x7vx): SIMPLIFY RADICALLY.**
  - Target shape: build into a fresh immutable release prefix, verify it, then flip one pointer with CAS.
  - Delete the continuation journal, resume descriptors, original-condition replay (`ContinuedPublicationClient`), accepted-preparation artifact upload and restore, the prepare / verify-prepared / publish split, the stdlib preflight with its custom signer, the 30-minute schedule (trigger on raw capture completion and code push instead), and the release-identity hashing.
  - Keep only the key allowlist and conditional writes. Most of those become unnecessary once derived data has its own bucket.
- **Derived alias/recovery indexing (ct-rrfm, ct-zkzt v1 branches): DELETE** the SQLite AliasIndex, `catalog_aliases` and the historical `index_recoveries` path. Keep one native recovery implementation.
- **Browser viewer (ct-lvvr, ct-p6aq, ct-zika, ct-qyey, ct-rckw, ct-l3s4, ct-p6ns, ct-kde5): FREEZE and SIMPLIFY.**
  - Keep `cache.ts` and `withVerifiedJson`.
  - Pick one occurrence format: either the bin observation reader or the parquet one, and delete the other.
  - Drop counters that exist only for ticket evidence.
  - No further performance work until there are real users.
- **Review export and staging (ct-qxpa, ct-vp92): SIMPLIFY.** Delete the legacy file-path Catalog branch. For staging, extract to a temp directory and rename, or `rm -rf` and re-extract; drop the lock and `.previous` swap.
- **Measurement (ct-sv16): SIMPLIFY.** Keep the workflow's job-cost receipt step. Delete `measure_publication_control.py`, which is coupled to test internals, and measure real data when a decision needs it.
