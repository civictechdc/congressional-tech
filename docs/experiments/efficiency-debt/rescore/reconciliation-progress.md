# Reconciliation progress supplemental rescore

At exact `014303ed0a292bc418e38070776734ce0feaae07`, reconciliation overall improves from B+ to A- and its operator experience from B to A-. Status operator experience improves from B+ to A-. All other dimensions and the related replay row retain their prior grades. The historical 168-row gradebook and prior supplements remain untouched. No tests or benchmarks were repeated.

| Historical row | Correctness | Efficiency | DX | Thoughtfulness | Debt | Overall |
| --- | --- | --- | --- | --- | --- | --- |
| scripts/recovery_publication_continuation.py:102:Continuation.reconcile | A- (retain) | B+ (retain) | B → A- | A- (retain) | B+ (retain) | B+ → A- |
| scripts/pipeline_status.py:113:continuation | A- (retain) | B+ (retain) | B+ → A- | A- (retain) | B+ (retain) | B+ (retain) |
| scripts/recovery_publication_continuation.py:124:Continuation.replay | A- (retain) | B+ (retain) | B+ (retain) | A- (retain) | B+ (retain) | B+ (retain) |

Higher debt grades mean less architectural debt. These are scoped judgments, not arithmetic averages or ticket-closure scores.

## Reconciliation judgment

Retain A-: complete current body length/hash/ETag and original-condition semantics remain. Reconciled observation follows fresh client-bound proof; complete follows successful state checkpoint. Observer failure cannot change primary outcome. Progress is never restored as proof.
Retain B+: visibility adds work, not a speed optimization. Three GETs, nine reads/7,340,028 bytes, two fsyncs and zero PUTs remain; the fixture adds 17 atomic latest-file replacements, serialized characters 704 to 10,264, and 565 retained bytes. Median 0.060483 to 0.062430 seconds is a scoped added cost, not a production prediction.
B to A-: shared local/cloud reconciliation now reports object, current bytes/declared bytes, checked count, outcome and exact next check with binding, scan ID and timestamp. Successful local observations expose a previously silent scan; observer failures may leave missing or stale visibility.
Retain A-: observation-only flags, bounded updates/file size, complete-after-checkpoint ordering, fixed diagnostics and exception isolation preserve authority boundaries. Thoroughness supports the existing grade without claiming A.
Retain B+: a named helper and shared validator/status reader isolate visibility from authority. It adds a latest-file observation route and does not replace retained recovery ownership; broader accepted-plan work is separate.
B+ to A- for this narrow reconcile function: the specific operating visibility gap is closed with bounded, tested observations and unchanged readback authority. This does not upgrade the entire dispatcher or prove public publication.

## Status and retained replay

Retain A-: input-bound read-only observation validation marks malformed/foreign data unavailable; accepted outputs and public readback remain unchecked. The observer supplies no write authorization.
Retain B+: one at-most-16-KiB latest observation is read in addition to existing status evidence. No measured status speed or memory benefit.
B+ to A-: operators see the last recorded object/byte state and exact next check, or an explicit unavailable label, without mistaking it for completed public verification.
Retain A-: separate observation/authority semantics and stale timestamps are deliberate; no additional grade from ticket status.
Retain B+: status reuses the maintained parser, does not create mutable Continuation and grants no acceptance. The broader status aggregation remains.
Retain B+: this wider status function aggregates independent GitHub, progress, phase and verification evidence. A narrow display improvement alone does not justify a global status-grade uplift.

Retain all six replay grades: neither recorded complete progress nor validated status data is consulted. A fresh continuation/client performs a full-current-body fallback; ephemeral reuse remains issuing-client/key/version scoped.

## Traces

| Function | Input → output | Verified boundary |
| --- | --- | --- |
| `packages/viewer_publication/src/viewer_publication/continuation.py:228:Continuation.read` | client/bucket/key, optional observer → full size/hash/ETag or original read failure | Reads 1-MiB chunks and requires exact complete length; no more than 32 periodic updates plus initial/final read counts; observer errors isolated. |
| `packages/viewer_publication/src/viewer_publication/continuation.py:262:Continuation.reconcile` | restored intents and fresh client → current-body proofs/state checkpoint, observational progress | Fresh proof precedes reconciled; checkpoint precedes complete. Original missing/original/conflict semantics remain. |
| `packages/viewer_publication/src/viewer_publication/reconciliation.py:70:ReconciliationProgress.__call__` | one observation and bound input identity → at-most-16-KiB atomic latest file | Fixed flags deny resume/current/public proof. No fsync, journal event, published PUT or remote delivery. |
| `packages/viewer_publication/src/viewer_publication/reconciliation.py:25:validate_progress` | complete observation object → validated shape or refusal | Exact fields/states/next_check, strict integer counters, false authority flags and identity bounds. |
| `packages/viewer_publication/src/viewer_publication/reconciliation.py:52:read_progress` | latest file and expected binding → validated observation or refusal | Bounded read, exact binding digest; no authority or mutations. |
| `packages/viewer_publication/src/viewer_publication/continuation.py:314:Continuation.replay` | actual client/key/body and ephemeral proof → current receipt or full-read fallback | Never reads progress file; new client/continuation requires current bytes. |
| `scripts/publication/pipeline_status.py:113:continuation` | state path and expected run identity → read-only status with last observation | Malformed/foreign observations become unavailable; no accepted output/public readback proof. |

## Evidence and limits

All nine retained raw receipt hashes and all measured source-file hashes match. The three paired synthetic runs use three objects and 7,340,028 body bytes, and preserve complete authority state and fresh client-bound proof values. The retained source assertions cover incomplete/failed reads, invalid lengths, original/missing/conflicting states, completion ordering, observer/file failure isolation, update caps and read-only input-bound status. No tests or benchmarks were repeated.

- No experiments/tests repeated; retained measurement is at 8219e186 and read-only source equality is checked at merged 014303ed.
- Observation is local, best-effort and potentially stale; no remote artifact custody/progress delivery, public verification or resume/write authority.
- Bounded additional local I/O buys visibility; no speed or memory improvement, total-process memory bound or production latency prediction.
- Original full-current-body SHA256/length/version/original-condition checks and fresh client proof remain mandatory.
- Historical168rows and previous supplements remain unchanged; broader accepted-plan/architecture judgment waits for ct-bpyj.

JSON records full vectors, function/test locations, exact source/evidence/review hashes and retained costs. Architecture and aggregate efficiency judgment will follow final accepted-plan review rather than closed-ticket counts.
