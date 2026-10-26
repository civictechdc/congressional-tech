# Combined main review: component index and continuation capacity

**Reviewed source:** `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`.

**Findings-first verdict: APPROVE in the inspected scope.** No actionable regression or incomplete behavior was found in the component lookup/index, shared continuation accounting, cloud journal replay, local journal port, status inspection, or release-fingerprint inclusion. This is a review of their combined merged source, including the acknowledged-upload policy, rather than an endorsement of the superseded `5c581a6e` implementation.

The task branch was empty-rebased onto the exact reviewed SHA after preserving `540d8b34fc4790a49f2d94031e75ba84b7b8d653` at `codex/v6-evidence-before-main-review`. Earlier experimental work remains at `codex/v6-native-components-before-port`. No old capacity constants or cloud-to-local continuation switch were reintroduced. The primary and shared integration checkouts were not edited.

## Scope and hypotheses

The review follows the semi-formal-code-review skill. It inspects behavior-critical callers/callees and relevant test assertions; it does not repeat the separate raw-source, YouTube, GPO, or JavaScript reviews.

Patch summary: the merged source adds a component-first SQLite index, coordinated finite release budgets, exact incremental byte admission, periodic cloud cache checkpoints, linear local event replay, runtime-sized status inspection, and local-source fingerprint inclusion. Combined upload changes accept successful acknowledgments without routine remote byte rereads while retaining conditional mutation and uncertain-request reconciliation.

| Hypothesis before tracing | Evidence and disposition |
| --- | --- |
| H1: The component-first index changes lookup cost without changing document membership or output. | Confirmed: constructor creates `views_by_component(component,name)`; the existing join and one-document-partition guard remain unchanged (`filename_native.py:453`, `filename_native.py:637`). The focused test compares complete entries and actual queries with and without the index. |
| H2: Cloud and local routes use one transition rule and matching byte accounting. | Confirmed: `write_transition` owns legality; `checked_event` calculates serialized deltas; cloud and local recording use it before applying state (`continuation.py:99`, `continuation.py:265`, `local.py:126`). |
| H3: Periodic cloud checkpoints preserve pending-write recovery. | Confirmed: remote intent precedes payload; the next accepted event can include one pending acknowledgment. Full chain validation precedes checkpoint replacement (`client.py:177`, `continuation.py:448`, `continuation.py:514`). |
| H4: The local/status port preserves distinct authority boundaries and finite limits. | Confirmed: local events remain the local recovery source, cloud attempts still use `Continuation` plus `DurableJournal`, and status only reports observations (`local.py:29`, `attempt.py:335`, `pipeline_status.py:113`). |
| H5: Release identity includes the new local dependency. | Confirmed: `source_files` includes `local.py`, and a parametrized test changes its bytes and observes the source identity change (`release_identity.py:45`, `test_viewer_publication_attempt.py:405`). |

All source paths below are repository-relative. Function and test references give one-based lines in the reviewed SHA.

## Function trace

