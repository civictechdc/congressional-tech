# Capacity and inventory review, 2026-10-26

## Findings and decision

**No blocking correctness finding in the reviewed scope. APPROVE.** The combined
code preserves fresh file verification after restore, binds plan values before
upload, accepts successful upload acknowledgments, and keeps incomplete
preparation and status observations separate from publication acceptance.

Reviewed commit: `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`.
This is a static review of the merged inventory/capacity flow and its immediate
initial-resume, local-journal, and status callers. It is not a review of every
feature in that commit or a production qualification. No code fix was required.

**OBSERVATION O1 — capacity is bounded and shape-dependent, not a guarantee for
any 131,072 arbitrarily large names or values.** The count bounds are independent
of serialized byte bounds (`continuation.py:22-33,67-96,265-289`). The maintained
large fixture deliberately replaces per-event filesystem saves/checkpoints with
counters, while executing real transition, fake-client upload, restore, and replay
paths (`test_publication_capacity.py:74-150`). Its 100,000 synthetic payloads and
100,000-reference inventory tests establish different properties; they do not
represent a full current native-catalog preparation. This limitation is explicit
in the tests and requires no code change.

**OBSERVATION O2 — one local recovery caller retains two directory walks.** The
saved-phase branch of `corpus_recovery/publication.py:57-64` still runs the size
validator and its own membership traversal. The hosted attempt flow now reuses
the validator's returned membership (`attempt.py:219-227`). The local branch
preserves correctness and does not invalidate the hosted improvement; its extra
walk is a remaining performance opportunity, not a release blocker. No additional
cleanup was made during this review.

Path abbreviations used below:

- `P/`: `packages/viewer_publication/src/viewer_publication/`
- `T/`: `packages/viewer_publication/tests/`
- `C/`: `packages/congress_api/src/congress_api/retention/`
- `S/`: `scripts/publication/`
- `R/`: `packages/corpus_recovery/src/corpus_recovery/`

## Patch summary and checked hypotheses

The merged change removes immediate full-inventory revalidation at issuance and
reissuance solely for plan metadata. It shares one directory census between size
admission and hosted prepared-output membership checks. Coordinated limits admit
a modeled full first release, with incremental exact JSON size admission and
periodic derived checkpoints (`C/viewer_inventory.py:48-110`, `P/plan.py:35-67`,
`P/attempt.py:214-255`, `P/continuation.py:22-33,249-304,514-561`).

Before reading the implementations, the review used these hypotheses:

| Hypothesis | Evidence motivating it | Result after tracing |
| --- | --- | --- |
| H1: rebinding plan metadata could bypass file freshness | `bind_context` no longer walks files | Refuted: acceptance requires inventory custody first; later plan use and individual transfers recheck it (`P/plan.py:48-66,28-32`, `P/publish_viewer_r2.py:465-473,506-517`). High confidence. |
| H2: sharing the size census could miss changed membership | hosted verifier removed its second `rglob` | Refuted for the maintained sequential flow: the returned complete name set is compared with the receipt; every accepted file is then verified or custody-checked (`P/publish_viewer_r2.py:83-100`, `P/attempt.py:225-238`). This introduces no filesystem snapshot or stronger concurrency guarantee. High confidence. |
| H3: initial resume might reuse incomplete or differently bound work | renderer state now survives initial adoption | Refuted: original binding is required before renderer work; retained assets are hashed; only an accepted phase may skip preparation; completed receipt/result identity remains fixed (`P/attempt.py:88-97,154-209`, `P/filename_renderer_state.py:58-67,129-147`). High confidence. |
| H4: raised capacities might leave local restore or status on smaller old bounds | local and status routes inspect the same state | Refined: local limits derive from continuation limits; workflow continuation/receipt readers allow 128 MiB and auxiliary files; status uses maintained state/event/journal bounds (`P/local.py:16-18,29-68`, `P/resume.py:68-85`, `S/pipeline_status.py:113-208`). Shape limits remain independent. High confidence. |
| H5: reconciliation progress might become replay authority | new latest-observation file is read by status | Refuted: recovery ignores that file; it is bounded and binding-checked for display only, with authority flags forced false (`P/continuation.py:341-409`, `P/reconciliation.py:27-84`, `S/pipeline_status.py:144-151`). High confidence. |

## Function traces

