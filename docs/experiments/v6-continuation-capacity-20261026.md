# V6 publication continuation capacity repair

Current merged behavior: publication accepts successful PUT responses without
routine GET/HEAD readback. It retains durable intents, conditional writes, chain
checks, accepted-file custody, uncertain-outcome resolution and bounded public
smoke checks. Inventory and upload/resume evidence have independent count and
byte limits. Local recovery now shares the larger capacity allowances.

The measurements below describe the original capacity repair and are historical
where later sections identify follow-up changes. No production preparation,
deployment or publication ran for this capacity experiment.

Base: `c466a45e09e27bde48ade12454f8b458c3643d21`.
Worktree: `/Users/mikewolfd/.codex/worktrees/v6-continuation-capacity/congressional-tech`.
The final task report records the commit SHA.

## Current input and sizing evidence

A bounded public read retrieved the selected 169,083-byte native metadata object
with SHA-256 `97e2ff1b675d11ba2dc6f4c9a9e25182474fa47060bc48b7913b358ffde841b8`.
Its counts are **1,683,430 sources and 1,241,157 grouped documents**, confirming
the parent's current selector evidence. Every fetched metadata body matched its
selected byte length and SHA-256. Eleven objects, totaling 446,791 bytes, covered
the selection, two routing roots, one path down each tree, and two component
metadata pages. They are retained as `/tmp/ct-capacity-*.json`.

The sampled component path branches through four hexadecimal positions before
a leaf; the sampled source path reaches a leaf after two. Component metadata
shares physical document chunks across components. This sample does **not** count
every selected leaf/chunk. It supports a modeled release of roughly 100,000 assets:
a complete depth-four component tree has 65,536 leaves and 4,369 branches;
1,241,157 documents need at least 19,394 sorted browse leaves plus 1,295 branches.
Source output, shared physical chunks, membership pages, inventory pages, and
controls add files. The full real inventory remains an integration check.

The previous 32,768 phase-file and 8,192 write limits fail even the minimum
38,788 browse/component leaves. Increasing either alone leaves the other refusal
and the separate 16,384-event journal refusal. A 32 MiB continuation also cannot
hold full inventory plus all write receipts: the scale exercise reaches 73.1 MB.

## Bounded repair

| Budget | Previous | New |
| --- | ---: | ---: |
| Phase files across all accepted phases | 32,768 | 131,072 |
| Retained writes / protected versions | 8,192 | 131,328 |
| Journal events | 16,384 | 262,784 |
| Serialized continuation | 32 MiB | 128 MiB |
| Total cloud journal | 64 MiB | 256 MiB |
| One journal event | 1 MiB | 1 MiB |
| Accepted phases | 64 | 64 |

The write allowance is the file allowance plus 256 release/control writes.
The event allowance is twice the write allowance plus twice the phase allowance;
parallel completions need not coalesce. Counts and bytes remain independent:
long keys, large ETags, or unusually large informational values can hit the byte
limit first. These are supported ceilings, not permission to truncate evidence.
At the count ceilings, a fixture with normal content-addressed names, 34-byte
ETags and a 9.6 MB retained binding occupies **89,309,508 state bytes**.

The cloud journal already owns write recovery. Its original pre-mutation intent
supports fresh body reconciliation when the last verification was not appended.
Full `continuation.json` serialization now occurs after each 1,024 cloud events
and on informational events, including completion/failure. Accepted phases and
direct `Continuation.record` calls still checkpoint immediately. This removes
per-asset copies of the growing write map and per-event full-state fsyncs.

One shared transition function validates the next write without mutating current
state. Exact canonical JSON deltas account for additions, changes, refusals,
commas, Unicode escaping, and protected-version changes before a journal append.
Restore checks both raw and canonical state byte limits. Phase byte overflow is
refused before accepting the phase. Cloud replay validates its complete prefix
and serialized state size before saving accepted local events or replacing the
checkpoint. Restore also avoids deep-copying the unchanged binding and phases.