| Function | Source | Input → output | Verified behavior |
| --- | --- | --- | --- |
| `NativeComponents.__init__` | `packages/viewer_publication/src/viewer_publication/filename_native.py:444` | Selected catalog, asset owner, SQLite database → staging tables/index | `IF NOT EXISTS` also installs the index on a populated staging database. No table key or query semantics change. |
| `prepare` / `_register_chunks` / `_prepare_chunk` | `filename_native.py:545`, `:551`, `:573` | Selected component proofs/chunks → stats, membership, document asset references | The name-first primary key still supports physical-chunk membership reads; only document-first reverse lookup gains an index. |
| `_prepare_entries` | `filename_native.py:625` | Component rows/proofs and assets → serialized component/browse records | Joins asset references through membership by component, then requires exactly one document partition. |
| `write_transition` / `apply_event` | `packages/viewer_publication/src/viewer_publication/continuation.py:99`, `:127` | Event and current write map → checked change / updated map | Reject illegal acknowledgment, changed intent identity, and count overflow; informational events do not change writes. |
| `Continuation.phase` | `continuation.py:210` | Action and exact file inventory → accepted result | Checks file/count/serialized-state limits before adding the phase. Existing phases verify matching inventory or owned file bytes. |
| `Continuation.checked_event` / `record` | `continuation.py:265`, `:291` | One event → exact canonical-JSON size delta and applied change | Accounts for insert/delete/replace, commas, escaped Unicode, and protected-version changes. Direct recording checkpoints immediately; cloud recording can defer cache writes. |
| `DurableJournal.record` / `_append` | `continuation.py:514`, `:538` | Event plus optional pending acknowledgment → conditional remote event and accepted local evidence | Admits state/event/total-byte budgets before the payload call. Keeps one pending acknowledgment and writes cache periodically or at a control event. |
| `DurableJournal.restore` | `continuation.py:448` | Remote ordered event prefix → reconstructed writes and one cache checkpoint | Validates sequence, previous digest, nonce, binding, transitions, counts, and serialized bytes before replacing the current write map. |
| `Continuation.reconcile` / `replay` | `continuation.py:341`, `:389` | Restored intents and original payload → resolved uncertain outcomes / acknowledged receipt | Reads only uncertain writes. Acknowledged writes reuse recorded ETags and matching local payload identities without GET/HEAD. |
| `LocalContinuation.record` / `_append` | `packages/viewer_publication/src/viewer_publication/local.py:122`, `:83` | Checked event → synced local event, then updated in-memory state | Uses inherited accounting. The append precedes state application; failed sync marks the session as requiring explicit resume. |
| `read_local_journal` / `_restore` | `local.py:29`, `:106` | Bounded hash-linked history → validated state and measured size | Replays into unpublished state without cloning the full map per event; rejects truncated, malformed, foreign-binding, and oversized histories. |
| Status `continuation` | `scripts/publication/pipeline_status.py:113` | Local receipt/history and expected run identity → observations | Uses runtime write/event/state/journal ceilings. Reads local events through a read-only parser, attributes accepted output only to the expected run, and retains `public_readback=not_checked`. |
| `source_files` | `packages/viewer_publication/src/viewer_publication/release_identity.py:22` | Source tree → source hashes | Includes continuation, local, and release-identity implementation; custody cache is invalidated when source metadata changes. |

Important caller traces:

- Cloud: `attempt.prepare` creates the base continuation and accepts the exact prepared inventory (`attempt.py:95`, `:161`). `attempt.publish` restores it, initializes protected versions, restores/reconciles an explicit resumed journal, then creates the guarded client (`attempt.py:323`, `:335`, `:346`). `GuardedPublicationClient.put_object` records intent before PUT and acknowledgment afterward; only uncertain outcomes read back (`client.py:175–221`).
- Local: `scripts/corpus_recovery/dispatch_corpus_recovery_publication.py:240` selects `LocalContinuation`. `corpus_recovery.publication.prepare_viewer` saves protected inputs before phase acceptance (`publication.py:16–68`); `publish_imported` forwards events to `continuation.record` (`publication.py:83–87`). The port does not substitute the local event route for cloud recovery.
- CI/status: `.github/workflows/publish-filename-viewer.yml:131–142` selects state, capacity, and local tests while allowing explicitly resumed historical checkouts to omit later-added optional suites. `pipeline_status.summarize` consumes status observations, not mutation authority (`pipeline_status.py:211`).

## Data flow and invariants

