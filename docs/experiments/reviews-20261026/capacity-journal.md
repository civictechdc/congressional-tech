# Merged journal and local status review — 2026-10-26

## Findings and verdict

**APPROVE within this scope. No blocking correctness finding.** The combined
cloud journal, shared local evidence, local event replay and status capacity port
preserve their recovery responsibilities. Successful uploads remain accepted
without routine GET/HEAD requests. Uncertain requests require reconciliation;
cloud appends retain nonce-based competing-runner fencing. No code fix was needed.

Reviewed exact source: `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`, including
integrated commits `37e481bc`, `072b1a7b`, `1318d96e` and `d36564b1`. The
coordinator owns the main client/reconciliation/capacity review; those functions
were read here to trace this boundary. This review was static. No tests or
production work ran. The coordinator's reported 723 publication/workflow, 235
data and 154 JavaScript passing checks are separate execution evidence, not new
results from this review.

**Observation — tests establish different properties.** The 100,000-upload cloud
fixture counts local evidence operations instead of performing every file sync;
the local 66,001-record fixture disables file syncs. Focused journal tests use
real file writes and exercise sync failures. These do not measure a complete
production release's disk cost. See
`packages/viewer_publication/tests/test_publication_capacity.py:74`, `:93`, `:98`, `:110`, `:264`;
`packages/viewer_publication/tests/test_local_continuation.py:30`;
`packages/viewer_publication/tests/test_publication_state_bounds.py:49`, `:166`.

## Patch summary and exploration

The merged work coordinates count/byte limits, admits one write transition without
copying the ledger, gives the accepted event a second name for its synced request
file, and lets status inspect the same-sized receipts as recovery. `local.py` now
participates in release source identity
(`packages/viewer_publication/src/viewer_publication/release_identity.py:44`).

Three hypotheses guided the review:

- Cloud state might advance before recoverable evidence exists. **Refuted:** the
  nonce-bound request is saved before conditional PUT; accepted linking precedes
  sequence/digest/byte advancement (`continuation.py:538`, full path below).
- Removing local ledger copies might expose partially applied state. **Refuted:**
  validation precedes append/sync; live writes and the existing versions map change
  afterward under the lock (`local.py:122`).
- Status might retain small limits or grant recovery authority. **Refuted for the
  changed paths:** it shares the limits, reads local events without constructing a
  continuation, and reports integrity/reconciliation as unchecked
  (`scripts/publication/pipeline_status.py:113`).

## Function trace

For this section and the invariant references below, `continuation.py` means
`packages/viewer_publication/src/viewer_publication/continuation.py`; `local.py`
means `packages/viewer_publication/src/viewer_publication/local.py`; `client.py`
means `packages/viewer_publication/src/viewer_publication/client.py`; `custody.py`
means `packages/congress_shared/src/congress_shared/custody.py`. All line numbers
refer to the reviewed SHA.

| Function | File:line | Inputs → outputs and verified behavior |
| --- | --- | --- |
| `attempt.publish` | `packages/viewer_publication/src/viewer_publication/attempt.py:323` | Accepted preparation/artifact → result. Restores journal before reconciliation/guards; sends events through `journal.record`; records completion before saving result. |
| `DurableJournal.__init__` | `continuation.py:423` | Attempt/binding → fenced writer. Fresh start refuses an existing first event; resume reads the prefix. |
| `DurableJournal.record` | `continuation.py:514` | Event → append/local state. Keeps at most one pending acknowledgment, joins it into the next append, periodically saves derived JSON. |
| `DurableJournal._append` | `continuation.py:538` | Event/optional acknowledgment → immutable nonce-bearing event. Checks limits, saves request, conditionally uploads, links acceptance, then advances. |
| `DurableJournal.restore` | `continuation.py:448` | Bounded remote prefix → reconstructed writes. Validates sequence, chain, nonce, binding, transitions and size before changing local evidence/checkpoint. |
| `Continuation.save` / `accept_saved` | `continuation.py:180`, `:195` | Bytes → saved file/custody receipt; unchanged request → accepted hard link. Refuses escaping paths, changed custody and conflicting evidence. |
| Shared atomic writer / custody | `packages/congress_shared/src/congress_shared/custody.py:188`, `:119` | Bytes → synced atomic file receipt; receipt/path → process-local identity check. Link acceptance needs no second payload read/file sync. |
| `write_transition` / `checked_event` | `continuation.py:99`, `:265` | State/event → one proposed write and exact serialized size. Admission does not mutate the live ledger. |
| `LocalContinuation._append` / `record` | `local.py:83`, `:122` | Event → synced record, then one write/version change. Write/sync failure blocks further use until explicit resume. |
| Local `flush` / `_restore` | `local.py:112`, `:106` | State → authoritative snapshot then derived JSON; history → state/sequence/digest/bytes. |
| `read_local_journal` | `local.py:29` | Bounded history → validated state and inspection totals. Replays into unpublished state, refuses current partial/corrupt history, writes nothing. |
| Local dispatcher / domain phases | `scripts/corpus_recovery/dispatch_corpus_recovery_publication.py:334`; `packages/corpus_recovery/src/corpus_recovery/publication.py:71` | Owned locked run → local continuation and guarded catalog/mapping/prepared/publication phases. |
| Continued replay | `client.py:253`; `continuation.py:389` | Original condition and same local bytes → recorded ETag. Changed condition/bytes refuse; accepted reuse requires no remote read. |
| Status reader / callers | `scripts/publication/pipeline_status.py:113`, `:211`, `:286` | Receipt/events plus expected run → observation. Shared bounds and identity checks precede attribution; invalid receipt becomes an issue. Ordinary status does not resume/write. Explicit publication verification remains separate. |

