# Recovery pipeline simplification

The goal is to make recovered documents appear in the viewer sooner, with fewer
repeated transfers and less memory, while keeping the source links and recovered
bytes correct. These changes are implemented in isolated checkouts. The existing
checkpoint-16 publication keeps its original pinned runtime until it exits.

## Work packages and evidence

| Task | Change | Check |
| --- | --- | --- |
| T1 | Persist publication phases and explicitly reconcile/resume; materialize an unchanged selected catalog | Interrupt after catalog, mappings, preparation, publication; reconcile lost acknowledgments; reject stale versions |
| T2 | One verified remote transfer receipt per immutable payload; six concurrent uploads | Count GET/PUT operations on actual publisher path, six-worker barrier, corrupted or forged receipt refusal |
| T3 | Bound active cloud queries; cheap immutable-write checks and fresh shared-commit checks | Unknown/slow cloud, changed pins/remote versions, lost lock, final freshness; independent review corrections applied |
| T4 | Compress missing bodies only; one maintained reconciliation/readiness command | Existing and missing body counts, current-version reuse, failed upload, readiness-to-import-to-publication seam |
| T5 | Keep baseline state in Arrow; append new rows; stream preservation comparisons | Values/types/nulls/nesting/multiplicity and row-group boundaries; 200,000-state memory probe |
| T6 | Maintained acquisition CLI, explicit configuration and dispositions | Account for all 45 skipped failures, exact process identity, exclusions, refusal, pagination |
| T7 | Immutable receipts, compact counters, frozen qualification cache; optional PDF preview | Interrupted reconstruction without re-fetch, one extraction per body/version, retained PDF and truncation probes |
| T8 | One local runner with absolute working directory, atomic status and actual child waits | Failure, explicit resume, PID reuse/reparenting, crash before dispatch evidence, common recovery lock |
| T9 | Coalesce unpublished sealed batches; preserve individual receipts | Combined body/URL coverage, no historical mapping resurrection, conflict refusal, bounded cadence CLI |
| T10 | Share one exact catalog pair validation with viewer preparation | Hash/semantic call counts and mutation/identity/validator invalidation |

Import measured 396,050,432 to 147,881,984 peak RSS bytes on the synthetic
200,000-state/1,525-addition probe (62.7% lower). Preservation measured 618,168,320
to 233,291,776 bytes (62.3% lower), trading 0.543 seconds for 1.783 seconds.
These are component results, not full-corpus runtime promises. Arrow baseline,
URL uniqueness state, and encoded output still occupy memory.

The retained 961-response acquisition example serialized about 4.65 GB when
rewriting every full prefix, compared with 9.07 MB for one final aggregate.
Receipts/cache/counters add linear writes; no physical-I/O speed claim is made.

## Operating sequence

Inputs are completed, qualified local receipts and an authoritative mapping
baseline. Select only unpublished batches; original receipts remain immutable.
Use `coalesce_corpus_recovery_batches.py` to seal a combined batch after 100
URLs or 900 seconds from the oldest ready batch. `--flush` explicitly seals a
smaller batch now. The command returns pending without creating a batch when
neither threshold is met. The existing ten-minute monitor supplies invocation;
900 seconds is a due threshold, not a measured end-to-end publication guarantee.

Run `reconcile_corpus_recovery_bodies.py` read-only against that combined batch.
It emits separate readiness and body-readback files, so sealed batch inputs do
not change. Pass its `--readiness` to both import and publication dispatchers.
A prior body proof can skip a new full GET only when its identity, current ETag,
and stored size agree. Unknown or changed bodies receive a full verification.

Run one import, verify its actual exit and preservation, then publish through
one dispatcher. Both dispatchers accept `--control-root` pointing to the same
primary checkout. All isolated runtimes must share that lock; a worktree-local
lock is not sufficient. Explicitly supply the existing R2 config path; never
copy credentials into plans or receipts.

`run_corpus_recovery.py prepare/run/status/reconcile/resume` replaces numbered
supervisors. A plan names absolute executable/cwd, pinned files, disk reserve,
and a separate supported resume command. It never restarts automatically.
Runner completion means child exit zero; publication completion additionally
requires the dispatcher's complete evidence, conditional remote selection,
public manifest/payload checks, and live viewer coverage. If dispatch identity
was not recorded, the runner refuses another launch rather than guessing.

Publication `--resume --execute` is explicit and requires its original
`continuation.json` and unchanged binding. It reconciles uncertain writes before
continuing and reuses accepted phase output. It does not adopt older ad hoc
runs or resume an incomplete SQLite computation automatically.

Use the new viewer runtime only after checkpoint-16 physically exits and its
current catalog/mapping/viewer readbacks pass. The replacement runtime starts
from the exact existing viewer runtime commit; only the reviewed publisher and
catalog-validation changes are overlaid. Acquisition/import improvements must
not silently replace catalog interpretation or naming data.

## Boundaries retained

- Exact original URL/body associations, deferred exclusions and receipt coverage.
- Conditional shared pointers, fresh ownership/input checks, one local writer.
- Rendered HTML remains marked as a rendered copy, not original archive bytes.
- Fresh mapping edits/deletions remain authoritative. Coalescing is not a
  consumed-batch registry; do not resubmit an old published batch as new.
- No extra recovery requests, spend, production restarts or code pushes occur
  merely because these local tests pass.

## Review and rollout state

The independent import, publication, and guard/runner/coalescing reviews are
retained under `docs/recovery/`. Acquisition review corrections are complete. The added source-record preparation
command uses explicit capture/alias inputs and binds transport timestamps to the
exact recovered source URL, body hash and length. Existing partial preparations
and incomplete catalog builds remain intact for diagnosis. Offline review is not
a live release claim. Current
production identities and any remaining rollout work belong in
`output/corpus-retry-20261015/current-continuation.json` in the primary checkout.


The next operational commands are saved in
[`next-batch-command-handoff.json`](next-batch-command-handoff.json). They combine
unpublished checkpoints 17 and 18 against the fresh mapping selected by
checkpoint 16, then reconcile bodies, import once, verify preservation and publish
once. The two dispatchers explicitly share the primary checkout's lock and
credential configuration. Their evidence directories and readiness file are
named in the handoff. The existing monitor will prepare each runner plan only
after its predecessor succeeds and all input files can be pinned.

The staged runtime is
`/Users/mikewolfd/.codex/worktrees/recovery-mvp-runtime/congressional-tech`,
commit `fcc65a635a0976399e901167aa31a1aecff8db6b`, based on the exact current
runtime commit `c361df34aa60f83877cd0c2e287a8d1410952ff1`. Its two viewer scripts
and new catalog-validation module are the only code overlays. The actual staged
packages and publisher passed a one-row materialization probe (269 files,
73,479 bytes). That probe establishes compatibility; it does not establish
full-corpus throughput or live publication.

Earlier Firecrawl probe/parallel results and two additional GovInfo packages
remain named, unconsumed work after the first coalesced batch. This refactor does
not mark those recovered files published or declare the remaining corpus complete.

The final integrated suite passed **175 tests and 7 subtests**. Evidence and code
hashes are recorded in [`execution-evidence.json`](execution-evidence.json).
Independent source-preparation review closed its initial timestamp finding, and
publication review confirmed that incomplete build evidence survives continuation
refusal. The active production run and all its pinned files remain unchanged.
