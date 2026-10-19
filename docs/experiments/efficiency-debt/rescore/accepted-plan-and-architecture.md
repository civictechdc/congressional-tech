# Accepted viewer plan and scoped publication architecture

Assessment at frozen `075779041f2d56fcdf138ee44ba6fa1d2a153e4c`, against merged base `014303ed0a292bc418e38070776734ce0feaae07`. This is a current source-and-evidence judgment of the publication flow and the nine ct-bpyj rows. It is not a rerun of all 168 functions, a deployment/production qualification, or an approval issued on Catalog’s behalf. Catalog’s actual independent approval and parent evidence validation are pinned separately below. This reviewer repeated no tests or benchmarks.

## Architecture judgment

| Dimension | Historical | Current | Practical meaning |
| --- | --- | --- | --- |
| correctness | B+ | **A-** | Strong source, file and write authority boundaries with inspectable failure/resume behavior. |
| efficiency | C+ | **C+** | Selected duplicate work is removed, but central memory/scan and remote durability costs remain substantial. |
| dx | B- | **B+** | Supported operation and recovery are clearer, with remaining setup and lifecycle complexity. |
| thoughtfulness | A- | **A-** | The design consistently protects exact evidence and states its limits. |
| debt | C+ | **B-** | Core responsibilities now have clearer owners, but important composition debt remains. |
| overall | B- | **B** | A careful and more maintainable publication system whose resource-heavy central paths keep it below excellent. |

Higher debt grades mean less debt. These are reasoned judgments, not arithmetic averages of functions, experiments or ticket counts.

**Correctness A-.** Runtime ownership refuses mixed cached code; one issued plan binds protected facts and original conditions; local events own durable state; fresh-client full readback and conditional selection remain. Static traces and retained focused receipts support this judgment; they do not establish current public/production correctness.

**Efficiency C+.** General Catalog construction, exact broad search/export allocation and cloud per-event readback remain. Rejected candidates did not justify replacement. Local event serialization/sync savings and accepted output-hash reuse are real scoped work reductions; no common end-to-end workload establishes aggregate throughput, RSS or CPU improvement.

**Dx B+.** One original-attempt descriptor, explicit selected-runtime refusal, retained incomplete-build next checks, observation-only reconciliation and a common plan reduce operator guesswork. Local/cloud custody is intentionally different; historical attempts do not auto-migrate, progress may be stale, and remote/public qualification still requires its own evidence.

**Thoughtfulness A-.** Exact nested/null/Unicode/order and original values remain; proposed/selected bytes, mandatory/optional failures and uncertain requests stay distinct. Failed performance candidates are retained without shipping regressions. Added assurance costs are measured and disclosed; completion counts add no grade.

**Debt B-.** Shared bounded reads, descriptors, runtime admission, local event authority, progress validation and AcceptedViewerPlan remove overlapping control ownership. General research Catalog use, optional no-plan/positional status helpers, nested source-custody Store, mutable dictionaries, direct-file loading and durable remote journal complexity remain.

**Overall B.** Integrity and operating clarity deserve higher marks than whole-flow efficiency. Coherent ownership improves the architecture, but large data preparation/consumer work and remote durability protocol dominate practical cost. This is a scoped professor-style judgment, not a numerical average of 168 functions or 12 tickets.

## What enters, happens and comes out

A sealed local recovery batch or accepted cloud preparation enters its own custody checks. The dispatcher keeps runtime admission, pins, lock and guarded client. `corpus_recovery.publication` owns local catalog/mapping/viewer phases. Cloud preparation keeps GitHub artifact/run identity. Both now issue `AcceptedViewerPlan`: protected source/mapping/viewer facts, source pins, accepted recovery status, exact inventory and original release/selector conditions. The plan wraps existing issued file proof; it creates no new persistence format or artifact service.

The uploader consumes that plan, writes immutable data, verifies current bytes/public probes and only then conditionally selects the original pointer. Local synced events and the cloud remote journal retain their distinct durability responsibilities. Fresh restart rehashes accepted files and reads current remote objects; copied JSON or a completed progress file does not grant proof. Status remains an observation, not permission to resume or publish.

## ct-bpyj historical function grades