No event or continuation format version changed. Cloud callers must restore the
journal before relying on write state; `attempt.publish` already does this.
A standalone read of `continuation.json` can see a stale derived write cache.

## Executed local evidence

The large test runs the maintained guarded/continued client, cloud journal,
transition validator, restore, reconciliation, and replay methods with an
in-memory object service. Per-event local evidence saves and periodic cache
writes are counted rather than executed. Initial preparation, restore,
reconciliation, final atomic checkpoint serialization/fsync, paged inventory
files, and small fixture durability checks execute normally. No 100,000-file
payload build or network simulation is implied.

- **100,000 fake one-byte immutable uploads**; interrupt after 50,000; restore
  from accepted preparation with no saved writes; reconcile all 50,000 bodies;
  replay them without a duplicate PUT; upload the remaining 50,000.
- 100,002 cloud journal events, **74,789,055 journal bytes**, 200,002 total fake
  PUTs (100,000 payloads and 100,002 journal objects), and **73,138,502 final state
  bytes**. The synthetic accepted binding is approximately the retained binding's
  size. The upload/recovery test took **11.078 seconds** in the final run.
- 97 counted periodic/final cache checkpoints during the large exercise, plus
  real initial/restore/reconciliation/final checkpoints. The old path would
  checkpoint every intent and verification (200,000 calls). This is a call-count
  result; the test does not measure full-production disk or network throughput.
- Worst completion ordering: **131,328 intents followed by 131,328
  verifications**, with 262,657 actual journal appends and **118,215,572 journal
  bytes**. It stays below both event and total-byte limits.
- Actual inventory writer/iterator: 100,000 synthetic asset references,
  **1,563 real inventory-page files**, **19,599,937 page bytes**, and 101,563
  enumerated references. Each reference has a valid content-addressed name.
  Payload references are metadata fixtures, not issued payload custody proofs.
  The separate publication-attempt fixtures exercise real issued file proofs.
- Count-ceiling checks accept 131,072 phase files / 131,328 writes, then reject
  the next file/write. Small boundary tests refuse event, journal, state and
  phase overflow before journal/payload mutation. Corrupted chain evidence at
  the end of the full-size prefix refuses without replacing the checkpoint.
  Existing tests retain changed-body/ETag, lost-acknowledgment, competing-runner,
  symlink, illegal-transition, and incomplete-read refusals.
- Peak process RSS reported during the final capacity run: **1,264,648,192
  bytes** (about 1.18 GiB). This includes fake remote objects, synthetic state,
  serialized checkpoints and corruption-test copies, not just runtime state.
  The bounded cloud restore still retains accepted raw events up to its journal
  limit in memory; this repair does not introduce a streaming journal format.

Final code checks:

```sh
PYTHONPATH="$PWD/packages/viewer_publication/src:$PWD/packages/congress_api/src:$PWD/packages/congress_shared/src:/tmp/ct-v6-index-test-deps" \
/Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest -q -s -p no:cacheprovider \
  packages/viewer_publication/tests/test_publication_capacity.py \
  packages/viewer_publication/tests/test_publication_state_bounds.py \
  packages/viewer_publication/tests/test_recovery_publication_continuation.py \
  packages/viewer_publication/tests/test_local_continuation.py
# 62 passed in 25.86s

PYTHONPATH="$PWD/packages/viewer_publication/src:$PWD/packages/congress_api/src:$PWD/packages/congress_shared/src:/tmp/ct-v6-index-test-deps" \
/Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest -q -p no:cacheprovider \
  packages/viewer_publication/tests/test_viewer_publication_attempt.py \
  packages/viewer_publication/tests/test_guarded_recovery_publication_client.py
# 51 passed in 20.15s

git diff --check
```