## Data flow and invariants

| State/fact | Creation, changes, use and boundary |
| --- | --- |
| Request bytes, nonce, custody | `_append` creates exact bytes/unique nonce; `save` syncs them before PUT. The returned process-local receipt checks the unchanged file before linking. It is not serialized as recovery authority (`continuation.py:543`, `:555`; `custody.py:119`). |
| Cloud sequence, digest, total bytes | Advance after conditional acceptance/local linking; restore derives them from the valid prefix. Gaps, malformed nonce or joined acknowledgment refuse (`continuation.py:489`, `:497`, `:511`, `:558`). |
| Pending acknowledgment | At most one dictionary; next intent/completion carries it. Consecutive acknowledgments append the older fact. Crash before joining leaves an uncertain remote intent, so that object requires reconciliation (`continuation.py:517`). |
| Live local writes/versions | Admission proposes one change; append/sync happens before mutation. The versions map retains its identity for guards. Restore changes private state and advances a protected version only on acknowledgment (`local.py:57`, `:126`, `:135`). |
| Local bounds | 262,850 records; 512 MiB total; snapshots ≤128 MiB +1,024 bytes; normal records ≤1 MiB. Derived count/byte budgets apply independently on read and append (`local.py:16`, `:35`, `:89`). |
| Accepted vs uncertain upload | A successful PUT ETag yields acknowledgment without GET/HEAD; failed-request reconciliation reads once without resending. Replay retains original conditions/bytes. Distinct journal nonces fence same-valued competing events (`client.py:182`, `:194`, `:253`; `continuation.py:543`). |
| Status output | Local event state feeds recorded counts. Integrity, remote reconciliation and public readback remain explicitly unchecked; output is never write authorization (`scripts/publication/pipeline_status.py:119`, `:138`, `:205`). |

Cloud restore builds a new writes map and publishes it after full-prefix validation
(`continuation.py:468`, `:509`). Local restore reconstructs private complete state
from snapshots/events (`local.py:46`, `:65`). Callers select the authority; these
paths do not substitute for each other.

## Test behavior and concrete edge cases

All entries are **expected to pass by the inspected static trace**, not new
execution claims. Assertions and exercised branches were read.