| Historical function | Correctness | Efficiency | DX | Thoughtfulness | Debt | Overall |
| --- | --- | --- | --- | --- | --- | --- |
| apps/site/scripts/publish-viewer-r2.py:198:recovery_for_publication | B+ → A- | B (retain) | B+ → A- | B+ → A- | B → B+ | B+ (retain) |
| apps/site/scripts/publish-viewer-r2.py:204:select_recoveries | B+ (retain) | B+ (retain) | B (retain) | B+ (retain) | B (retain) | B+ (retain) |
| apps/site/scripts/publish-viewer-r2.py:285:upload | B+ → A- | B → B+ | B → B+ | B+ → A- | B → B+ | B → B+ |
| scripts/dispatch_corpus_recovery_publication.py:94:run | B+ → A- | C+ → B- | B- → B+ | A- (retain) | C+ → B | B- → B+ |
| scripts/dispatch_corpus_recovery_publication.py:209:run.Store.read | B+ (retain) | B (retain) | B- (retain) | B+ (retain) | C+ (retain) | B (retain) |
| scripts/dispatch_corpus_recovery_publication.py:214:run.Store.put | A- (retain) | B (retain) | B (retain) | B+ (retain) | C+ (retain) | B (retain) |
| scripts/dispatch_corpus_recovery_publication.py:267:run.prepared_phase | A- (retain) | B → B+ | B → A- | A- (retain) | B → B+ | B+ → A- |
| scripts/dispatch_corpus_recovery_publication.py:274:run.publication_phase | A- (retain) | B → B+ | B → A- | A- (retain) | B → A- | B+ → A- |
| scripts/viewer_publication_attempt.py:153:publish | B+ → A- | B (retain) | B → B+ | A- (retain) | B → B+ | B+ (retain) |

Six rows change; three retain every dimension. In particular, `select_recoveries` still has positional protected records and optional index derivation. `Store.read` and `Store.put` preserve already-credited behavior but remain implicit custody side effects in a nested adapter. Moving them behind a maintained domain entry improves the larger controller; it does not automatically erase each helper’s debt.

The two narrow local prepared/publication handoffs receive A- overall because they now return/consume an inspectable issued plan and independently restore its files. The broad uploader and cloud controller remain B+: optional paths, mutable lifecycle dictionaries, public selection and expensive durability still need careful reasoning. Full per-dimension reasons and current locations for all nine rows are in the JSON.

## Measured work, including the tradeoff

| Accepted local preparation + upload fixture | Before | After |
| --- | ---: | ---: |
| Known complete output hash helper passes | 823 | 270 |
| Bytes through those helpers | 279,129 | 50,688 |
| Recovery scans | 1 during upload | 1 during preparation |
| GET / HEAD / PUT | 278 / 270 / 273 | 281 / 270 / 273 |
| fsync calls | 554 | 557 |
| Serialized JSON characters | 825,186 | 927,970 |
| Tiny elapsed sample, seconds | 0.4955 | 1.0469 |

The change removes 553 known output helper hash passes and 228,441 bytes of repeated hashing. It does **not** remove the one recovery scan; acceptance moves it earlier and upload/restore reuse its result. Three extra GETs and three extra syncs retain protected inputs and plan facts. Fresh restoration performs 271 file hashes / 76,027 bytes once, with no rebuild or recovery scan.

The comparison records 269 equal payload hashes, complete normalized prepared/published manifests, recovery status, result and mutation conditions. Only prepared issuance time is normalized; changed code fingerprints remain separate expected provenance. The parent separately validates actual retained payload files; this assessment verifies the 16 frozen source hashes and 7 accepted raw receipt hashes and inspects the recorded comparison, rather than claiming that independent payload scan.

**There is no speed or memory gain claim.** One arm each is too little for latency qualification, and the baseline overlapped focused tests. The candidate is slower in the tiny sample. Hundreds of empty ID shards make removed byte hashing cheap; inventory custody/path/context checks, extra control reads and checkpoints add work. Hash counters exclude incremental transfer/decoder/native digests and physical disk reads. The observed RSS 128.8→130.0 MB is neither improvement nor a hard memory bound.

## Aggregate efficiency: improvements do not add up to a percentage

**Catalog.** Retained general Catalog; packed candidate rejected. Constructor peak about 1.4% lower and publication peak 3.2% lower missed target; small publication time 5.4058→5.4796s. General Arrow/Python maps remain; historical 5.085 GB Catalog / 7.310 GB preparation is dated pressure evidence, not current measurement.

**Search.** Retained exact scan; row-group candidate rejected. Warm broad median 0.1% slower; cold broad/AND 27.0% / 30.7% slower, decoded estimates 19,101,790→34,512,864 bytes and RSS 171,622,400→179,617,792. Historical 27.523 s broad query is not a current guarantee.

**Exact export.** Retained exact values; Blob candidate rejected. Modeled known storage +25.9%; parse/clone/format/clipboard allocation remains. Diagnostic/cache ceilings do not bound native heap.

**Cloud checkpoints/journal.** Compact serialization and shared verified-version checkpoint shipped. Retained local checkpoint encoding median 0.566→0.142 s; full remote journal counts 833 GET / 821 PUT / 270 HEAD unchanged on that fixture. Whole growing state and full remote readback remain.

**Local events.** One synced authority with derived checkpoints shipped. 128 writes / four phases: 783→276 syncs, 5,493,025→511,187 JSON characters; scratch 117,247→245,262 bytes and JSON calls 652→923. This fixture is not the cloud fixture.

**Admission/mapping/workflow/visibility.** Bounded reads, descriptor, runtime/diagnostics and progress shipped. Resource refusal/clarity gains do not imply average latency gains. Descriptor validator 12.15→19.73 ms and progress adds 17 local replacements on a three-object scan; current remote byte work unchanged.