| Function or method | Location | Input → output | Verified behavior and immediate caller/callee |
| --- | --- | --- | --- |
| `verify_inventory` | `C/viewer_inventory.py:78` | receipt file facts → issued inventory | Hashes every file, compares byte/hash facts, then issues proofs; called by restored `verify_prepared` and local `prepare_viewer`. |
| `issue_inventory` | `C/viewer_inventory.py:93` | issued file proofs → inventory | Rejects invalid paths/plain dictionaries and checks each proof once; called during preparation and by `verify_inventory`. |
| `_require_authority` | `C/viewer_inventory.py:41` | root/facts/context → refusal or continuation | Requires issued object identity, current validator/process, root, optional facts and binding. |
| `InventoryValidation.require` | `C/viewer_inventory.py:48` | inventory → same checked object | Compares all facts to proofs and calls each `VerifiedFile.require`. |
| `InventoryValidation.bind_context` | `C/viewer_inventory.py:57` | issued inventory + plan context → newly registered context view | Reuses the same file facts, authenticates the source object; grants no new file freshness. |
| `InventoryValidation.file` | `C/viewer_inventory.py:68` | requested path + optional facts → file proof | Requires inventory authority, coverage, expected facts and exact file custody. |
| `AcceptedViewerPlan.context` | `P/plan.py:22` | plan values → canonicalizable context | Includes source pins, conditions, release plan, recovery, manifest and file paths. |
| `AcceptedViewerPlan.require` | `P/plan.py:28` | requested root/manifest → same plan | Requires correct output plus all current inventory facts and exact bound plan values. Called before full upload and recovery-sidecar selection. |
| `accept_viewer_plan` | `P/plan.py:35` | checked inventory + protected inputs → accepted plan | Checks incoming context, manifest bytes and conditions, enumerates payloads, loads prepared recovery, then binds context. |
| `attempt.prepare` | `P/attempt.py:48` | live selections/native runtime + optional retained root → prepared result | Requires exact native selection and original continuation binding; admits sizes, file proofs and phase before creating receipt/result. Calls `prepare_native_output`. |
| `attempt.verify_prepared` | `P/attempt.py:214` | restored directory + optional live inventory → `PreparedVerification` | Compares membership, runtime/source/policy, manifest digest, phase files and receipt/result producer identity before plan acceptance. |
| `attempt.publish` | `P/attempt.py:323` | accepted directory + explicit artifact/resume → publication result | Calls verifier and artifact check before journal mutation; restores/reconciles before protected-input guard; uploads with accepted plan. |
| `validate_prepared_output` | `P/publish_viewer_r2.py:83` | publication directory/manifest → observed name set | One census enforces single-PUT sizes; control/manifest/recovery checks remain; hosted verifier consumes returned names. |
| `prepared_files` | `P/publish_viewer_r2.py:199` | manifest/inventory → payload path map | v6 iterates bounded inventory pages and checks each covered file against declared facts. v5 retains explicit paths/shards. |
| `upload` | `P/publish_viewer_r2.py:460` | accepted plan/original conditions → result | Requires plan and matching release/selection conditions, checks per-file custody, then conditional transfer and pointer selection. |
| `Continuation.__init__` / `_restore` | `P/continuation.py:139,157` | root/binding/resume → validated state | Bounded read and shape validation precede exact binding equality and canonical byte accounting. |
| `Continuation.phase` | `P/continuation.py:210` | phase action or saved phase + inventory → result | Saved phase requires current proofs and exact digests; new phase checks total file/state bounds before storing it. Plain-file branch rejects symlink escapes before hashing. |
| `Continuation.checked_event` | `P/continuation.py:265` | event → one transition and exact byte delta | Validates transition/count and JSON delta before mutation; shared version changes are included. |
| `Continuation.record` / `flush` | `P/continuation.py:291,160` | event or state → cache/checkpoint | Applies one accepted change; direct records checkpoint, cloud journal records request periodic checkpoints. Full serialization remeasures its limit. |
| `Continuation.reconcile` / `replay` | `P/continuation.py:341,389` | persisted writes + explicit client/body → resolved state or acknowledgment | Reconcile reads only uncertain requests; replay compares exact local bytes/proof and original conditions via `ContinuedPublicationClient`. Successful acknowledgments need no GET/HEAD. |
| `DurableJournal.restore` / `record` / `_append` | `P/continuation.py:448,514,538` | bounded remote chain or event → recovered writes/durable event | Whole prefix validates before checkpoint replacement; append admits bytes/counts before conditional PUT; only accepted request evidence advances sequence. |
| `LocalContinuation.record` / `flush` / `_restore` | `P/local.py:122,112,106` | event/state or retained local log → state | Synced events precede in-memory changes and upload; phase snapshots append before derived checkpoint; restore owns state independently of `continuation.json`. |
| `read_local_journal` | `P/local.py:29` | local JSONL → reconstructed state + inspection counts | Checks complete lines, chain, limits and transitions; used by local restore and status without constructing a writer. |
| `RendererState.run` / `restore` | `P/filename_renderer_state.py:172,129` | task + retained DB/assets → completed task result/assets | Skips only committed task rows; restores and hashes retained files before putting proofs in current assets. |
| `save_preparation_checkpoint` / `verify_preparation_checkpoint` | `P/resume.py:119,158` | quiescent incomplete directory + exact artifact evidence → checkpoint/checked receipt | No publication writes/versions; original code binding plus full saved-file inventory required; complete pairs cannot be relabeled incomplete. |
| `ReconciliationProgress.__call__` / `read_progress` | `P/reconciliation.py:72,54` | observation → bounded latest file / checked display value | No durability sync/history; validates exact observation-only fields and binding; observer failure does not alter reconciliation results. |
| status `continuation` | `S/pipeline_status.py:113` | local evidence + expected identity → recorded status | Reads authoritative local events when present; otherwise reports checkpoint limitations; never resumes or claims fresh public/output integrity. |
| local `prepare_viewer` / `publish_imported` | `R/publication.py:16,71` | admitted local continuation/snapshot → accepted plan/publication | Uses the same inventory/plan path; local source pins, lock and protected versions remain dispatcher-owned. |

