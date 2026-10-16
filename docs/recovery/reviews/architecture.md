# Independent architecture review: recovery MVP

**VERDICT: APPROVE the design for staged local adoption.** Keep the maintained commands, exact evidence bindings, shared writer lock, and runtime separation. Live adoption remains pending. Acquisition corrections and their certificate are complete; the exact runtime overlay and its actual tiny-catalog probe passed; a concrete command handoff is saved. Checkpoint-16 exit/readback, final runner pins, monitor adoption and the next publication's live checks remain required before reporting the entire effort complete.

## Findings first

**F1 — RESOLVED CONCERN, named-seam / ownership: executable handoff now names the shared inputs.** `docs/recovery/next-batch-command-handoff.json` saves exact absolute argv for coalescing checkpoints 17/18, body reconciliation, import, preservation verification, publication and explicit publication resume. Import and both publication commands name the same primary `--control-root` and external `--readiness`; coalescing/publication name the same freshly read accepted baseline; publication names staged runtime `fcc65a6`; credential arguments contain the existing config path only. The handoff requires checkpoint-16 actual exits and fresh remote/public readback before preparing final runner plans, and refuses missing artifacts rather than treating them as complete. Recommendation: **KEEP** this handoff and pin its exact bytes plus completed inputs at each phase. Saving it closes the design-binding concern; preparing/running those plans and updating the authoritative monitor remain live adoption work.

**F2 — RESOLVED OBSERVATION, scope: acquisition hardening is locally reviewed.** The cookie/refusal/worker/plan-hash corrections from acquisition `4950d11` are integrated as `a3ee633`. `docs/recovery/reviews/acquisition.md` approves the local acquisition scope and names remaining provider/authorization limits. Source-preparation's transport-timestamp and sealed-read corrections are also approved through final integration `ee728cf` (`docs/recovery/reviews/source-preparation.md:Current review result`). Publication's incomplete-build preservation correction has a separate approval (`docs/recovery/reviews/publication.md:Addendum: preserve incomplete catalog evidence`). Recommendation: **KEEP** those local certificates and their live limits. No acquisition, import or publication success is inferred from them.

**F3 — RESOLVED OBSERVATION, intent-vs-shape: the exact-base runtime overlay is installed and probed.** The staged runtime is committed at `fcc65a635a0976399e901167aa31a1aecff8db6b`, based on exact existing runtime `c361df34aa60f83877cd0c2e287a8d1410952ff1`. Its code diff contains only the two reviewed viewer publishers and `catalog_validation.py`; the fourth changed file is the identity record at `docs/recovery/mvp-runtime-overlay.json` inside that runtime checkout. The record preserves their hashes and says `deployed: false`. `output/recovery-mvp-runtime-probe.json` names the actual staged package/builder paths and reports one row materialized into 269 files / 73,479 bytes with zero remote writes. Recommendation: **KEEP** this narrow overlay and its recorded identity. The actual compatibility probe closes the earlier missing-overlay/import evidence; full retained-corpus behavior and live selection remain unverified.

No unresolved architectural blocker was found in the declared shape. The earlier design concerns above are resolved locally; their adoption gates remain explicit; this report does not approve execution over the active publication.

## 1. Artifact summary and decision frame

Artifact: `docs/recovery/mvp-execution-20261016.md`, rereviewed against final integration code `ee728cf3cb33c5bd574cd7b0504899e8e322c95c` and the saved command handoff in `/Users/mikewolfd/.codex/worktrees/recovery-mvp-integration/congressional-tech`. The document and final certificates are pending the parent's documentation commit; the reviewed dispatcher code includes the shared `--control-root` support. This review used the semi-formal architecture-review skill and did not edit implementation source.

The problem is repeated transfer/compression, repeated interpretation work, high Python baseline memory, dated worker/supervisor copies, and delayed viewer availability. The decision is a small set of maintained local commands that retain existing source/body/publication boundaries, rather than a new queue service or data platform (`mvp-execution-20261016.md:3-21,33-72`). The direct beneficiary is the operator handling recovery; the downstream beneficiary is a viewer user who can retrieve a correctly associated recovered document sooner. Category: **operations scaffolding and proof infrastructure supporting an existing product surface**.

The design changes the path to an outcome, not the public product definition. A qualified body, imported receipt, selected catalog, published mapping, selected viewer release, and public saved-file retrieval remain distinct acceptance states (`docs/plans/corpus-recovery-next-steps-20261016.md:Remaining work and completion evidence`; `mvp-execution-20261016.md:55-66`).