**Accepted plan.** Shared issued plan and local domain entry frozen. Known output helper passes 823→270,bytes 279,129→50,688; scan moved not removed; three extra GET/syncs and tiny time 0.4955→1.0469 s. Not an aggregate speed or memory result.

These measurements have different inputs, stages, denominators and durability policies. Adding their percentage changes would invent a whole-system result. The defensible aggregate conclusion is that several identifiable repeated operations are gone while the general Catalog, exact consumer work and cloud durability request protocol remain. A representative end-to-end profile would be needed to measure throughput, CPU or resident memory for the whole current flow. None was run here.

## Remaining per-write and recovery costs

A local immutable write performs ownership/local checks, stats pin custody and may refresh bounded cloud clearance. Mutable/shared boundaries require fresh protected inputs. Cloud immutable `PublicationGuard.check` deliberately does no fresh selector read; `shared_commit` does. Every guarded payload still gets full current-byte readback, while cloud journal event intentions/results themselves require conditional remote writes/readbacks and retained receipts. These costs preserve authority and are not eliminated by naming an accepted plan.

Clarification of prior retained runtime rescore wording: +58 files / +330,101 bytes is larger initial pin/hash work and repeated stat/ownership comparisons. RecoveryGuard._pins(full=False) caches custody identity at immutable AND phase/shared boundaries; unchanged payloads do not trigger complete rehash of those bytes. Historical pinned reports/receipt hashes are retained unchanged; this corrects interpretation only.

## Source traces and verification limits

| Current function | Checked responsibility |
| --- | --- |
| `packages/viewer_publication/src/viewer_publication/plan.py:28:AcceptedViewerPlan.require` | Root, manifest, context and all file custody must still match. A copied/serialized dictionary cannot issue inventory. |
| `packages/viewer_publication/src/viewer_publication/plan.py:35:accept_viewer_plan` | Checks manifest/protected source/conditions, accepts file list once, loads accepted recovery, reissues existing proofs under complete plan context. |
| `packages/corpus_recovery/src/corpus_recovery/publication.py:16:prepare_viewer` | Stores original inputs/release before build; capacity admission and status acceptance precede common plan; fresh restore verifies complete file set once. |
| `packages/corpus_recovery/src/corpus_recovery/publication.py:71:publish_imported` | Owns Store/catalog/mapping/prepared/publication; preserves incomplete build, coverage, proposed-versus-selected and final supported result. |
| `packages/viewer_publication/src/viewer_publication/attempt.py:137:verify_prepared` | Existing preparation/artifact prerequisites remain; common plan binds original protected facts and mode. |
| `packages/viewer_publication/src/viewer_publication/attempt.py:246:publish` | Consumes plan files/status; journal restore, fresh reconcile, guards and public-selection checks remain independent. |
| `apps/site/scripts/publish-viewer-r2.py:341:upload` | Full-mode/conditions gate before PUT; plan file proofs avoid known rehashes; exact readback/probe/current-input checks still precede selection. |
| `apps/site/scripts/publish-viewer-r2.py:272:recovery_for_publication` | Same complete accepted record required; plan.recovery reused. No-plan derivation remains optional. |
| `apps/site/scripts/publish-viewer-r2.py:285:select_recoveries` | Existing public status and current-input verification remain; API/body unchanged. |
| `packages/corpus_recovery/src/corpus_recovery/guards.py:85:RecoveryGuard._pins` | Every boundary stats pins; hashing only initial/changed custody when full=False. |
| `packages/corpus_recovery/src/corpus_recovery/guards.py:115:RecoveryGuard.boundary` | Fresh cloud/protected checks and local/custody comparisons; not an exclusion lease. |
| `packages/viewer_publication/src/viewer_publication/continuation.py:441:DurableJournal.record` | Intent event gets own conditional remote write/readback and retained receipts; compact JSON does not remove this request protocol. |

The seven new source assertions cover actual local builder/upload integration, issued inventory/status reuse, original-condition failure/resume, independent subprocess restoration, same-size corruption, plan mutation and recovery-plan/full-upload refusal before PUT. Domain integration intentionally stubs the already-imported catalog rebuild while using the actual pair/coverage/builder/upload afterward. Existing dispatcher phase tests still use explicit stubs. Owner logs contain 222 distinct focused passes plus 7 subtests after an isolated missing-PyYAML repair; that is not a single full-suite green run.

Catalog independently issued **APPROVE** for frozen 0757790; its certificate is separately pinned. Parent evidence review independently verified 269 actual payload files per arm and source identities. The same reviewed source is locally integrated at `e9b18a9699af34b52742c3e9ca3658cb71ab8f20`: combined affected local checks passed **251 tests and 7 subtests in 47.43 s**, with the log pinned. This does not replace the original 221-pass-plus-PyYAML-repair history above, which remains retained. The scope contains no source acquisition, hosted/public/full-catalog/held-out qualification or remote writes. Historical 168-row files and earlier independently pinned receipts are preserved; the JSON binds exact source, current receipt, accepted raw artifacts and earlier supplemental hashes.
