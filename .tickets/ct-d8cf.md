---
id: ct-d8cf
status: open
deps: [ct-tw3r]
links: [ct-jo8n, ct-xu1o, ct-pgxn, ct-a3le, ct-0bce, ct-qkvr, ct-4nyy, ct-5yof, ct-ur7v, ct-dzyf, ct-a1aa, ct-8ax6, ct-n6lj, ct-r60e, ct-x0nk, ct-8kl2, ct-98sm, ct-mi03, ct-syem]
created: 2026-10-24T18:15:54Z
type: task
priority: 2
assignee: mikewolfd
---

# Recover News Lake writes safely on the existing backend

**Parked News Lake work.** The production CLI, native upsert and incremental bridge paths already use DocSpec. Qualify and repair those paths. The remaining write risks are the lease handoff, partial durable commits, rollback against stale local state, cached abandoned values and chronological comparisons of timestamp strings. News runtime selection must use the intended verified binary.

`ct-xu1o` owns cold logical-ID conflict refusal and append scale. `ct-jo8n` owns exact derived inputs and old available-release reads. `ct-4nyy` owns public export rights and expiry. Share scenarios and results rather than repeating them. The optional labels feature in `ct-5yof` is deferred and is not a backend or congressional release prerequisite.

## Acceptance Criteria

- Qualify the existing CLI on the verified runtime. Port the relevant release, replay, recovery and bridge cases in `test_releases.py`, `test_coordinator_replay.py`, `test_recovery.py` and `test_partitions_and_bridges.py` to `DocSpecLake` with expectations from the data rules. Credit the delivered CLI and native merge. After parity, retire PyIceberg production dispatch, duplicate state machines, obsolete shim and fallback flags. Keep a Python reference only in tests if the owner retains it.
- Return the acquired writer epoch inside the claim transaction. Enforce that same lease at every native dataset selection and application publication transition, including a takeover between datasets or during an in-flight request. Entry/exit checks alone are insufficient. Preserve the engine's own exact-base protections. Reconcile a lost response from the recorded operation and selected pin before advancing another dataset.
- A failed cycle restores the latest available release's exact baseline using native changes and a new update against the verified current head. Include partial durable commits absent from the local pin map. Preserve multiplicity, relationship data and physical delete keys. Invalidate or rebind both ID and upsert caches so an abandoned value cannot suppress its later retry. Cover failed validation, repeated abandon, staged-checkpoint discard, refusal without a baseline and refusal after release append.
- Preserve monotonic upserts and release-pinned cross-table bridges. Qualify mixed fractional-second instants for merge ordering, minimum and maximum while retaining the original fields and precision. Coordinate strict expiry with `ct-4nyy`. Remove remaining full-corpus Python bridge/rollback scans, quadratic batch duplicate work and obsolete merge/export routes only when the replacement preserves behavior and the measured work improves. Reuse same-pin validation; qualify changed rows and required dependency context before replacing broad validation.
- Keep periodic lifecycle compaction and protect available and retryable release dependencies. This ticket owns safe maintenance integration; `ct-jo8n` owns the old-release readback acceptance. Reuse one scenario across both. Prefer maintained tail coalescing when verified; keep the safe fallback until that capability works or a focused upstream gap is recorded.
- Exercise native finite-number validation, the C6 identity-decision graph, C7 run-input acyclicity, unique checkpoint connector keys and credential redaction. Explicitly settle and test `ct-r33r`'s metadata-only version from a failed capture. Qualify public subset export and the expiry boundary through `ct-4nyy` before removing its duplicate policy.
- Replace static receipt and test-local `_ArrowHttpStream` assertions with actual maintained behavior. Pin the schema to its Git digest, retain changed-path results and independent review, and update the README. Preserve provider refusals and `ct-3180`'s qualified R2 evidence. Apply the existing raw-writer check where the changed path writes raw storage. Keep unrelated news and UI work intact.

[Final root-cause review](../docs/plans/production-mvp-root-causes-round4-20261105.md).

## Notes

**2026-10-24T18:47:54Z**

Efficiency pass E10. (1) Don't revert append keys to ['id']: polls became O(history) in measurement (561 to 1,088 ms between 120k and 2.16M rows). Derive the time key from input, or use engine insert-if-absent (ss-jxvn). (2) Fix the quadratic duplicate check (2.36 s at 44k). (3) Consume the engine's change stream instead of re-reading datasets. (4) Validate only deltas on publish. (5) Keep the engine's C5 rights policy, with Python only as a test oracle. (6) Keep periodic lifecycle compaction (see ss-1uh5).

**2026-11-05T17:11:15Z**

Current consolidated ownership, 2026-11-05: parked News Lake runtime/recovery owner; absorb ct-ur7v, residual ct-0bce and ct-dzyf. Keep ct-jo8n as exact-release owner, ct-4nyy as rights owner, ct-xu1o as append/replay/measurement owner, and standalone ct-5yof as classifier owner. Native validation inherited from ct-a1aa includes interrupted mid-upsert/in-flight publish convergence, finite floats, C6 decision graph and C7 input acyclicity, unique checkpoint connector keys, credential redaction, accurate README, and the existing ct-r33r metadata-only version from a failed capture case (contract/semantics.py:189–204). Preserve source/provider fail-closed behavior and ct-3180's qualified R2 evidence. The latest owner decision keeps periodic lifecycle compaction and requires measured key choice; do not revive the superseded blanket instruction to revert time keys or delete all periodic compaction. Move news upserts/bridges/export retirement from ct-a3le here; keep monotonic and cross-table semantics. No new Phase 2 gate is introduced.

Consolidation accepted 2026-11-05: absorb ct-ur7v, ct-0bce, ct-dzyf.

User outcome: One maintained News Lake backend and recovery implementation.

Remaining acceptance: Production CLI; removal of alternate dispatch and duplicate state machines; native crash/fence/compaction checks; exact-release rollback pins; abandon idempotency and refusal after publish or without a baseline; checkpoint discard; old-release readability. Carry only remaining work; preserve completed evidence.

Source evidence and full original criteria remain in: .tickets/ct-d8cf.md:14; .tickets/ct-ur7v.md:28; .tickets/ct-0bce.md:45; .tickets/ct-dzyf.md:17; packages/news_lake/src/news_lake/storage/docspec/lake.py:865. The superseded records remain available; completed work is reused and unfinished criteria stay with this owner.

**2026-11-05T20:56:46Z**

Final root-cause review: credit the existing backend and focus on writer fencing, partial durable commits, rollback, abandoned caches and timestamp comparisons. Keep append, exact-read and export ownership in their existing tickets.

**2026-11-08T17:23:55Z**

2026-11-08 sweep-d: KEEP OPEN (parked). Rechecked on main 302dc5e6: nothing schedules or imports news_lake outside its own CLI/tests, and it writes no raw storage, so no source data is at risk. Defects still present in code: abandon_cycle never clears _known_upsert_records (lake.py); ControlStore.claim returns self.epoch() after its write transaction (control.py:116-123). Recommended plainer A/C for resumption: before the first scheduled news run, a failed cycle leaves the last available release readable and byte-identical, claims return their own epoch, and timestamps compare as instants; move PyIceberg retirement and cleanup items to notes.