| Test / file:line | Expected behavior and concrete risk covered |
| --- | --- |
| `test_journal_acceptance_reuses_synced_request_bytes`, `packages/viewer_publication/tests/test_publication_state_bounds.py:49` | Twenty intents sync before PUT; twenty saves/syncs retain two names per inode. Covers the intended I/O reduction. |
| `test_journal_interruption_preserves_request_and_resumes`, same file`:85` | Before PUT, after commit and accepted-link interruptions leave sequence unchanged; explicit restore never repeats PUT. |
| Local evidence corruption tests, same file`:127`, `:150`; sync failure test`:166` | Linked corruption refuses on restore; a changed request fails custody before acceptance; failed sync prevents remote mutation. |
| Competing runner tests, `packages/viewer_publication/tests/test_viewer_publication_attempt.py:280`, `:303` | Conditional conflict refuses; ambiguous acknowledgment cannot adopt another runner's different nonce despite identical event values. |
| Joined acknowledgment tests, `packages/viewer_publication/tests/test_publication_state_bounds.py:304`, `:324`, `:340`, `:360`, `:380`, `:395`, `:417`, `:433` | One pending fact, crash before joining, failed append, malformed value, lost acknowledgment, byte refusal and accepted reuse follow the stated transitions. |
| Point lookup / count tests, `packages/viewer_publication/tests/test_local_continuation.py:17`, `:30` | Iteration-refusing ledger accepts intent/acknowledgment; 33,000 paired writes exceed the old event limit and restore identically. The scale test mocks syncs. |
| Local failure/recovery tests, same file`:46`, `:71`, `:121`, `:147`, `:169`, `:190`, `:199`, `:224`, `:246` | Missing JSON, uncertain/accepted outcomes, Unicode size deltas, partial/corrupt history, sync/checkpoint failures, limit refusal and shared versions identity retain expected behavior. |
| Local caller integration, `packages/corpus_recovery/tests/test_accepted_viewer_plan.py:143` | After public smoke failure, the local journal and original plan resume without rebuild or duplicate immutable payload PUTs. |
| Status capacity tests, `scripts/publication/tests/test_pipeline_status.py:218`, `:230` | >2 MiB /12,000-write receipt now inspects without mutation; above-shared-limit count refuses. |
| Local status tests, same file`:259`, `:283`, `:297` | Fresh intent appears despite stale/missing JSON; current partial history refuses; legacy fallback labels event state stale/unknown; reconciliation observations grant no authority. |
| Workflow selection, `scripts/publication/tests/test_workflow_resume.py:103`; `.github/workflows/publish-filename-viewer.yml:131` | Current workflow selects capacity/local-journal tests; historical accepted code may omit the listed newer checks. |

Residual boundaries: hard-link support is required within the attempt directory;
link failure retains request/cloud evidence for explicit recovery. Evidence saves
retain the existing directory-sync policy; power-loss persistence beyond those
guarantees is not established (`continuation.py:187`, `:205`). Complete production
output, real R2 transfer and production resource qualification are outside this
static review.

**VERDICT: APPROVE.** Coverage of changed recovery/status paths: **ADEQUATE**.
Confidence: **HIGH** for traced transitions/fencing; production performance is
unqualified. No fix commit or remote write was made.

## Final source delta review

**Final reviewed source: `6183938fcb2b0842d5e1f59072383aa7dd251d32`. Final
verdict: APPROVE for journal, local recovery, status and producer identity.** This
addendum reviews only the relevant `ad222085..6183938f` changes; it does not repeat
the preceding audit or claim production qualification. No source fix or test
execution was needed.

The delta changes none of `continuation.py`, `local.py` or
`scripts/publication/pipeline_status.py`. Their earlier review therefore still
applies. Its producer identity change is commit `c4326f58`: `source_files` now
includes the maintained publisher modules, publication constants and all Python
modules in `docspec_client`. The following references use the final source SHA.

| Trace | Final source evidence | Review result |
| --- | --- | --- |
| Existing source closure → additional files → relative-path/digest map | `packages/viewer_publication/src/viewer_publication/release_identity.py:20`, `:31`, `:41` | The recursive native-client enumeration and explicit publisher paths enter the same sorted set and custody/hash pipeline; no second identity implementation is introduced. |
| File facts → cache check → hash → after-read custody check | Same file`:57` | The added files participate in cache invalidation and the existing changed-during-hashing refusal. The returned dictionary is a copy. |
| Shared source map → runtime implementation digest | `packages/viewer_publication/src/viewer_publication/publish_viewer_r2.py:121`, `:126` | The publisher calls the maintained `source_files` implementation and hashes its encoded map. |
| Shared source map → early preflight implementation digest | `scripts/publication_preflight.py:340`; `scripts/viewer_release_identity.py:12` | Preflight uses the same source owner through the existing shim, so it receives the expanded closure too. |
| Added path → digest → cached equality → changed source digest | `packages/viewer_publication/tests/test_release_identity.py:41`, `:49` | The six-case parameterized test asserts each maintained path is included and changing its bytes changes identity; expected to pass by static trace. Existing import-order test at `:15` checks package/shim ownership. Tests were read, not rerun. |

No new blocking finding. The change closes a producer-source identity gap while
preserving the reviewed journal/recovery behavior. Remaining transfer/resource and
hard-link boundaries are unchanged from the preceding review.

## Final closure

Final source SHA: `0cde0d348dce0c5eae714a7199b54839dab8bc23`.
**VERDICT: APPROVE, unchanged for this review's scope.** The delta from `6183938f`
only changes the bounded Parquet smoke read in `publish_viewer_r2.py` and its
viewer R2/native-upload tests, outside the journal/local/status/producer
identity review. Per the closure instruction, no audit or test expansion was
performed. The report-only commits were rebased onto this exact source.
