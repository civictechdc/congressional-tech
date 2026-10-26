# Workflow custody, Pages verification and initial renderer resume review

One correctness defect was confirmed in merged main: checkpoint verification
time was added back to the preparation budget. It is fixed separately in
`a7b4caca1146747664177e372175f49bd7b12aeb`. No additional actionable defect was
found in the traced custody, Pages gate or initial-resume paths.

**Reviewed main:** `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`.
**Reviewed correction:** `a7b4caca1146747664177e372175f49bd7b12aeb`.
**Base for merged changes:** `c466a45e09e27bde48ade12454f8b458c3643d21`.
**Method:** semi-formal code review, with explicit local execution requested by
the user. Source reasoning, fixture results and hosted evidence are distinguished
below. This is a focused review of the combined implementation, not an approval
of unrelated raw-source, GPO, YouTube or proposed architecture changes.

## Findings

### F1 — preparation can exceed its elapsed-job cutoff during checkpoint resume

- **Severity:** WARNING / P2; **category:** correctness; **status:** fixed.
- **Merged-main location:** `scripts/publication/prepare_workflow_resume.py:95`
  and `:104`. `run_preparation` calculated `remaining` before invoking
  `verify_checkpoint`, then passed the original duration to `process.wait`.
  The verifier makes GitHub metadata requests and hashes every saved file
  (`packages/viewer_publication/src/viewer_publication/resume.py:158` and `:185`).
  A large restored checkpoint therefore extends the intended 130-minute cutoff
  by however long verification takes, reducing the time reserved for quiescence,
  inventory and artifact upload before the 180-minute job limit
  (`.github/workflows/publish-filename-viewer.yml:75` and `:175`).
- **Reproduction:** with a 100-second job budget and a 70-second verification,
  the existing code passed 100 seconds to the child wait rather than 30. With
  110 seconds spent verifying, it still launched preparation. Both new regression
  cases failed on merged main before the fix.
- **Correction:** hold one absolute deadline, refuse launch if verification
  exhausted it, and subtract verification and process-launch time from the wait
  (`scripts/publication/prepare_workflow_resume.py:95`, `:108`, `:114`).
  The regression is
  `scripts/publication/tests/test_preparation_checkpoint.py:355`.
- **Verification:** the two cases pass after the correction; the complete focused
  workflow/checkpoint run passed 61 checks.

### O1 — hosted Pages remains blocked by the selected data version

This is an observed rollout prerequisite, not a newly identified code defect.
The retained log `/tmp/ct-merged-pages-failure-20261026.log` for exact-main Pages
run `40388067405` shows the built browser executing its worker and failing with
`Unsupported filename catalog version.` The failure occurs at the intended gate.
The initial connection-refused line is followed by successful server access and
worker execution, so it is not the terminal failure. The gate precedes Pages
artifact upload (`.github/workflows/deploy-pages.yml:106` and `:121`).

The coordinator reports the public selection remains v5 and filename publication
workflow `383614042` is manually disabled. I did not re-query those remote states,
enable a workflow, dispatch publication, move a pointer or deploy. A passing
hosted v6 publication and deployment are not established by this review.

## Patch summary and review boundaries

The combined source separates three stages: incomplete local preparation,
complete accepted preparation, and conditional publication. Workflow descriptors
and artifact metadata establish where saved bytes came from. Runtime input
bindings and output verification establish whether they may be reused. The
Pages gate independently executes the built/deployed worker against the actual
selected filename publication.

The initial renderer now retains SQLite stages through the production
`publication_cli.main → attempt.prepare → native.prepare_native_output →
publish_filename_viewer.publish_selected → filename_native.publish_selected`
chain. Initial preparation supplies a binding without requiring an existing v6
publication. Explicit upgrades retain their separate rendering-rule guard.
The forwarding is visible in `publication_cli.py:187`, `attempt.py:136`,
`native.py:103`, and `publish_filename_viewer.py:173` under
`packages/viewer_publication/src/viewer_publication/`.

I read the workflow/bootstrap/descriptor implementations, Pages scripts and
verifier, preparation and continuation implementations, renderer state and its
asset/task callers, and the relevant test bodies. I followed input identities,
private copies, transactions, completed-stage reuse, completion receipts and
publication custody. I did not re-audit unrelated parser policies or every
throughput implementation in the merged repository.

