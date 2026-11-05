---
id: ct-8bzh
status: closed
deps: []
links: []
created: 2026-11-02T18:22:51Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [tests, flaky]
---

# Make House naming audit tests reliable under shared machine load

Keep correct changes from failing because a shared machine is busy. Two `test_audit_acceptance` cases exceeded a 10-second child-process limit during a full lane on `1499dae7` alongside model work on November 2; all 13 passed alone. The failed boundary was the deadline, which includes process startup and scheduling as well as the tiny audit. The exact delayed phase remains unresolved.

Latest qualified shards passed on unchanged test code, so the timing defect remains open. Separate November 5 pre-pytest `doctor` import timeouts have a different control and do not establish this fix.

## Acceptance Criteria

- Preserve both real CLI entry points, normal and optimized (`-O`) Python, the two-row fixture, planted corruption and duplicate-JSON refusals, and exact error/output assertions. Avoid changing byte-hashed naming parser code for test timing.
- Give these children a shared generous hang guard based on a representative loaded run, and include the timed-out command in the failure detail. Correctness must not depend on finishing within 10 seconds. Keep fixture work bounded.
- When the flake recurs or the ticket is implemented, run the file once through its declared lane during already-admitted representative load. Use child arguments and elapsed time to locate a failure. Only if attribution is needed, compare an import-only child with the tiny audit using the same interpreter. Reuse valid evidence; do not start an unrelated heavy job merely to exercise this maintenance ticket.

[Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

## Notes

**2026-11-05T20:18:16Z**

Applied the accepted third-round scope update. The current description records the root cause, delivered work, remaining behavior and bounded checks; historical notes remain unchanged. No implementation or operational action was performed. [Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

**2026-11-05T21:17:22Z**

Merged in `030b91d6` via independently reviewed commit `a30964c4`. Both real CLI entry points keep normal and optimized Python coverage, planted corruption and duplicate-JSON refusals, and the two-row fixture. A shared 60-second guard reports the timed-out command, elapsed time and captured output. All 13 naming cases passed in a focused production-offline run under existing shared load. The slowest case took 2.33 seconds. The earlier retained log identifies two valid audit children that exceeded the original 10-second limit. [Focused evidence](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/quality/STATUS.md)
