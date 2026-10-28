# Raw seed and fingerprint reuse — October 26, 2026

A raw catalog update now writes and hashes its ordered seed input once. Nested
source replay reuses the same read-only spool and digest while the outer caller
keeps its SQLite owner open. Each iteration still returns detached rows; one-shot
inputs, original order, duplicates, empty inputs and the canonical digest retain
their existing behavior.

Source requirements are calculated once per update, including nested replay and
proof verification. Overlapping implementation/policy hashes share source bytes
within that calculation. A context-local owner releases the result after success
or failure; independent calls outside an operation calculate fresh requirements.
Each reuse checks the current file inventory, device/inode, size, modification and
change timestamps, runtime version and filename-parser function identities. A
changed source version refuses the current update. A new operation recalculates
requirements, so a checkpoint from different source bytes still refuses.

This removes repeated byte reads and hash/serialization work. It deliberately
retains directory enumeration and file metadata checks on reuse. Those metadata
checks assume ordinary local filesystem version reporting; they are not a defense
against a hostile filesystem that can forge all metadata.

## Measured operation counts

Baseline: local `7242f0419f589ffcf9e52f5f5068fb4edd5b6c44`, identical assigned
raw-path source to pushed `0bfeb21e84b73a9637713a3673d61dc97beb53be`.
The implementation is in the commit containing this note. The first candidate
probe ran with these implementation files modified over that baseline; its
reported HEAD therefore remains the baseline, not a claim of a clean candidate.

The unchanged maintained probe exercises the real raw CLI update path, then a
seed-label correction, using three seeds and two receipt-backed URLs. Both
operations showed the following reductions:

| Per operation | Baseline | Candidate |
| --- | ---: | ---: |
| Seed canonical JSON encodes | 6 | 3 |
| Seed SQLite pickle encodes | 6 | 3 |
| Seed helper calls / actual spools | 2 / 2 | 2 / 1 |
| Source requirement lookups | 6 | 6 |
| Fingerprint file byte reads | 528 | 85 |
| Distinct fingerprint files | 85 | 85 |

The focused calculation counter also verifies one requirements calculation per
operation, including nested scope reuse, and a fresh calculation in the next
operation. File byte reads become one per distinct input. Seed digests, grouping
memberships and the five observed source fields match the baseline fixture.
These are deterministic operation counts, not a measured production speedup.

## Verification and limits

- New regressions initially produced five failures and one pass on the baseline;
  the nonempty seed fixture showed six canonical encodes instead of three.
- Final focused checks: **85 passed, 14 skipped**. The skips require a configured
  native binary. Tests cover ordinary daily seed/code changes, one-shot/repeatable
  seeds, detached values and owner lifetime, fresh/failed/nested operations,
  source and rule-file mutation, added/deleted rules and parsers, and a same-size
  rule edit with its modification timestamp restored.
- A source mutation during real maintained replay refuses before catalog
  selection. Retrying its old directory refuses the changed implementation;
  a fresh operation directory succeeds. Existing completed-replay recovery also
  rejects changed source bytes before payload reuse.
- Counterexamples remain decisive: one early source expands to three after
  dependency closure; equal interpreted gzip rows can have different file
  hashes; equal Parquet values/row proofs can have different physical hashes;
  replacing the retained Parquet file refuses resume and preserves selector
  bytes. Physical and logical identities remain separate.
- `git diff --check` passes. No dependency install, native build, external
  acquisition, main merge, push or publication was performed. Native execution,
  production throughput, peak memory and physical disk I/O remain unmeasured.

Focused command, from this task's worktree:

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/congress_api/src:packages/docspec_client/src:packages/congress_shared/src:packages/committee_meeting/src:packages/house-naming/src /Users/mikewolfd/Work/congressional-tech/.venv/bin/python .github/scripts/offline-python.py -m pytest packages/congress_api/tests/test_source_operation_reuse.py packages/congress_api/tests/test_source_replay.py packages/congress_api/tests/test_source_replay_capture_stream.py packages/congress_api/tests/test_catalog_raw_updates.py packages/congress_api/tests/test_source_update_proof.py packages/congress_api/tests/test_native_raw_cli.py packages/congress_api/tests/test_catalog_dependencies.py packages/congress_api/tests/test_catalog_scope.py -q -p no:cacheprovider
```

Baseline, instrumentation, retained first candidate results and counterexamples:
`/Users/mikewolfd/Work/congressional-tech/output/duplication-validation-20261026/raw/`
(`report.md`, `probe.py`, `counterexamples.py`, `current-attempt2/`,
`implemented-attempt1/`, `implemented-counterexamples1/`). The assigned output
namespace contains fixture evidence only. Source changes are confined to this
isolated worktree. Focused test logs are `/tmp/ct-raw-operation-reuse-*.log`.
