# Independent review of T4 and T5

Verdict: **APPROVE**, with one integration-test observation tracked by the parent task. This review found no behavioral blocker in the body-verification reuse or Arrow preservation changes. It does not establish production qualification or authorize remote writes.

## Patch summary

Reviewed `37ee074` and `891209d`, plus their import-dispatch caller in the integration worktree. T4 reuses exact retained-body evidence only after a fresh version and size check. T5 appends new states to the original Arrow table and compares saved baseline rows in batches.

The review followed the semi-formal code review skill. Hypothesis H1 was that stale prior body evidence could skip verification; the implementation refuted this for changed body identity, size or ETag. H2 was that converting fewer state rows could omit untouched values; retaining the original Arrow table and checking ordered prefixes refuted this for the supported schema. H3 was that receipt multiplicity might collapse during state deduplication; separate capture append rows and exact receipt counters preserve it.

## Function trace

| Function | Location | Input and output | Verified behavior |
| --- | --- | --- | --- |
| `reusable_result` | `scripts/reconcile_corpus_recovery_bodies.py:28` | Desired body and prior result to boolean | Requires canonical body key, raw SHA and size, stored SHA and size, explicit verified status and ETag. |
| `head_body` | `scripts/reconcile_corpus_recovery_bodies.py:43` | Store and key to fresh metadata | Treats only known missing-object codes as absence. |
| `reconcile` | `scripts/reconcile_corpus_recovery_bodies.py:53` | Inventory and optional prior report to read-only result | Reuses matching versions; binds fallback bytes to the GET response; records conflicts and unknown reads. |
| `sealed_inputs` | `scripts/reconcile_corpus_recovery_bodies.py:87` | Batch to file pins, inventory and counts | Checks named files, source preparation and capture/body identity coverage. |
| Reconciliation `run` | `scripts/reconcile_corpus_recovery_bodies.py:114` | CLI arguments to external readiness | Checks prior digest before reuse; records protected remote versions and readback-report digest. |
| Import dispatch `run` | `scripts/dispatch_corpus_recovery_import.py:51` | Sealed inputs and external readiness to one import | Pins readback evidence, checks baseline versions, supplies cheap body guard and fresh shared-commit guard. |
| `checked_put` | `scripts/import_corpus_recovery_batch.py:23` | Guarded conditional write to exact readback | Never retries an uncertain PUT; verifies stored bytes. |
| `import_batch` | `scripts/import_corpus_recovery_batch.py:42` | Bodies, records and baseline Arrow tables to retained receipts/index pair | Hashes local bodies, uses exact prior proof or full GET, filters only requested baseline state rows, appends with the existing schema. |
| `PreservedStates` methods | `scripts/assemble_corpus_recovery_import.py:12` | Baseline mapping to lazy copies and ordered new states | Copies accessed rows only; new URLs share one state while captures remain separate. |
| `assemble` / `index_rows` | `scripts/assemble_corpus_recovery_import.py:42,90` | Prepared records and verified bodies to receipts and capture rows | Preserves parent/member pointers, original associations and each capture occurrence. |
| `compare_prefix` | `scripts/verify_corpus_recovery_import_preservation.py:24` | Two Parquet paths to row counts | Compares exact ordered values and types across different row groups. |
| `unique_state_urls` | `scripts/verify_corpus_recovery_import_preservation.py:47` | State path to uniqueness assertion | Uses one Arrow column; includes null in duplicate detection. |
| Preservation `verify` | `scripts/verify_corpus_recovery_import_preservation.py:55` | Saved completed import to local audit | Checks evidence, baseline prefixes, pending suffix rows, receipt state and exact capture multiplicity. |

## Data flow and invariants

The reconciliation report carries desired raw identity and verified stored identity. Import dispatch pins its file digest and checks its batch manifest. `import_batch` recomputes local raw identity and refreshes the object's ETag and stored size before using that evidence (`import_corpus_recovery_batch.py:55-85`). A mismatch takes the full stored-byte path. This remains dependent on the caller honoring the documented pinned-evidence requirement; the dispatcher does so.

Only the requested state rows enter Python dictionaries (`import_corpus_recovery_batch.py:86-90`). The original state table is retained and concatenated with `states.added` using the same schema (`:103-107`). Existing metadata is retained except for the intended capture-count/digest update. The audit ignores schema metadata while comparing row values, consistent with that intended metadata update (`verify_corpus_recovery_import_preservation.py:24-44`).

New states are unique by URL, but receipts and appended captures retain their individual occurrences. The audit checks exact receipt/capture counters (`verify_corpus_recovery_import_preservation.py:82-125`). It explicitly reports physical exit and fresh remote readback as unverified (`:128-131`).

## Tests and edge cases

Executed the five focused pytest files with bytecode and pytest cache writes disabled in the integration tree: **36 passed**.

- `test_full_then_prior_reuses_only_fresh_matching_version` (`tests/test_reconcile_corpus_recovery_bodies.py:38`) establishes one initial GET, reuse without another GET, and full verification after the stored version changes.
- Corrupt prior SHA/size and unknown reads (`:50-68`) take fallback or unresolved paths.
- Existing-body, pinned prior-body and lost-ack import probes (`tests/test_import_corpus_recovery_batch.py:123-185`) check zero unnecessary compression and no repeated PUT.
- Arrow preservation probes (`:188-225`) retain maximum unsigned integers, nested binary values, nulls, baseline capture duplicates and exact schema types; duplicate baseline URLs, including null, fail explicitly.
- Assembly probes (`tests/test_assemble_corpus_recovery_import.py:75-95`) reject copying untouched rows, preserve deep-copy independence and retain both receipts for a repeated URL.
- Prefix and duplicate-URL probes (`tests/test_verify_corpus_recovery_import_preservation.py:66-84`) compare differing row groups and detect changed values.
- Conditional dispatch probes (`tests/test_dispatch_corpus_recovery_import.py:83-98`) prevent a competing capture update from advancing the second raw index.

## Findings

**Observation: external readiness integration coverage.** The reviewed tests exercise the reconciliation functions and a prior-digest refusal, but do not run reconciliation output through external-readiness dispatch and publication verification. `tests/test_reconcile_corpus_recovery_bodies.py:71-77` exits before network/client setup. The parent task is adding that integrated fake-S3 probe. This is a coverage observation, not an observed implementation failure. Publication's direct evidence-binding probe separately verifies the external report digest and its batch binding.

No remaining correctness blocker was found in the reviewed T4/T5 changes. The synthetic memory comparison script was inspected, but its historical measurements were not rerun as part of this review.

## Conclusion

VERDICT: APPROVE

The code achieves the stated reuse and preservation behavior. Coverage of the changed core paths is adequate; the external-readiness integration observation remains assigned to the parent task. Confidence is high for the reviewed code paths and focused tests. Production-size replay, physical process exit, current remote readback and publication remain separate acceptance steps.