## Data flow and invariants

1. **File facts enter through fresh hashing or issued writes.** Fresh restore uses
   `verify_inventory`; file reuse depends on `VerifiedFile.require` checking the
   issuing process, exact target, device/inode/size/mtime/ctime, and immutable
   byte/hash facts (`C/viewer_inventory.py:78-110`,
   `packages/congress_shared/src/congress_shared/custody.py:119-129,144-169`). The
   inventory and bound view share mapping objects inside one process. Mutations
   do not establish new accepted facts: later `require` compares them against
   the proofs and current context. This is a trusted in-process custody mechanism,
   not protection from arbitrary malicious Python code executing in the process.
2. **Plan context escapes only as bound accepted values.** `accept_viewer_plan`
   verifies incoming preparation context; `bind_context` then binds complete plan
   values. Upload compares the plan with the caller's original selection and
   release conditions. Changed plan dictionaries or files cause refusal
   (`P/plan.py:22-67`, `P/publish_viewer_r2.py:465-473`).
3. **Initial resume preserves origin while admitting the actual artifact producer.**
   Only origin run/attempt values are taken from the original continuation; all
   current source/code/native/control binding values still compare exactly. A
   completed receipt/result pair keeps its producer and digest; a receipt alone
   preserves its release plan but may finish under the current producer
   (`P/attempt.py:88-97,170-209,239-254,325-334`). Interrupted renderer output remains
   resumable work, not an accepted upload inventory.
4. **The authoritative journal precedes public writes.** Cloud event limits and
   state transition admission precede the intent PUT and payload PUT. Full cloud
   replay validates the complete bounded prefix before replacing local state
   (`P/continuation.py:448-561`, `P/client.py:175-223`). Local synced JSONL owns local
   recovery and updates shared version maps in place; its bounds derive from
   current continuation capacities (`P/local.py:16-18,83-137`).
5. **Observation cannot authorize resume.** Progress contains no transfer proof;
   flags remain observation-only and bound to the current input digest. Status
   reads events/checkpoints/progress but does not construct a continuation or
   perform remote reconciliation (`P/reconciliation.py:27-84`,
   `S/pipeline_status.py:113-208`). `Continuation.reconcile` never reads progress.
6. **Counts and bytes remain enforced together.** Limits are 131,072 phase files,
   131,328 writes, 262,784 events, 128 MiB state, 1 MiB/event, and 256 MiB cloud
   journal. Workflow checkpoint readers permit 128 MiB and 132,096 files;
   local event/history bounds derive from the shared values
   (`P/continuation.py:22-33`, `P/resume.py:68-85`, `P/local.py:16-18`). No claim is
   made that every possible file-name/value shape fits all these independent limits.

## Tests read and concrete edge cases

These are static predictions from inspected assertions, not new execution results.
No source defect required a new focused run, and the already completed broad suites
and catalog work were not repeated.