## Exploration notes

| Hypothesis before reading | Evidence inspected | Result and next check |
| --- | --- | --- |
| H1: artifact custody is distinct from semantic completion | Workflow steps, bootstrap and `resume.py` | Confirmed. Followed the runtime binding comparison and accepted-artifact gate. |
| H2: initial resume skips only committed tasks and checks retained bytes | `attempt.py`, `native.py`, `filename_native.py`, `filename_renderer_state.py` | Confirmed for the traced paths and exercised fixtures. Followed partial-copy, transaction and accepted-phase boundaries. |
| H3: Pages executes the actual worker and compares the selected publication | Pages workflow, built server helper, verifier, page session and tests | Confirmed. The hosted failure log independently shows actual built-worker execution. |
| H4: restoration time may be excluded from the cutoff | `run_preparation` computes the duration before `verify_checkpoint` | Confirmed with two failing deterministic cases; corrected in the separate fix commit. |

## Function trace

Paths below are relative to the repository. Publication module names refer to
`packages/viewer_publication/src/viewer_publication/`.

| Function or boundary | File:line | Input → output | Verified behavior |
| --- | --- | --- | --- |
| Workflow admission and dispatch | `.github/workflows/publish-filename-viewer.yml:88` | Optional descriptor → selected revision/route | Admission precedes checkout/setup; v1 accepted resume and v2 preparation resume use separate outputs. |
| `prepare` | `scripts/publication/prepare_workflow_resume.py:21` | Dispatch environment → safe scalar outputs and retained descriptor | Requires explicit dispatch/repository; v2 requires the original code revision; retains exact admitted bytes outside checkout. |
| `parse_resume_descriptor` | `resume.py:10` | ≤16 KiB JSON → validated descriptor | Rejects duplicate fields; v2 requires explicit preparation permission. Publication's caller uses the default refusal (`publication_cli.py:69`). |
| `verify_checkpoint` | `scripts/publication/prepare_workflow_resume.py:58` | Descriptor/tree/GitHub metadata → verified receipt | Rechecks repository, code revision, run and artifact metadata, then exact saved bytes. |
| `verify_preparation_checkpoint` | `resume.py:158` | Artifact metadata, run, local receipt/tree → incomplete receipt | Checks expiry, ID, digest, name, producer, workflow revision, original binding and exact file inventory; rejects publication writes. |
| `run_preparation` | `scripts/publication/prepare_workflow_resume.py:92` | Job start/environment → prepared, unchanged or checkpoint result | Owns outputs, enforces the corrected absolute cutoff, signals the group, requires quiescence, and refuses forced-stop acceptance. |
| `verify_completed_preparation` | `scripts/publication/prepare_workflow_resume.py:71` | Quiescent receipt/result pair → prepared result | Executes maintained `verify-prepared`; refuses a different producer. Complete pairs are not v2 checkpoints. |
| `require_incomplete_preparation` / `save_preparation_checkpoint` | `resume.py:110` / `:119` | Saved continuation/tree → incomplete receipt and artifact name | Requires renderer stages or an accepted `prepared` phase; complete pairs and pre-renderer diagnostic stops cannot be advertised as resumable. |
| `publication_cli.main` / `validate` | `publication_cli.py:117` / `:52` | CLI flags → prepare/verify/publish result | Preparation resume is independent of renderer upgrade; publication rejects v2 before constructing a client. |
| `attempt.prepare` | `attempt.py:48` | Fresh controls/catalog/native configuration → accepted local output | Re-reads source/viewer/recovery controls, checks snapshot selector and native execution files; only origin run fields are restored before exact binding comparison. |
| `Continuation.__init__` / `phase` | `continuation.py:140` / `:210` | Binding and optional saved state → exact-input phase reuse | Refuses binding drift. Reuses `prepared` only through an issued matching inventory proof. |
| `prepare_native_output` | `native.py:26` | Adopted snapshot and prior viewer → v6 manifest/recovery | Verifies retained v5/v6 controls; forwards initial resume and binding; recovery-only reuse keeps exact prior bytes. |
| Builder forwarding | `publish_filename_viewer.py:166` | Snapshot/options → native builder | Forwards binding, resume flags, timings, events and memory metrics. |
| `filename_native.publish_selected` | `filename_native.py:876` | Exact snapshot/requirements/binding → prepared manifest | Production binding enables retained state; rejects missing resume binding, changed rules or occupied fresh output. Finished state revalidates retained proof. |
| `RendererState.__init__` / `restore` | `filename_renderer_state.py:38` / `:129` | Bound SQLite and saved assets → verified asset identities | Requires existing stages on resume; compares canonical binding; completes recorded deletions and hashes retained assets before reuse. |
| `RendererState.run` | `filename_renderer_state.py:172` | Named task/action → saved or newly committed result | Reuses saved result; commits task result and asset records after action, rolls back on exception. No publication write occurs here. |
| `NativeComponents.prepare` | `filename_native.py:545` | Planned components/chunks → retained chunk/entry tasks | Registration, physical chunks and entries have distinct reusable tasks. |
| `NativeSourceAssets.render` | `filename_native.py:334` | Bound source route → retained source task | Route digest keys task reuse; source subtree inputs are also bound by the renderer. |
| `ViewerAssets.put_file` / `put_node` | `filename_native.py:24` / `:52` | Complete bytes → addressed asset/reference | Existing destinations are hash-checked; retained copies use the private partial directory and remember complete identities. |
| `RendererState.publish_asset` | `filename_renderer_state.py:108` | Source/identity → complete destination | Uses `copy_checked` with exclusive publication and private staging. |
| Final renderer acceptance | `filename_native.py:1003` | Serving roots → manifest/inventory/finished task | Validates roots/counts, removes owned unreachable assets, retains final manifest and finished result. |
| `attempt.verify_prepared` | `attempt.py:214` | Receipt, complete publication, phase → verified preparation/plan | Checks code/runtime/policy/source, exact membership, every issued file identity, receipt digest and producer-derived result. |
| `attempt.publish` | `attempt.py:323` | Verified preparation and GitHub artifact → guarded publication | Artifact producer must match receipt producer; protected versions are checked before journal/publication and shared selection (`:357`). |
| Built/deployed Pages gate | `.github/workflows/deploy-pages.yml:106` / `:144` | Built site/current pointer → worker observation | Runs before Pages upload and after deployment, retaining observations and failures. |
| Built server helper | `.github/scripts/verify-built-filename-worker.sh:4` | Actual Astro `dist` → localhost Pages base | Serves the real build at its configured base; trap closes its server. No fake catalog replaces the public selection. |
| Browser setup | `.github/actions/setup-publication-browser/action.yml:9` | Exact Playwright version → Chromium/library path | Installs pinned `1.64.1`, matching headless browser and dependencies. |
| `verifyLivePublication` | `apps/site/scripts/verify-live-publication.mjs:22` | Selected pointer/pages/reviews → observation | Pins one pointer, bounds HTTP, verifies native roots/recovery/reviews and invokes browser execution. |
| `browserRuntimeProbe` / `requireNativeWorker` | `apps/site/scripts/verify-live-publication.mjs:280` / `:354` | Page worker `/api/info` → compatibility/gate result | Requires v6, executed worker success, matching catalog/generation/review/recovery; compares the full built/deployed pointer. Browser closes on failure. |
| Page worker caller | `apps/site/src/components/explorer/reader/filenames/session.ts:31` | Configured public manifest/review descriptor → actual worker API | Mounts the worker with public selection and exposes `filenameViewerApi`; verifier calls that API. |