1. **Exact component ownership.** Selected chunk membership enters `views` during registration. Document references enter `chunk_assets` during chunk preparation. The new reverse index changes the access path; missing or multiple document partitions still fail before serializing an entry (`filename_native.py:637–640`).
2. **One transition authority.** New intents contain original conditions, byte count, and SHA-256. `write_transition` returns a new record without mutating the current map. Both recording routes check it before publication; unrelated records and the shared protected-version map retain identity (`continuation.py:99–136`, `:265–304`, `local.py:122–137`).
3. **Exact byte budget.** `_state_bytes` is measured at creation, restore, and flush. Each changed write contributes its actual canonical-JSON delta, including a possible protected ETag replacement. Phase admission measures its complete serialized addition. Escaped-Unicode state cannot evade the canonical size check (`continuation.py:139–172`, `:256–288`).
4. **Finite coordinated limits.** Shared ceilings remain 131,072 phase files, 131,328 writes, 262,784 events, 128 MiB state, 1 MiB/event, and 256 MiB remote journal (`continuation.py:26–33`). The local history derives 262,850 events, 512 MiB history bytes, and a state-sized checkpoint record allowance from those same constants (`local.py:16–18`). Status reads those runtime constants instead of the old smaller literals (`pipeline_status.py:126`, `:157`, `:175–192`). Count and byte admission remain independent.
5. **Accepted upload versus uncertain request.** `verified` in the retained schema now records a successful acknowledgment or a reconciled uncertain intent; it does not promise a routine remote byte reread. Successful receipts are reused for identical local payloads and original conditions. An uncertain outcome still requires reconciliation, and mutable selector commits retain their conditional/freshness guards (`client.py:177–221`, `:253–263`, `continuation.py:341–409`, `attempt.py:357–364`). This follows the user's explicit upload policy.
6. **Recovery before effect.** A cloud intent's exact nonce-bound bytes are synced before its conditional remote event. Accepted local journal names hard-link the same bytes rather than rewriting the payload. The remote chain owns cloud recovery; local event history owns local-only recovery. Neither status nor progress records confer either authority (`continuation.py:180–208`, `:448–561`, `local.py:29–104`, `pipeline_status.py:205–208`).
7. **No partial restore acceptance.** Full remote prefix validation completes before local checkpoint replacement. Local replay similarly finishes validation before a constructor exposes state; it does not rewrite damaged history (`continuation.py:465–512`, `local.py:29–68`).

## Tests and boundary cases

The assertions below were read, not inferred from test names. Execution results are recorded separately below.

| Test and line | Concrete trace/assertion | Risk addressed |
| --- | --- | --- |
| `test_filename_native_indexes.py:18` | Runs actual entry preparation without/with index, compares complete entries and lookup results, checks SEARCH rather than SCAN, and reopens staging twice. Missing and duplicate asset matches are covered. | Result parity and idempotent index installation. |
| `test_publication_capacity.py:74` | 100,000 synthetic one-byte uploads; interrupts after 50,000; rebuilds from remote chain; performs one uncertain GET; replays accepted uploads with no extra PUT/GET/HEAD; validates final serialized size and corrupted-chain refusal. | Large combined upload/replay path. |
| `test_publication_capacity.py:153` | Tests count ceilings, the next refused file/write, and a binding shaped like the retained ~9.6 MB input. | Coordinated count and byte support. |
| `test_publication_capacity.py:178`, `:240` | Tightened state/event/journal budgets reject before remote append and payload; phase state remains unaccepted. | Admission timing and no partial acceptance. |
| `test_publication_capacity.py:195`, `:281` | Compares incremental accounting with complete canonical JSON through Unicode, insertion, acknowledgment, refusal, and restore. | Exact size deltas and Unicode expansion. |
| `test_publication_capacity.py:258` | All intents precede all acknowledgments at write capacity; checks worst-case noncoalesced event/byte bounds. | Parallel completion ordering. |
| `test_publication_state_bounds.py:49` | Counts real evidence writes and fsync calls; accepted/request names share one inode and two links. | Single-write evidence retention. |
| `test_publication_state_bounds.py:85`, `:150`, `:166` | Interrupts before/after remote PUT and before acceptance link; changes saved request bytes; injects failed fsync. Recovery retains evidence and does not resend uncertain requests. | Crash and custody boundaries. |
| `test_publication_state_bounds.py:201`, `:217`, `:380` | Malformed remote version, chain, joined acknowledgment, and byte/event overflow refuse before checkpoint replacement. | Whole-prefix validation. |
| `test_local_continuation.py:17`, `:30` | Point-lookup-only map forbids full traversal; 66,001 real log records restore the same 33,000 acknowledged writes. | Linear recording/replay and old event-cap regression. |
| `test_local_continuation.py:46`, `:121`, `:148` | Removes/corrupts the derived checkpoint; checks exact Unicode deltas and malformed/truncated/mismatched local history. | Local recovery source and no repair-by-truncation. |
| `test_local_continuation.py:169`, `:190`, `:199`, `:246` | Rejects size/count/sync failures; recovers accepted phase after checkpoint failure; checks sync-before-PUT and stable guard-map identity. | Effect ordering and shared state. |
| `test_pipeline_status.py:118`, `:218`, `:230`, `:259` | Attributes a bound journal, reads a >2 MiB receipt with 12,000 writes, enforces the shared write cap, and inspects fresh local events without constructing a mutable continuation or changing files. | Status capacity and read-only behavior. |
| `test_viewer_publication_attempt.py:405` | Includes `local.py` in the hash inputs, changes its bytes, and observes a changed source identity. | Release fingerprint completeness. |