The unchanged baseline continuation suites passed 54 tests before editing.
An earlier combined run passed 112 tests; after adding the Unicode restore-byte
refusal check, the two final commands above establish **113 passing tests** on
final runtime/test sources. Logs: `/tmp/ct-capacity-final-checks.txt` and
`/tmp/ct-capacity-integration-checks.txt`.

## Workflow checkpoint integration

The sibling checkpoint code owns `resume.py`; it was not edited here. Its new
receipt needs a separate byte budget from the continuation file reader. The
measurement below uses the **real retained 9,641,711-byte input binding**, a
**4,351-byte representative v6 manifest result** from the maintained native
fixture, synthetic content-addressed phase names and exact identity field
shapes, and 256 auxiliary renderer/continuation files. It measures serialization
only; it does not qualify an accepted production preparation.

| Phase files | Auxiliary files | Preparation state bytes | Checkpoint receipt bytes |
| ---: | ---: | ---: | ---: |
| 101,563 | 256 | 27,521,245 | 29,990,409 |
| 131,072 | 256 | 32,714,829 | 35,892,209 |

A **64 MiB receipt ceiling** covers these modeled cases; **32 MiB does not cover
the count ceiling**. The continuation reader must independently admit the
runtime's **128 MiB** supported state ceiling. The workflow file-count ceiling
must include auxiliary files beyond the 131,072 accepted phase files: this model
has **131,328 total checkpoint files**. The actual renderer working tree can
retain additional intermediate/partial files, so its owner must count those
before choosing the final checkpoint file allowance. Do not equate the accepted
phase count with all checkpoint files.

Reproduction: `/tmp/ct-capacity-checkpoint-size.py` and
`/tmp/ct-capacity-checkpoint-size.json`. The manifest fixture path is
`/tmp/ct-v6-index-profile-ordinary/native-public/manifest.json`.

## Remaining limits and release boundary

This scoped commit changes only continuation capacity/accounting, focused tests,
and this evidence note. It does not own preparation checkpoints, workflow
supervision, renderer staging, timers, the SQLite lookup index, or raw guards.
Integrate those separately and rerun their checks at the resulting head.

A new accepted preparation is required because the maintained full-release
identity hashes `continuation.py`. Do not reuse an accepted artifact built with
other runtime bytes. A real full inventory, output count, preparation duration,
artifact transfer, cloud journal cost and production upload/resume remain
unmeasured. At 100,000 assets the maintained format still entails about 100,000
journal object PUTs plus payload PUTs and hundreds of thousands of small local
journal evidence saves; fewer full-state checkpoints do not remove that cost.

Historical boundary: the initial repair left local-only `LocalContinuation`
at 65,536 events and 256 MiB. The merged local recovery repair supersedes those
limits: `local.py:16–18` now permits 262,850 events and 512 MiB of history, with
checkpoint headroom, and shares the incremental state validator. See
[the final review](reviews-20261026/capacity.md) for current source and evidence.

## Follow-up: accept successful uploads without routine readback

The user explicitly changed upload acceptance: a successful service response is
sufficient, with at most bounded smoke tests. The earlier readback claims above
describe the capacity commit's original behavior. The follow-up removes GET/HEAD
verification after successful payload, metadata and journal PUTs, removes the
uploader's fallback download on success, and trusts recorded successes during
resume. It retains local prepared-file checks, original conditional requests,
protected-input guards, durable attempt evidence and bounded public gateway
smoke checks. The persisted `verified` flag/event now records an acknowledged
upload (or an uncertain request resolved from its exact bytes); it does not
claim a fresh remote-byte check. Network reads remain for uncertain outcomes,
condition collisions, required input/journal loading and explicit read-only
verification commands. No publication occurred while applying this policy.

The focused acknowledgment suite passed 153 tests and two subtests before the
last comment/native-upload expectation updates; the final integrated validation
is reported in the task result. A new success-path regression makes both GET
and HEAD fail if called, and proves a successful upload and its receipt can
complete without either. Existing lost-acknowledgment and competing-runner tests
continue to exercise exceptional reconciliation.