## Data flow and invariants

1. **Origin versus producer.** `attempt.py:57` creates the binding; `:95` restores
   only origin run fields, and `Continuation` compares every other field before
   rendering. `attempt.py:179` chooses the current artifact producer for unfinished
   preparation, while an already completed receipt/result pair keeps its identity.
   `:185` persists that producer and `:241` derives the verified result from it.
   Artifact custody checks that producer at publication (`:329`). Rebinding a
   completed pair to a newer upload would break this property; both checkpoint
   admission and stop-boundary acceptance reject that route.
2. **Saved bytes versus completion.** The checkpoint hashes the complete local
   tree (`resume.py:88`) and binds that inventory into a separately named incomplete
   receipt (`:131`). It retains working SQLite/private partials but never creates
   a complete preparation phase. Only `attempt.verify_prepared` can issue complete
   verification; workflow acceptance/upload/publication require `prepared`
   (`publish-filename-viewer.yml:202`, `:221`, `:224`).
3. **SQLite atomic units.** Renderer binding is canonical and immutable across
   resume (`filename_renderer_state.py:58`). Asset identities and task results
   commit together in `run`; exceptions roll back the current transaction
   (`:180`). Nested completed chunk/source tasks may survive an interrupted outer
   stage. `restore` validates those bytes before cached results are returned.
   Copy partials remain outside publication and completed existing destinations
   are independently hash-checked (`filename_native.py:35`, `:71`).
