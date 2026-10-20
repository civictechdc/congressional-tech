---
id: ct-nc7l
status: closed
deps: [ct-q968, ct-adu0, ct-wjce, ct-qdkd, ct-n7la, ct-oxg6, ct-bt1q, ct-3faj, ct-egpe, ct-ccy4]
links: []
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