Large metadata tests count per-event evidence saves/cache writes instead of performing 100,000 fsyncs. The 66,001-record local stress case disables fsync for event-count/replay coverage. Separate small tests execute real sync, link, interruption, and failure boundaries. Therefore these tests establish bounded fixture behavior, not production disk/network throughput or a real full-catalog publication.

## Execution evidence and limits

Executed at the exact reviewed source SHA: **221 passed in 45.46 seconds**, with no deselections or failures. Log: `/tmp/ct-index-merged-review-20261026.log`. The command uses this worktree's package sources first in `PYTHONPATH`, the existing Python runtime, private pytest dependencies under `/tmp/ct-v6-index-test-deps`, and no remote service:

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/tmp/ct-v6-index-test-deps:packages/viewer_publication/src:packages/congress_api/src:packages/congress_shared/src:packages/house-naming/src:packages/docspec_client/src:packages/congress_api/tests:tests:packages/corpus_recovery/src:scripts/publication:scripts \
/Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest -q -p no:cacheprovider \
  packages/viewer_publication/tests/test_filename_native_indexes.py \
  packages/viewer_publication/tests/test_publication_capacity.py \
  packages/viewer_publication/tests/test_publication_state_bounds.py \
  packages/viewer_publication/tests/test_local_continuation.py \
  packages/viewer_publication/tests/test_recovery_publication_continuation.py \
  packages/viewer_publication/tests/test_reconciliation_progress.py \
  packages/viewer_publication/tests/test_viewer_publication_attempt.py \
  packages/viewer_publication/tests/test_publication_control_reads.py \
  scripts/publication/tests/test_pipeline_status.py \
  scripts/publication/tests/test_workflow_resume.py \
  > /tmp/ct-index-merged-review-20261026.log 2>&1