4. **Accepted phase reuse.** Once `prepared` is accepted, `attempt.py:154` verifies
   its saved inventory and `Continuation.phase` returns its result without
   rebuilding. Before that point, renderer finished state skips rendering, but
   recovery may be repeated (`native.py:110`). Tests explicitly distinguish these
   two cases rather than claiming recovery-row checkpoints.
5. **Mutable inputs.** Source/catalog/control/native input checks precede reuse
   (`attempt.py:53–97`); native execution files are required again before output
   acceptance (`:142`). Existing runtime/configuration paths remain exact bindings
   (`packages/docspec_client/src/docspec_client/client.py:299`). Source-file
   identity includes bootstrap, validator, renderer and preparation owners
   (`release_identity.py:28–50`). Publication checks protected versions again.
6. **Real worker qualification.** The verifier's maintained loader and browser
   worker must agree on source/recovery/review identities, and built/deployed
   pointers must match (`verify-live-publication.mjs:130`, `:327`, `:354`). This
   qualifies worker startup and `/api/info`, not every browsing/search/detail
   interaction or a new data publication. A changed pointer fails closed; a
   post-deployment failure does not roll back Pages.

## Tests and concrete boundary cases

All test assertions below were read. Executed outcomes are listed afterward.

| Test / file:line | Boundary and assertion trace | Assessment |
| --- | --- | --- |
| `test_checkpoint_verification_consumes_the_elapsed_job_budget`, `scripts/publication/tests/test_preparation_checkpoint.py:355` | Clock advances during restore; child receives 30/100 remaining seconds, or launch is refused after 110/100. | Two reproduced failures on reviewed main; both pass with fix. |
| `test_real_subprocess_stop_artifact_round_trip_and_explicit_restore`, same file `:184` | Real subprocess/SQLite stop → archive/restore → second producer stop → third producer completion; original and producer IDs differ correctly. | Pass; fixture CLI proves supervisor behavior, not production semantic completion. |
| Completion and race tests, same file `:264`, `:277`, `:286` | Complete pair at SIGINT, zero exit, vanished process, old producer and corrupt output → verified preparation or refusal, never incompatible v2 acceptance. | Pass. |
| Pre-renderer/complete-pair checks, same file `:315`, `:324`, `:335` | Missing stages fail diagnostic-only; complete pairs cannot be v2; accepted phase permits receipt completion without rendering. | Pass. |
| Descriptor/custody tests, same file `:57`, `:75`, `:91` | V2 stays preparation-only; changed metadata, original identity, bytes and file set fail. | Pass. |
| Initial chunk/source interruption, `packages/viewer_publication/tests/test_filename_initial_resume.py:19` | Stop before/after committed task; completed native pins are not read again; repeated resume is stable and selector unchanged. | Pass. |
| Initial stale inputs/corruption, same file `:46` | Changed source/config/reviews/compression/prior binding or same-size corrupted asset fails before native chunk reads. | Pass. |
| Initial CLI abrupt exit, same file `:79` | `os._exit(73)` leaves private checkpoint; new run resumes and emits new producer identity. | Pass. |
| Real-native initial/upgrade abrupt exit, `packages/viewer_publication/tests/test_filename_native_upgrade.py:97` | Private real-native workspace; stop before/after chunk; no completed pin rereads or new native candidates during rendering; source selector unchanged. | Four cases pass after granting localhost access. |
| Private copy windows, same file `:149` | Abrupt loss during copy, before link and after link for node/file; no publication partial; resumed bytes match. | Six cases pass. |
| Split occurrence asset loss, same file `:203` | Loss after an occurrence asset; resumed output retains required inventory/membership, creates no native tables, repeated resume reads no inputs. | Pass. |
| Producer and v5 withdrawal behavior, `packages/viewer_publication/tests/test_viewer_publication_attempt.py:646` | Current producer receives newly completed artifact; original binding and historical withdrawal remain; repeated accepted resume does not rebind. | Pass. |
| Stale native/control and acceptance boundaries, same file `:721`, `:752`, `:796` | Changed runtime/control fails before reads; recovery/prepared-phase/receipt/result boundaries preserve their correct producer/reuse rules; legacy receipts retain identity. | Pass. |
| Fresh/recovery reuse, `packages/viewer_publication/tests/test_native_preparation.py:65`, `:78`, `:108`, `:123` | Qualified prior assets reused; recovery-only preserves exact bytes and occupied output; corrupt prior input fails before reads. | Pass. |
| Workflow admission/historical paths, `scripts/publication/tests/test_workflow_resume.py:111`, `:133` | Exact selected checkout precedes setup; actual workflow shell selects current/historical paths. | Pass. |
| Pages ordering, `.github/tests/test_pages_dependencies.py:49` | Built gate must precede artifact upload; deployed gate follows deployment and receives built pointer observation. | Pass. |
| Verifier native gate, `apps/site/scripts/verify-live-publication.test.mjs:28`, `:48`, `:118`, `:135` | V5, pending/failed worker, pointer/generation/recovery/review mismatch rejected; browser closed on each result. | Pass with fixtures; hosted evidence separately shows actual worker execution/failure. |