## 2. Lineage and relationships

| Prior artifact | Type | Relation | Evidence |
| --- | --- | --- | --- |
| User-supplied AGENTS instructions, Refactoring | Parent constraint | Every refactor must simplify or improve measured resource use while preserving behavior/data | Current review request and supplied instructions |
| `docs/plans/corpus-recovery-next-steps-20261016.md` | Parent plan | Establishes correct source associations, exclusions, shared writer clearance, guarded import/publication and live readback | Remaining work and completion evidence; Guarded import core; One-shot dispatch driver |
| `docs/recovery/checkpoint16-combined-successor-20261016.json` | Prior operational decision | Demonstrates coalescing incorporated batches and forbids dispatching them separately | `dependency.incorporated_unimported_batches`, `do_not_dispatch_incorporated_batches_separately` |
| `docs/recovery/catalog-publication-adapter-repair-20261016.json` | Failure/repair lineage | Earlier wrapper/internal-builder mismatch establishes why runtime compatibility must be verified | `failure`, `repair`, `next_attempt` |
| `docs/recovery/publication-runtime-dependency-sync-20261016.json` | Runtime lineage | Pins the maintained viewer runtime to `c361df34...` and records dependency completion | `source_runtime`, `source_head`, `files` |
| `docs/recovery/publication-integration-check-20261016.json` | Prior offline proof | Establishes compositional import/catalog/viewer evidence while explicitly withholding a live claim | `local_integration.scope`, `uploader_integration.scope`, `limitation` |
| `docs/recovery/import-t4-t5-independent-review-20261016.md` | Sibling review | Supports body reuse and Arrow preservation; external-readiness seam observation now has a focused integration test | Verdict; Findings |
| `docs/recovery/reviews/publication.md` | Sibling review | Supports local publication continuation, verified transfer reuse and in-process catalog proof; no live qualification | Verdict; Data flow and invariants; Tests and edge cases |
| `docs/recovery/reviews/t3-t8-t9.md` | Sibling review | Supports bounded guards, actual child waits and coalescing; names scheduling/resume/input-selection limits | Findings and disposition; Outstanding limits |
| `docs/recovery/reviews/acquisition.md` | Final sibling review | Approves local T6/T7 corrections integrated as `a3ee633`; preserves provider/queue limits | Verdict; Scope and trace; Limits and operator responsibilities |
| `docs/recovery/reviews/source-preparation.md` | Final sibling review | Approves exact source/body/transport-time binding and sealed-read preservation through `ee728cf` | Current review result; final rereview |
| `docs/recovery/next-batch-command-handoff.json` | Prepared operational binding | Saves all phase argv, common lock/readiness/current-baseline/runtime/config identities and predecessor gates | `commands`, `runner`, `gates_before_any_next_writer`, `remaining_after_this_batch` |
| Runtime `docs/recovery/mvp-runtime-overlay.json` | Applied runtime identity | Records exact `c361df34...` base and three reviewed code-overlay hashes | File in `recovery-mvp-runtime` checkout; commit `fcc65a6` |
| `output/recovery-mvp-runtime-probe.json` | Actual staged-runtime proof | One-row materialization using the real staged package and builder paths, no remote writes | `runtime_head`, `modules`, `rows`, `files`, `total_bytes`, `remote_writes` |
| `docs/recovery/maintained-acquisition.md` | Sibling acquisition design | Defines explicit queues/configuration, immutable receipts, frozen qualification and rendered provenance | Maintained recovery commands; Durable evidence and qualification |
| Primary `output/corpus-retry-20261015/current-continuation.json` | Current operational handoff | Records checkpoint-16 ownership and queued successor inputs; must receive new concrete command wiring at adoption | `active_publication`, `next`, `next_sealed_batch`, `additional_sealed_direct_batch` |

No ADR is claimed as the normative authority for this recovery flow. The existing parent plan and actual maintained command boundaries provide the operative commitments. The repository's sibling ADRs address unrelated adapters/dependencies and do not subsume this recovery decision.

