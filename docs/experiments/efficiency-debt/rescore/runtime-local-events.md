# Runtime and local-event supplemental rescore

At exact `fd8eb4d373aed93319ddc8ed4a755d203c4c65c4`, two historical rows improve and seven related rows retain all six grades. The historical 168-row JSON/MD remains unchanged. No tests or benchmarks were repeated. Ticket status determines no grade.

Reviewer implemented ct-piku: this is a supplemental rescore, not independent self-approval. Parent independent review is hashed. ct-2ut4 source/evidence reviewed independently here.

| Historical row | Correctness | Efficiency | DX | Thoughtfulness | Debt | Overall |
| --- | --- | --- | --- | --- | --- | --- |
| scripts/dispatch_corpus_recovery_publication.py:78:load | B+ → A- | A- (retain) | C+ → B+ | B → A- | C+ → B+ | B- → B+ |
| scripts/dispatch_corpus_recovery_publication.py:113:run.journal | B+ → A- | B → B+ | C+ → B+ | A- (retain) | C+ → B+ | B- → B+ |

Higher debt grades mean less debt. Overall is a scoped judgment rather than an arithmetic mean.

## Runtime ownership

B+ to A-: execute-mode selection precedes admission; required package source owners must exist and stay contained. Foreign/unknown cached origins and extended paths refuse. Real explicit-file children receive origin checks before flock/client. Eight retained unsafe cases issue zero admission/client calls.
Retain A- for the narrow explicit-file loader; no speed credit. Cached observations avoid repeated path resolution: 25 warm checks issue zero resolves, 0.453 ms median observed. Complete pins add 58 files / 330,101 bytes per existing digest guard; this assurance cost prevents a whole-route speed claim.
C+ to B+: named SelectedRuntime and specific source-owner/fresh-process errors replace implicit mixed-owner behavior. Complete checkout required; unsupported historical layouts refuse explicitly.
B to A-: preflight stays lazy, cached modules are never evicted, exact pin changes still refuse resume, and a retained eager-import traceback leaves the shared lock reacquirable.
C+ to B+: one early source selection and named ownership proof replace late path mutation and unverified transitive owners. Explicit-file loading and in-process sys.path selection remain; no fully packaged or hostile-code-isolated runtime is claimed.
B- to B+: the historical owner gap now has implementation and real-import evidence. Interpreter-owned dependencies and the explicit loader remain, and no integrated live-runtime qualification is claimed.

The integrated LocalContinuation alias is imported inside selected package roots before flock; exact local.py source is pinned. SelectedRuntime, load and original-condition ASTs match approved 0affd10. Its retained real-import receipt observes 77 project modules and 7 direct-file modules in the selected tree; this is not a new integrated execution.

## Local event authority

B+ to A-: synced intent precedes conditional PUT; full readback precedes verified event and protected-version advancement. Validated local history restores accepted phases without the derived checkpoint; fresh resume grants no persisted ephemeral proof.
B to B+: retained 128-write/four-phase evidence removes 507 syncs (783 to 276), full-state encodings 263 to 12, and JSON characters 5,493,025 to 511,187. Ordinary JSON calls increase 652 to 923; scratch rises 117,247 to 245,262 bytes. Full snapshots and whole-history restore remain.
C+ to B+: one read-only parser serves restore/status. Status sees current intent facts without checkpoint mutation and labels legacy counts stale/unknown. Partial, excessive and failed histories stay retained with explicit refusal.
Retain A-: durable intent/readback/phase semantics, deliberate constraints and refusal policy were already thoughtful; stronger evidence alone does not justify an A grade.
C+ to B+: local events.jsonl owns state; continuation.json is derived. Dispatcher duplicate append and version callback are removed. Local/cloud persistence intentionally remain separate, with full phase/control snapshots.
B- to B+: overlapping local progress ownership is replaced with an evidenced maintained route. Larger retained history, bounded complete-history restore and separate accepted-plan work keep the grade below A.

The retained three-pair fixture has 128 writes, four phases and 9,874 request bytes. Complete state, 257 ordinary facts and 128 body hashes agree across all six runs, with 128 PUTs and 128 complete readbacks unchanged. Median 0.153948→0.079474s belongs to 0c2b782 only. The final map correction is covered by retained targeted assertions with unchanged serialization/sync/request boundaries; there is no integrated timing claim. History admits 256 MiB / 65,536 records and state 32 MiB; those are admission ceilings, not hard process-memory budgets.

## Retained related grades

