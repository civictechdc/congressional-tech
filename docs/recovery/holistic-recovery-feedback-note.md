# Native feedback implementation note

## Scheduler and profile integration needed

The scheduler currently reads `url_state.parquet`, `capture_scope.json`, `capture_profile.json`, and `url_variants.parquet` from a selected release. `capture_scheduler.py` builds `candidates`, then filters `eligible` before `due` and budget reservation. Its campaign path must carry these native UTF-8 columns through `keyed_states` and `candidates`: `capture_disposition` (`eligible`, `satisfied`, `excluded`), `capture_reason`, and nullable `capture_decision_id`. It must filter historical `satisfied` and `excluded` before ranking or reserving requests, and explicitly reject unknown/null dispositions in a recovery-profile release. Do not infer this state from HTTP status, attempts, or a filename. Seed and variant aliases need the same policy decision as their target; merging conflicting literals requires explicit refusal or a conservative eligible result.

A new capture profile version must bind the precise policy version and target-requirement input identity. Recovery campaigns must reject version 1, while any legacy scheduling path must opt in explicitly. The policy must distinguish historical requirements (`historical_exact`, `requested_content`, `current_official_counterpart`) from live freshness: a historical recovery can satisfy a pinned historical target without disabling a live-page refresh.

Current provenance decisions contain `body_sha256`, `original_url`, `kind`, and `evidence_sha256`, but the native inputs do not contain a pinned per-target requirement or a qualification/acceptance result. A recovery category or filename alone is insufficient. The recovery owner must supply a typed immutable binding with at least target literal URL, requirement and policy identity, decision ID and accepted/rejected state, relationship kind, body digest, receipt key/line/capture index, and qualification identity. The native producer must check the current non-superseded decision and exact retained-import identity before emitting `satisfied`, and apply a pinned mapping from relationship kinds to requirements. Missing, rejected, superseded, mismatched, or ambiguous evidence must remain eligible. This proposed interface is not implemented or agreed with the recovery owner yet.

Existing scope already excludes common media extensions and allows captions. An exclusion for an expired stream must be narrow enough to preserve caption and document discovery. No scope change has been made.

## Publication continuation

`archive_publish_job.execute` and `archive_controller.run_publish` currently require fresh work, model output, and scratch directories. The selected pointer is managed by `archive_publish`; fresh-process continuation must bind the original model spec, receipt and provenance identities, native result and release manifest, reconcile the selected pointer and its existing input record, and reuse only verified completed work. Retain the old selected release until the replacement passes both reader gates and conditional selection. No fresh-process continuation is implemented here.

The existing gate now reconciles an exception from its conditional pointer PUT by reading the actual selected pointer. Only an exact release and previous-release match with a valid observed ETag is accepted. It performs no second PUT; conflicting or unreadable selection preserves the original failure. Publisher status identifies this as `selected_pointer_reconciled`. A missing ETag in a returned response still fails under the existing policy. This is one uncertainty boundary, not proof of publication resume.

## Verification and remaining work

The focused local gate/publisher tests passed: 73 passed, one real-canary test deselected. The Python module path was verified in this worktree; the shared environment supplied dependencies. No native engine, external storage, production publication, or corpus reads were used. The gate test uses in-memory local storage, not an actual remote reader or process-kill test.

The eligibility producer, typed inputs, policy binding, profile version, source-scope exclusion, scheduler integration, native output reuse, fresh-process restart, and local published-reader journey remain unfinished. The exact recovery input format and custody handoff require coordination with the recovery owner before implementing suppression. The capture owner must implement the scheduler consumer described above; no scheduler or capture CLI files were changed here.