| Component / named seam | Owner | What enters / happens / leaves | Consumer and check |
| --- | --- | --- | --- |
| Acquisition to qualification | Acquisition command and reviewer/operator | Explicit approved target/config -> retained response + immutable receipt -> classified or qualified evidence | Batch preparation; source/body identity and deferred exclusions (`maintained-acquisition.md:15-28,69-110`) |
| Qualification to sealed batch | Preparation/coalescing commands | Completed qualified records and authoritative mapping -> deduplicated metadata union -> sealed manifest with input hashes | Reconciliation; `sealed_inputs` verifies capture/body coverage (`coalesce_corpus_recovery_batches.py:43-44,64-97`) |
| Sealed batch to readiness | Reconciliation command | Frozen inventory + optional digest-pinned prior proof -> fresh object/version checks -> separate readiness/readback | Import and publication; pinned external readiness (`mvp-execution-20261016.md:43-47`; import dispatcher `:53-63`) |
| Readiness to raw retention | Import dispatcher | Exact inputs + fresh raw baseline -> absent-body upload/receipts/state append -> completed import evidence | Preservation audit and publication verification; conditional raw pair (`import_corpus_recovery_batch.py:108-124`) |
| Completed import to catalog/mappings/viewer | Publication dispatcher and retained viewer runtime | Completed raw evidence + fresh mapping baseline -> guarded accepted phases -> selected catalog/mapping/viewer | Public saved-file/coverage checks; phase evidence (`dispatch_corpus_recovery_publication.py:223-275`) |
| Local execution to evidence | Local runner; child owns pipeline-specific checks | Pinned absolute command/cwd -> actual supervised child -> logs/status/waited exit | Operator/monitor; child exit is not public completion (`run_corpus_recovery.py:100-117,121-171`) |
| Isolated checkout to one local writer | Both dispatchers, operator-supplied primary control root | Same primary lock path -> nonblocking exclusive lock -> inode checked during writes | Both pipelines refuse an already-held shared lock; publication resume binds control root (`dispatch_corpus_recovery_publication.py:132-134`) |
| Prepared source pair to viewer preparation | Catalog validation utility | Exact files/manifest/validator/expected bodies -> process-local validation proof -> reused coverage | Viewer builder; no proof survives restart (`catalog_validation.py`; publication review, T10 trace) |

The seams are named in the operating sequence, maintained command documentation and the concrete handoff. F1 is resolved by that saved binding; the operator/monitor must still turn each phase into a pinned runner plan after its real inputs exist.

## 3. Invariants and commitments

| Invariant | Status | Evidence | Failure if violated |
| --- | --- | --- | --- |
| Source URL/body association and exclusions survive every step | PRESERVED / RELIED UPON | Parent plan, Remaining work; design `:76`; coalescer/import review | A valid file appears under the wrong hearing/link or a deferred item is published. |
| One local writer spans isolated code/runtime trees | PRESERVED; saved operational argv explicitly share it | Design `:49-53`; import dispatcher `:67-70,132`; publication dispatcher `:103-106,176` | Separate worktree locks admit overlapping writers. |
| Active checkpoint-16 code and runtime remain pinned until physical exit | PRESERVED / rollout gate | Design `:5-6,68-72`; primary continuation `active_publication` | Editing active code invalidates guards or changes in-flight interpretation. |
| Shared index/pointer selection stays conditional and freshly guarded | PRESERVED | Design `:77`; guard `boundary`; publication review, Data flow and invariants | A stale writer replaces another writer's raw state, catalog or viewer selection. |
| Exact retained/body verification precedes proof reuse | PRESERVED | Design `:43-47`; import review, Data flow and invariants | Corrupt or stale remote content is treated as a verified body. |
| Immutable response/receipt evidence remains authoritative | PRESERVED; acquisition hardening locally approved | Acquisition documentation `:69-94`; design `:35-36` | A worker retry or mutable aggregate hides an uncertain request or changes its meaning. |
| Rendering does not imply archive byte identity | PRESERVED / acceptance gate | Design `:78`; acquisition documentation `:53-55,105-110` | A rendered derivative is misrepresented as original archive bytes. |
| Fresh mapping edits/deletions remain authoritative | PRESERVED, with explicit caller selection duty | Design `:79-80`; coalescer `:67-73`; mapping merge; T3/T8/T9 review limits | Replaying a previously published cumulative batch resurrects removed mappings. |
| Runner/local review success is distinct from publication success | PRESERVED | Design `:55-66,84-90`; runner `:100-117` | Exit zero or a test result becomes a false public-availability claim. |
| Interpretation/naming behavior is not changed by infrastructure rollout | PRESERVED by exact-base three-file code overlay; tiny actual-runtime probe passed | Design `:68-72`; runtime `fcc65a6`, overlay identity and `output/recovery-mvp-runtime-probe.json` | A throughput refactor silently changes catalog grouping or source labels. |

