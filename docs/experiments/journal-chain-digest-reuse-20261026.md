# Reuse the saved journal-request digest

Baseline: `7242f0419f589ffcf9e52f5f5068fb4edd5b6c44`. Independent review approved this change with no findings. It is complete locally in the isolated `journal-chain-digest-reuse` worktree on `codex/journal-chain-digest-reuse-20261026`; it has not been merged, pushed, published, or deployed. Candidate `continuation.py` SHA-256: `54ea32563bbea6b8db3549f42b6f3aa00dfefbc1d579e07b2636ad9af934a8db`. Exact baseline/candidate source hashes and the source diff are also retained in `output/journal-chain-digest-reuse-20261026/source-manifest.json`.

`DurableJournal._append` now advances its chain with the digest issued by `Continuation.save`. This assignment still occurs only after the guarded conditional PUT and accepted-file custody/link checks succeed. The atomic writer hashes the exact immutable request bytes; guarded-client admission still independently hashes the outgoing body. Event bytes, acknowledgment grouping, per-object intents, locks, byte/count ceilings, failure ordering, and restore checks are unchanged.

## Evidence

The original bounded survey is `output/duplication-validation-20261026/capacity-journal/report.md` in the primary checkout. Its tiny six-payload instrumented fixture was copied unchanged into this owned worktree. It delegates to maintained entrypoints, uses a fake transport, and performs real local writes/fsyncs.

| Six simultaneous one-byte payloads | Baseline | Candidate |
| --- | ---: | ---: |
| Journal records / PUTs | 8 | 8 |
| Payload PUTs | 6 | 6 |
| Journal-body SHA calls | 24 | 16 |
| Journal-body SHA calls per append | 3 | 2 |
| Successful payload GET/HEAD | 0 / 0 | 0 / 0 |
| Startup attempt-existence GET | 1 | 1 |

Raw results: `output/journal-chain-digest-reuse-20261026/baseline.json` and `candidate.json`. Both fixtures rejected late chain corruption without accepted-state mutation. The candidate measurement used the baseline HEAD plus the reviewed source diff recorded in the manifest; it is not a measurement of the unchanged baseline revision.

Focused regression evidence:

- Baseline failure/custody cases: **7 passed**, 32 deselected.
- New hash-count and chain regression against unchanged production source: **1 expected failure**, 39 deselected; retained `red.log`.
- Candidate focused checks: **13 passed**, 46 deselected; retained `green.log`. These include interruption before/after PUT, failed accepted linkage, failed joined append, changed request custody, linked local corruption, late remote corruption, interrupted fetch/staging failure, and changed restore-spool custody.

Commands below ran in the isolated worktree. `PYTHONDONTWRITEBYTECODE=1` was set throughout; no dependency installation or source-checkout pycache writes. The probe command ran before and after the single production assignment changed, with `baseline-fixture`/`baseline.json` replaced by `candidate-fixture`/`candidate.json` for the second arm.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/packages/viewer_publication/src:$PWD/packages/congress_shared/src:$PWD/packages/congress_api/src" /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -B output/journal-chain-digest-reuse-20261026/probe.py "$PWD" "$PWD/output/journal-chain-digest-reuse-20261026/baseline-fixture" 7242f0419f589ffcf9e52f5f5068fb4edd5b6c44 > output/journal-chain-digest-reuse-20261026/baseline.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/packages/viewer_publication/src:$PWD/packages/congress_shared/src:$PWD/packages/congress_api/src" /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -B -m pytest -q -p no:cacheprovider packages/viewer_publication/tests/test_publication_state_bounds.py -k 'journal_append_reuses_saved_digest_and_preserves_chain or journal_interruption_preserves_request_and_resumes or journal_refuses_changed_request_before_linking_acceptance or failed_joined_append_retains_pending_fact_and_sequence or linked_local_corruption_is_still_refused_on_restore' packages/viewer_publication/tests/test_journal_restore.py -k 'journal_append_reuses_saved_digest_and_preserves_chain or journal_interruption_preserves_request_and_resumes or journal_refuses_changed_request_before_linking_acceptance or failed_joined_append_retains_pending_fact_and_sequence or linked_local_corruption_is_still_refused_on_restore or failed_restore_keeps_accepted_state_and_cleans_spool or changed_spool_is_refused_before_publishing_accepted_evidence' > output/journal-chain-digest-reuse-20261026/green.log 2>&1
```

## Limits

This establishes one fewer full-body SHA computation per journal append, not a hosted throughput improvement. The two tiny probes finished in under one second combined; no large fixture, full suite, native build, service request, publication, or deployment ran. File proof custody and client byte admission remain separate checks. No new proof API or cache was introduced. Independent review confirmed issued immutable proof custody, no chain advancement on failed saves/PUTs/accepted links, and unchanged collision checks, limits, event format, and grouping.