```

`git diff --check` passed. Only this review document changed after test execution; reviewed runtime and test bytes remain those at the stated SHA.

Parent integration logs were inspected separately: `/tmp/ct-merge-publication-final-20261026.log` reports 723 tests plus 2 subtests; `/tmp/ct-merge-data-tests-20261026.log` reports 235 tests; `/tmp/ct-merge-js-tests-20261026.log` reports 154 JavaScript tests. Those are parent-run evidence, not additional executions by this reviewer. No hosted pipeline, deployment, remote mutation, or production rebuild was performed here.

## Findings and conclusion

No actionable findings in the inspected combined source. All behavior-critical paths in this scope have relevant assertions; no missing changed-path coverage was identified. The supported inventory is a finite measured class, not proof of the next real catalog's exact object count. Hosted runtime, actual complete inventory, transfer time, and deployed behavior remain qualification work outside this source review.

**VERDICT: APPROVE.** The combined implementation removes the indexed-lookup and fixed-capacity blockers while preserving exact state accounting, original write conditions, bounded recovery evidence, and the acknowledged-upload policy. Coverage: **ADEQUATE** for this local scoped review. Confidence: **HIGH** for the traced behavior; production readiness is not claimed. No fix commit is required.

## Final-source delta review

**Final source SHA:** `6183938fcb2b0842d5e1f59072383aa7dd251d32`.

The owned review branch was rebased onto this exact revision, preserving the report as `fd0bfc46155b0fe1b053b071d5f02cc6ebb37013`. Its previous report tip is preserved at `codex/v6-review-before-final-source` → `5232a908c91f3249dca77ec614370baf5bddc21d`. No source fix was replayed. This addendum inspects only the relevant `ad222085..6183938f` delta; the original trace and 221-test result above remain evidence for their stated earlier SHA.

| Relevant new change | Trace and boundary review | Result |
| --- | --- | --- |
| Maintained-source fingerprint coverage (`c4326f58`) | `release_identity.source_files` now includes the maintained R2 publisher, filename publisher, constants, and all DocSpec client Python sources (`release_identity.py:28–43`). Existing `local.py` inclusion remains at `:49`. The source cache still checks file custody before reuse and after hashing. `test_release_identity.py:41–59` changes each added maintained source and observes a changed identity. | APPROVE: closes missing hash inputs without changing continuation limits or transition behavior. |
| Absolute preparation deadline (`a82cfb55`) | `prepare_workflow_resume.run_preparation` derives one deadline from the saved job start, rechecks it after `verify_checkpoint`, and uses only the remaining interval for the child wait (`prepare_workflow_resume.py:92–114`). The new test advances a fake clock by 70 or 110 seconds in a 100-second budget and asserts a 30-second wait or refusal before launch (`test_preparation_checkpoint.py:355`). | APPROVE for this caller boundary: checkpoint verification consumes the existing job budget. |
| Occurrence writer byte admission (`6183938f`) | `filename_native.publish_occurrence_assets` forwards its policy and metrics to the shared writer (`filename_native.py:293–298`). Standalone export does the same (`filename_exports.py:448–457`). `OccurrenceParquetWriter.append` counts retained Python tree bytes, refuses an oversized single row, flushes existing pending rows before the projected buffer exceeds policy, and resets pending-byte accounting after flush (`filename_exports.py:346–354`, `:390–427`). Order/count/slice bookkeeping is unchanged; already-decoded values still feed the combined writer. New tests cover both standalone and combined paths (`test_filename_observations.py:342–386`). | APPROVE: both paths enforce the retained-row byte budget before adding an oversized row; combined failure issues no asset identities. This is not an assertion that all Arrow/native process memory equals the Python buffer metric. |

No changes in this delta affect the component index/query, shared continuation limits/accounting/replay, local journal implementation, or status reader. The raw capture-cache/interpreted-file and GPO timestamp fixes were not re-audited here; those remain their owners' review scope. No actionable regression or additional fix was found in this delta.

Executed **14 focused delta checks**, all passed in **1.23 seconds**, at the final source bytes. Log: `/tmp/ct-index-final-delta-review-20261026.log`. The command reused the explicit worktree-first Python path above and selected:

```sh
python -m pytest -q -p no:cacheprovider \
  packages/viewer_publication/tests/test_release_identity.py \
  packages/viewer_publication/tests/test_filename_observations.py::test_flat_occurrence_buffer_flushes_by_retained_bytes_before_row_limit \
  packages/viewer_publication/tests/test_filename_observations.py::test_flat_occurrence_refuses_single_row_larger_than_writer_byte_budget \
  scripts/publication/tests/test_preparation_checkpoint.py::test_checkpoint_verification_consumes_the_elapsed_job_budget
```

Parent follow-up logs were also inspected: 264 cross-cutting Python checks in `/tmp/ct-post-review-integration-20261026.log`, 126 renderer/native checks in `/tmp/ct-post-review-occurrence-20261026.log`, and 154 JavaScript checks in `/tmp/ct-post-review-js-20261026.log`. These overlapping focused runs are not additional unique tests to add to the earlier suite. They are parent-run local evidence, not hosted or deployed proof. No broad audit, full-catalog rebuild, remote mutation, operational-setting change, or source modification was performed by this final review.

**FINAL VERDICT: APPROVE for source `6183938fcb2b0842d5e1f59072383aa7dd251d32` in this review scope.** No unresolved source-review issue or fix commit. Hosted/deployed qualification remains separate; the filename-publisher and Pages operational settings were left untouched.