| Test / scenario | Location | Expected behavior and evidence |
| --- | --- | --- |
| Unchanged issuance, context handoff and later plan use | `T/test_viewer_inventory_reuse.py:37-65` | Pass: one proof check per member at issuance; acceptance checks each plus manifest; context binding does not rescan; later use rechecks members. |
| Changed/missing file, forged facts or changed plan context | `T/test_viewer_inventory_reuse.py:68-96` | Pass: facts/context/custody mismatch refuses; plain serialized facts cannot issue inventory. |
| Fresh restored hashes and copied proof | `T/test_viewer_publication_attempt.py:493-516` | Pass: every member hashes once; same-process reuse adds no hashes; copied/plain proof and same-size corruption refuse. |
| Missing/additional output and shared directory census | `T/test_viewer_publication_attempt.py:814-838` | Pass: membership refuses before writes; verifier performs one directory walk. |
| Initial v5 interruption and current producer | `T/test_viewer_publication_attempt.py:646-718` | Pass: completed chunks are not reread, original binding remains, new producer supplies artifact custody, accepted repeat does not rebind receipt, owned fake publication succeeds. |
| Changed runtime/control inputs before resumed chunks | `T/test_viewer_publication_attempt.py:721-748` | Pass: exact continuation binding refuses before native chunk reads or remote writes. |
| Recovery, accepted phase, receipt-only and completed-result interruption | `T/test_viewer_publication_attempt.py:751-811` | Pass: resume skips committed renderer work; receipt-only/current producer and completed-pair/original producer differ intentionally; older completed v1 receipt identity stays fixed. |
| Abrupt renderer process loss and corrupt retained output | `T/test_filename_initial_resume.py:17-147` | Pass: task-start/completion cases resume, changed bindings/assets refuse, subprocess exit leaves retained state and resumes into current producer. |
| Full modeled release, interrupted halfway, replay and corrupt chain | `T/test_publication_capacity.py:74-150` | Pass: 100,000 fake uploads, 50,000 replays without duplicate PUTs, one GET for the last uncertain intent and zero HEADs; corrupt chain refuses without checkpoint/remote mutation. Per-event local persistence is counted rather than executed at scale. |
| Next count/byte and canonical Unicode limits | `T/test_publication_capacity.py:153-217,240-288` | Pass: state/event/journal limits refuse before payload; incremental sizes equal canonical serialization; worst noncoalesced completion order fits the configured journal bound. |
| Real inventory paging at relevant scale | `T/test_publication_capacity.py:220-237` | Pass: 100,000 synthetic references produce 1,563 real inventory pages and 101,563 unique references accepted by the state validator. Payload custody is exercised separately. |
| Journal interruption, local corruption and sync failure | `T/test_publication_state_bounds.py:49-174,201-241` | Pass: accepted evidence links to synced request bytes, failed local acceptance does not advance sequence, full-chain validation precedes checkpoint replacement. |
| Local state reconstructed without checkpoint | `T/test_local_continuation.py:46-118,147-217,246-273` | Pass: phases and acknowledgments restore from events; changed input/partial/corrupt history refuses; events sync before PUT; guard version map identity stays fixed; acknowledged uploads are not reread. |
| Local count and byte admission | `T/test_local_continuation.py:30-43,121-145,169-187,224-243` | Pass: over 65,536 events restore, byte accounting is exact, and failed sync/limits do not expose accepted in-memory writes. The event-count fixture disables fsync only for that scale loop. |
| Progress failure/partial reads and bounded status file | `T/test_reconciliation_progress.py:31-187` | Pass: completion follows checkpoint, malformed/partial read reports failure, acknowledgment replay has zero GETs, observer filesystem errors cannot mask the real outcome. |
| Status reads live local events, stale checkpoints and progress | `S/tests/test_pipeline_status.py:259-319` | Pass: fresh intent is visible with stale/missing derived checkpoint; malformed history refuses; legacy checkpoint freshness is explicitly unknown; progress grants no proof and no file is mutated. |
| Incomplete checkpoint custody and bounded-stop complete pair | `S/tests/test_preparation_checkpoint.py:57-122,264-351` | Pass: metadata/origin/file changes refuse, preparation-only descriptor fails before publication-client creation, completed pair requires its normal verifier/current producer, and 33 MiB state is admitted by the 128 MiB reader. |

The parent reports 723 publication/workflow, 235 data, and 154 JavaScript checks
passing on the integrated work. Those counts are supplied execution evidence;
this reviewer did not rerun or independently authenticate their full receipts.
Earlier pre-merge 73-test inventory evidence remains historical and is not
substituted for exact-merged-head execution.

## Verdict and handoff

**VERDICT: APPROVE.** The inspected combined paths achieve the intended bounded
capacity and remove redundant hosted inventory work without weakening required
file, source, phase, or resume checks. Changed-path coverage is adequate for this
static review. Confidence is **high for the traced invariants**, with full native
preparation cost and deployed behavior outside this review. No release, upload,
public smoke test, or remote mutation was performed here.

- Backup ref: `codex/backup-inventory-pre-review-20261026` → `f2c07b87913b50a6782244b16fd8038129844c23`.
- Review branch: `codex/review-capacity-inventory-20261026`.
- Exact rebased/reviewed SHA: `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`.
- Fix SHA: none; no code fix required.
- Report SHA: the single commit introducing this path (`git log -1 --format=%H -- docs/experiments/reviews-20261026/capacity-inventory.md`); the exact result is included in the final handoff because a commit cannot contain its own hash.
- Clean status: required after the report commit; recorded in the final handoff.