- `scripts/dispatch_corpus_recovery_publication.py:94:run`: correctness B+, efficiency C+, dx B-, thoughtfulness A-, debt C+, overall B-. Keep the broader controller vector: the two corrected seams do not remove duplicated local/cloud preparation or accepted-plan ownership. ct-bpyj is separate; no parent upgrade from ticket closure.
- `scripts/pipeline_status.py:113:continuation`: correctness A-, efficiency B+, dx B+, thoughtfulness A-, debt B+, overall B+. Keep all six grades: status now uses validated local facts and labels legacy stale counts, but remains observational and proves neither output integrity nor current remote state. No new status latency or memory claim.
- `scripts/recovery_publication_continuation.py:21:Continuation.__init__`: correctness B+, efficiency B+, dx B+, thoughtfulness B+, debt B+, overall B+. Keep all six grades: named base restore hook permits the local authority override; original binding refusal and empty proof cache remain. Credit the new local route in row83 rather than each inherited primitive.
- `scripts/recovery_publication_continuation.py:37:Continuation.flush`: correctness A-, efficiency B+, dx B+, thoughtfulness A-, debt B+, overall B+. Retain completed-eight grades: compact shared checkpoint serialization/fsync is unchanged; local full checkpoints remain at phase/control boundaries and whole-state string/bytes copies persist. Avoid double credit.
- `scripts/recovery_publication_continuation.py:60:Continuation.phase`: correctness A-, efficiency B+, dx B+, thoughtfulness A-, debt B+, overall B+. Keep all six grades: accepted output rehash/reuse stays inherited. Checkpoint-loss recovery is credited to row83 rather than inventing a new phase-validation implementation.
- `scripts/recovery_publication_continuation.py:73:Continuation.record`: correctness A-, efficiency B+, dx B+, thoughtfulness A-, debt B+, overall B+. Retain completed-eight grades: cloud/base verified event and protected version already share one checkpoint. Local record overrides it and is graded in row83; no local fixture speed credit to cloud journal.
- `scripts/recovery_publication_continuation.py:102:Continuation.reconcile`: correctness A-, efficiency B+, dx B, thoughtfulness A-, debt B+, overall B+. Keep all six grades at this exact revision: explicit resume still reads complete current bytes and refuses conflicts, while replay proof is client/key/version scoped. Upcoming progress work is outside scope.

## Function traces

| Current function | Input → output | Checked behavior |
| --- | --- | --- |
| `scripts/corpus_recovery/dispatch_corpus_recovery_publication.py:38:SelectedRuntime.__init__` | runtime, cached modules, required package roots → selected source paths or refusal | Source containment and cached ownership precede execute admission; no module eviction. |
| `scripts/corpus_recovery/dispatch_corpus_recovery_publication.py:69:SelectedRuntime.check` | cached/direct modules and prior observations → ownership observations or refusal | New objects or changed origin/package paths recheck; direct children outside sys.modules included. |
| `scripts/corpus_recovery/dispatch_corpus_recovery_publication.py:96:SelectedRuntime.files` | selected source directories and actual driver → exact source pins | Selected common/control/local sources and executing driver included; bytecode excluded. |
| `scripts/corpus_recovery/dispatch_corpus_recovery_publication.py:145:run` | sealed batch, selected runtime, execute/resume flags → preflight or guarded publication | Lazy preflight; real builder imports and selected LocalContinuation alias before lock/client. |
| `packages/viewer_publication/src/viewer_publication/local.py:23:transition` | state,event,detail → validated candidate delta | Copies mutable write/version maps before transition validation. |
| `packages/viewer_publication/src/viewer_publication/local.py:91:LocalContinuation._append` | bounded event/checkpoint → synced chained JSONL record | Failed sync sets refusal; no in-memory admission or PUT follows that failure. |
| `packages/viewer_publication/src/viewer_publication/local.py:130:LocalContinuation.record` | intent/refused/verified event → durable event and in-memory delta | Sync before exposing key/version delta; never clear shared guard map or overwrite unrelated writes. |
| `packages/viewer_publication/src/viewer_publication/local.py:120:LocalContinuation.flush` | phase/control state → authoritative event then derived checkpoint | Event snapshot sync owns acceptance before checkpoint replacement. |
| `packages/viewer_publication/src/viewer_publication/local.py:40:read_local_journal` | bounded local history → validated state and inspection counts | Checks chain,binding,transitions and limits without mutation or current remote proof. |
| `packages/viewer_publication/src/viewer_publication/continuation.py:169:Continuation.phase` | phase action and accepted files → reused or newly accepted result | Accepted file hashes checked; local subclass owns new acceptance flush. |
| `packages/viewer_publication/src/viewer_publication/continuation.py:244:Continuation.reconcile` | fresh client and restored intents → current readback observations | Complete current bytes/version required; proof cache begins empty. |
| `scripts/publication/pipeline_status.py:113:continuation` | attempt path and expected identity → read-only state observation | Shared parser rather than mutable continuation; legacy counts explicitly stale/unknown. |

## Evidence limits

- No tests/benchmarks repeated, no integrated runtime speed or production/hosted/full-catalog qualification. Runtime single process samples do not prove speed gain.
- Local counts/timings belong to 0c2b782; final 1e572d0 map correction preserves operation boundaries with targeted assertions, not a new timing run.
- Local scratch and JSON call count increase; restore scans complete bounded history. No memory improvement claim.
- Complete package source layout required; third-party dependencies remain interpreter-owned. Origin checks are not hostile Python isolation.
- Broader accepted-plan duplication, final progress grades and whole-system architecture grade remain outside this supplement.

Six runtime and eight local raw receipt digests were independently checked. The integrated local source matches the reviewed final follow-up hash. Source, test assertion, review and raw evidence hashes appear in `runtime-local-events.json`. No aggregate architecture grade was recomputed.

Requested primary output/publication-exam-20261018/BELOW-B-PLUS.md absent. Maintained historical docs/package-overlap-rescore-20261019 JSON/MD contain 168 rows and exactly match completed-eight input hashes. Neither file changed.
