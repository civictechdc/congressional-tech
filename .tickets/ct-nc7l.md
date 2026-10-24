---
id: ct-nc7l
status: closed
deps: [ct-q968, ct-adu0, ct-wjce, ct-qdkd, ct-n7la, ct-oxg6, ct-bt1q, ct-3faj, ct-egpe, ct-ccy4, ct-m9td]
links: [ct-m9td, ct-egpe, ct-qdkd, ct-3faj, ct-a70m, ct-q2ht, ct-7uit]
created: 2026-10-20T18:24:29Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Qualify the integrated application runtime and archive update path

Qualify the reviewed common runtime, typed preparation and archive consumer integration at one exact application head. Keep optional news feature work in its own dependent tickets so it does not force a big-bang archive migration.

## Acceptance Criteria

- Test the actual shared client and archive/catalog/viewer callers locally against one frozen native binary. Preserve every source/document value, mapping, review decision and old pin.
- Include process loss, uncertain submission, prepared-phase replay, stale writer and zero-write no-op; the preparation positive-spill gap must have real evidence.
- Record aggregate parent/child memory, staging/spill, requests and bytes; fixture latency is not production/R2 throughput. Reuse accepted checks unless a changed path warrants rerun.
- Review, commit and integrate owned changes, preserve ignored evidence, then archive only completed owned worktrees. Preserve primary UI/news work and unrelated checkouts.
- Production snapshot import/cutover remains ct-2ukk. Do not claim all optional feature adoption complete when only core integration passes.

## Notes

**2026-10-20T19:00:10Z**

Storage qualification must distinguish execution batch size, row-group size and target file size; include combined parent/child RSS, actual spill and old/new retained bytes. No page-index/Bloom/delete-file feature claims unless the pinned reader consumes them safely. Local scan-byte counters omit catalog/manifests/retries; provider costs require separate bounded evidence.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit expanded `deps` to include all 22 child tickets of `ct-mi03` (adding `ct-wjce`, `ct-xl0y`, `ct-3180`, `ct-3li2`, `ct-cpio`, `ct-vt7i`, `ct-clvr`, `ct-csyg`, `ct-bt1q`, `ct-3faj`) so no unreviewed child can bypass the integration gate. Recorded that all 4 secondary `docspec-rs` worktrees are already unified on `docspec-rs` `main` (`298053b`) and pruned.


**2026-10-20T22:19:32Z**

2026-10-20 fresh application adoption review at app 34c1ee7 / engine 9661026. Scope is congressional-tech using an upgraded engine, not reimplementing native lifecycle. Actual local/R2 capability must pass before use; unsupported upstream work remains linked evidence, not a completion claim. See docs/plans/docspec-application-adoption-20261020.md.

**2026-10-20T23:32:30Z**

Reopened by evolutionary-refactoring audit at `main` (`8221566d`):
1. `ct-nc7l` depends on `ct-egpe` (shared client across archive and news plus `update_table` / `deletions.parquet` producer-input custody in `NativeDatasets`), which remains open.
2. Reconciled dependency policy: `ct-nc7l` intentionally gates core runtime, shared client (`ct-egpe`), preparation/spill (`ct-adu0`, `ct-wjce`, `ct-n7la`, `ct-ccy4`), operator inspection (`ct-qdkd`), and host safety (`ct-oxg6`, `ct-q968`, `ct-bt1q`, `ct-3faj`), while optional news feature tickets (`ct-qkvr`, `ct-nloa`, `ct-5fkx`, `ct-jo8n`, `ct-gf8i`, `ct-4nyy`) do not block archive qualification.

**2026-10-21T02:20:25Z**

Qualified integrated application runtime (docspec-rs 96e38262 / SHA-256 9a9f9952), shared docspec_client transport, typed preparation + positive spill, operator status/retention protection, and archive/news callers across 176 passing local tests.

## Audit 2026-10-24

- Verdict: PARTIAL (batch mi03b).
- Grades: proposal 75 → 65, work 68 → 68.
- Problem: AC3 ("record aggregate parent/child memory, staging/spill, requests and bytes") has no record for the integrated head.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03b/mi03b-verdicts.md:21
- Status: Closed as superseded by the simplification plan (Step 0 ct-q2ht, WS7 ct-7uit): qualifying the Python incremental update path is replaced by Step 0's rebuild baseline and WS7's engine prototype on real data.
- See docs/reviews/2026-10-24-ticket-audit/README.md