Cloud-status checks are observations rather than a distributed lease. The design retains conditional writes and subsequent live readback as additional defenses. This limitation is already explicit in the independent guard/publication reviews; no new distributed-lock system is justified by this MVP.

## 4. Task coverage and user value

| Task | Design coverage | Verified/local meaning | Remaining acceptance |
| --- | --- | --- | --- |
| T1 | Accepted publication phases and explicit continuation | Independently reviewed local behavior | Actual staged-runtime compatibility probe passed; retained-data run and live phase/pointer/readback remain |
| T2 | One verified transfer proof and six immutable upload workers | Publisher-path fake-store/count/concurrency evidence | Production transfer timings and public payload checks |
| T3 | Bounded immutable guards, fresh shared boundaries | Independently reviewed; freshness/ownership corrections tested | Prepared shared-control-root command binding inspected; live ownership checks remain |
| T4 | Missing-only compression and maintained readiness | Independently reviewed; new readiness/import/publication-verification seam test passed | Current exact batch/remote identities at dispatch |
| T5 | Arrow append and bounded comparisons | Independently reviewed; scoped synthetic memory evidence | Production-size memory/time observation; no constant-memory claim |
| T6 | Explicit maintained acquisition commands/dispositions | Shape documented and prior 45 failures accounted for | Corrections integrated as `a3ee633`, independent local approval saved; live provider/admission evidence remains |
| T7 | Immutable receipts, frozen qualification/cache, PDF preview | Shape documented; serialization scope is explicit | Acquisition correction certificate saved; future queue/provider work and physical-I/O performance remain unqualified |
| T8 | One maintained command supervisor | Independently reviewed actual wait/status/crash safeguards | Concrete phase argv saved; final input pins and actual runner adoption remain; phase command owns remote reconciliation |
| T9 | Coalesced unpublished batch and actual CLI cadence gate | Independently reviewed union/conflicts/gate | Checkpoints 17/18 selected once in saved handoff; monitor adoption/consumption evidence remains; 900 seconds is not a delivery guarantee |
| T10 | One exact process-local catalog proof | Independently reviewed pair/validator invalidation | Narrow overlay `fcc65a6` installed and actual-runtime probe passed; full retained-corpus/live behavior remains |

The user-visible value is earlier access to correctly linked retained documents and fewer failed or repeated operations before they become available. Conceptual debt falls because maintained commands replace dated copies, immutable receipts replace repeated full aggregates, and exact proof reuse removes repeated expensive validation. Small JSON evidence files and a local runner are appropriate debt for recoverability; a new database-backed scheduling framework would add a larger seam without an established need.

The reported memory comparisons are appropriately scoped to synthetic components (`mvp-execution-20261016.md:23-27`). The preservation audit explicitly trades CPU/I/O for lower peak memory. The serialization comparison measures logical JSON work, not observed physical I/O or elapsed runtime (`:29-31`). These claims honor the user's refactoring requirement without promoting them into whole-pipeline benchmarks.

Falsifiability: after adoption, if ready batches still cause repeated whole-prefix serialization, repeated full object transfers, redundant catalog interpretation, or unchanged operator delay with no recorded bottleneck, the claimed simplification has not delivered. If viewer links become available but point to incorrect source versions or lose existing mappings, the product goal has failed regardless of throughput.

## 5. Counterfactual analysis

- **Kill criterion:** any rollout that cannot prove shared primary-lock ownership, exact runtime identity, correct source association or unchanged baseline mapping semantics must stop before shared selection. A code/test certificate cannot waive those checks (design `:49-53,68-82`).
- **Opposite decision:** continue numbered scripts, per-checkpoint builds and full-prefix aggregates. That minimizes immediate code movement but retains the measured duplication and opaque failure/restart behavior. It does not satisfy the user's simplification objective.
- **Removal probe:** removing maintained readiness first breaks the named evidence handoff to import/publication; removing the runner forces operators back to ad hoc wait/exit tracking; removing coalescing restores per-batch processing. None requires removing the established catalog/viewer product implementation.
- **Sibling subsumption:** existing catalog and viewer implementations should continue to own catalog semantics and serving. The new dispatcher reuses them; it does not replace them. Existing monitoring supplies wakeups, so a second resident scheduler is unnecessary (`mvp-execution-20261016.md:40,68-72`).
- **Smallest sufficient shape:** keep separate acquisition, raw import and derived publication commands because they have different permissions, evidence and failure states; connect them through exact file pins rather than combine them into a process that acquires, imports and publishes implicitly.
- **Six-month critic:** the likely remaining debt is duplicated operating prose and forgotten command/runtime identities. A concrete pinned handoff plus one current continuation record is a smaller correction than creating a general workflow platform. Periodically retire superseded local scripts only after retaining their historical evidence; cleanup is outside this review.