## Executed evidence and limits

- **61 workflow/checkpoint checks passed in 11.12 seconds** after the fix. This
  includes the new failing-before/passing-after budget cases, real subprocess
  interruption and fake-artifact custody checks.
- The independent renderer/publication/Pages command covered
  `test_filename_initial_resume.py`, `test_filename_native_upgrade.py`,
  `test_native_preparation.py`, `test_viewer_publication_attempt.py` and
  `.github/tests/test_pages_dependencies.py`. It produced **91 passes and four
  environment failures**: sandbox denial of the local DocSpec helper's loopback
  listener (`Operation not permitted`). Only those four real-native cases were
  rerun with localhost permission: **4 passed, 12 deselected, 22.00 seconds**.
  Thus all 95 selected cases passed across those invocations; this is not a claim
  of one clean full-suite invocation.
- **21 JavaScript verifier checks passed** with Node `22.22.2`. A temporary
  dependency link in this isolated worktree was removed afterward. No primary
  checkout file was modified. Python checks used `3.12.9`, existing dependencies
  and the prior `/tmp` test parser dependencies; the unrelated installed
  Pydantic/Logfire warning remained. The four native fixtures used the maintained
  binary at the primary checkout's `.cache/docspec-catalog/docspec-remote`, read
  as an executable, with new private temporary workspaces.
- The coordinator's broader logs record 723 publication/workflow tests plus two
  subtests, 235 data checks and 154 JavaScript checks on reviewed main. I did not
  rerun or promote those supplied results into independent evidence for this fix.
- Hosted Pages log evidence is a negative gate result on reviewed main. No hosted
  run tested the new deadline fix, and no passing v6 selection or deployed
  worker result is claimed. I did not run a full catalog build or mutate remote
  data, workflow settings, publication pointers or deployment state.
- Git checks pass. The backup ref is
  `codex/backup-workflow-pre-review-20261026` at
  `4860eb2ba28ab60d71aca30e28a5978f1de76d4e`. The task branch was rebased directly
  to the exact main SHA, dropping its already-integrated changes. No old
  superseded changes were reintroduced.

## Verdict

**VERDICT on reviewed main: REQUEST CHANGES** for F1.

**VERDICT with `a7b4caca1146747664177e372175f49bd7b12aeb`: APPROVE** for this
review's custody, initial-resume and Pages-gate scope.