## 6. Verification and outstanding rollout work

This architecture review is primarily static. It read the design, parent recovery plan, prior runtime/failure/integration artifacts, acquisition documentation, component reviews, new dispatcher lock changes and relevant caller boundaries. It did not independently repeat T4/T5 implementation review. The final update inspected the acquisition/source-preparation/publication correction certificates, exact runtime-overlay commit and hashes, staged-runtime probe, and command handoff; those local facts supersede the original pending entries.

Three focused offline seam checks passed against the inspected integration working tree:

- `test_isolated_runtime_uses_shared_control_lock`: held primary-style control lock stops isolated import before writes.
- `test_isolated_publication_obeys_existing_shared_lock`: the same held lock stops publication.
- `test_maintained_reconciliation_to_import_to_publication_evidence`: fake object-store reconciliation output passes import and publication evidence verification; corrupting the pinned external body report is rejected.

Tests are in `tests/test_dispatch_corpus_recovery_import.py` and `tests/test_dispatch_corpus_recovery_publication.py`. No production request or shared remote write occurred. Both dispatcher lock paths resolve from `--control-root`; both recheck lock inode during guarded writes; publication also includes control root in its immutable resume binding. The runner itself need not hold the publication lock, because the child dispatcher holds it; holding the same lock in both would prevent the child from acquiring it.

The command handoff was read and checked without executing its phase commands. Absolute executables are used throughout; import/publication/resume share the primary control root and readiness path; coalescing/publication share the current-baseline target; publication points to the import destination. At rereview, checkpoints 17 and 18 both already contained their prepared-source records and completion reports. Their body readiness and the selected-current baseline are intentionally future inputs, not placeholders for success.

Remaining live sequence, consistent with the design:

1. Record actual checkpoint-16 child/supervisor exit and fresh raw/catalog/mapping/viewer readbacks. Preserve its pinned runtime until then.
2. Save the selected-current accepted mapping bytes plus GET ETag/hash at the handoff's `publication16-final-readback` target. Confirm checkpoints 17/18 remain sealed and unpublished; preserve named extras for later work.
3. Adopt the saved handoff in the authoritative continuation/monitor and prepare each runner plan only when its inputs exist, pinning final integration code, runtime, handoff and exact completed phase evidence. This adoption is not established merely by a saved argv list.
4. Run read-only reconciliation and preflight against the chosen batch; then complete authorized import, actual waits, preservation verification and one guarded publication. Explicit continuation remains a separate diagnosed decision; incomplete local catalog evidence is preserved rather than deleted.
5. Report live completion only after current selected identities, public payloads/saved links and representative original/ZIP/rendered viewer coverage pass. The staged one-row compatibility probe does not establish these live results or full-corpus throughput.

The existing local acquisition approval does not start a new provider request, grant a retry, purchase credits or remove deferred exclusions. Additional acquisition/adoption remains subject to the preserved queue, spend and evidence boundaries.

## 7. Verdict

VERDICT: APPROVE

- Intent vs. shape: **MATCHES** — the changes reduce repeated work while retaining acquisition, retention, interpretation and publication boundaries.
- User-value claim: **SUPPORTED for local design** — measured resource reductions and safer recovery steps support earlier availability; live delivery remains unmeasured.
- Commitment status: **HONORED**, with completed local acquisition/source/runtime reviews and explicit remaining adoption/live-verification gates.
- Conceptual debt delta: **PAYS DOWN** — maintained local commands replace duplicated workers and supervisors; no new resident service is required.
- Sibling subsumption: **PARTIAL** — reuse the existing monitor/catalog/viewer; do not duplicate their responsibilities.
- Confidence: **HIGH** in the reviewed architecture and lock/readiness seams; no live rollout, additional acquisition or corpus-completion claim.