The code now retains one elapsed-job cutoff through checkpoint verification.
The traced runtime preserves exact input and retained-asset checks, reuses only
committed work and keeps completed preparation identity separate from checkpoint
origin. The Pages gate correctly refuses the currently incompatible selection.
Coverage is **ADEQUATE** for these paths; confidence is **HIGH** in the bounded
source/fixture conclusion. Hosted v6 publication and successful deployment remain
unverified prerequisites, not conditions this local review has completed.

## Final merged-source delta review

**Final reviewed source:** `6183938fcb2b0842d5e1f59072383aa7dd251d32`.
**Delta reviewed:** `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f..6183938fcb2b0842d5e1f59072383aa7dd251d32`.
**Final verdict: APPROVE** for this report's workflow custody, initial renderer
resume and Pages-gate scope. No unresolved source finding remains in that scope.

The original report above is preserved as historical review evidence. The final
source includes its required deadline correction as
`a82cfb55e45310dc359c4b501cdcc77d23d6e388`. I compared stable Git patch IDs against
the original `a7b4caca1146747664177e372175f49bd7b12aeb`; they match. The owned branch
was rebased onto final main with the original source fix dropped and the report
preserved as `afa3166b558a85c0ab4e8be16c1391e136f4335f`. No duplicate source patch
was replayed. Before rebasing, the prior review tip was retained in
`codex/backup-workflow-final-review-20261026` at
`fafdbeb99683a015b472dee074b3747df6238c43`; the earlier backup also remains.

Only the relevant new delta was examined:

| Change and trace | Review result |
| --- | --- |
| `release_identity.source_files`, `packages/viewer_publication/src/viewer_publication/release_identity.py:31` and `:41–43` | Now includes all maintained DocSpec client Python sources, publisher implementations and constants. The existing stat-based cache recomputes hashes when those files change (`:58–70`). This strengthens the code/runtime binding used by `attempt.prepare` and `verify_prepared`; it does not create a path around stale-input rejection. The parameterized regression changes each included file and requires a different identity (`packages/viewer_publication/tests/test_release_identity.py:49`). |
| Absolute deadline in `scripts/publication/prepare_workflow_resume.py:95`, `:108`, `:114` | Identical to the separately reviewed correction. Restoration and process-launch time consume the original budget, and exhausted verification refuses a new producer. Both deadline regressions remain present (`scripts/publication/tests/test_preparation_checkpoint.py:355`). |
| Occurrence writer admission, `packages/viewer_publication/src/viewer_publication/filename_exports.py:346`, `:390`, `:417` | Counts retained row/list bytes, refuses an oversized single row, flushes before adding a row that would exceed the pending-byte budget, and resets the byte count after flushing. Row-order counters and per-parent slices remain independent of new row-group boundaries. This bounds retained pending rows; it does not claim a complete process-heap bound while Arrow builds a table. |
| Writer callers, `filename_exports.py:451` and `packages/viewer_publication/src/viewer_publication/filename_native.py:296` | Both the standalone and combined renderer paths pass the same policy and metrics. Failed admission exits before addressed occurrence assets are accepted (`filename_native.py:299–305`). Regressions check ordering, slices, byte-bound metrics, single-row refusal and absence of accepted assets in both paths (`packages/viewer_publication/tests/test_filename_observations.py:343`, `:368`). |

The Pages workflows/gate and renderer transaction/attempt state machines have no
additional changes in this delta. The raw-capture cache/hash and GPO timestamp
repairs belong to other reviewers; they were not re-audited here. Their changed
Python source remains covered by the existing application-source fingerprint.

Independent final-delta execution selected only the six source-fingerprint
variants, four standalone/combined occurrence-bound cases and two deadline cases:
**12 passed, 71 deselected, 1.58 seconds**. The same unrelated installed
Pydantic/Logfire warning remained. No broad suite or full catalog build was
repeated. The coordinator's supplied follow-up logs were read and record
264 cross-cutting Python checks, 126 renderer/native checks and 154 JavaScript
checks; those are focused follow-ups and are not summed with earlier results.

The coordinator reports that publication is still manually disabled and Pages
continues to refuse selected v5 data. I made no operational change or fresh
remote-state claim. The requested source merge/review work is complete; a
successful v6 publication and deployed-worker result remain separate rollout
evidence. No further source fix is requested by this final delta review.
