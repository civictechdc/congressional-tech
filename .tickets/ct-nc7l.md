---
id: ct-nc7l
status: open
deps: [ct-q968, ct-adu0, ct-wjce, ct-eipa, ct-xl0y, ct-qdkd, ct-a70m, ct-n7la, ct-dmca, ct-gziq, ct-sb0s, ct-3180, ct-13cn, ct-oxg6, ct-wmtx, ct-3li2, ct-cpio, ct-vt7i, ct-clvr, ct-csyg, ct-bt1q, ct-3faj, ct-lcbc, ct-mpsp, ct-csjp, ct-tcfg]
links: []
created: 2026-10-20T18:24:29Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Qualify integrated DocSpec reuse and clean up worktrees

Integrate all reviewed `ct-mi03` lanes (`codex/docspec-host-transport`, `codex/docspec-keyed-updates`, `codex/docspec-typed-preparation`, and the unified `docspec-rs` `main` binary from `ct-oxg6`) into `codex/docspec-reuse-integration` after independent review. Compare aggregate cost on the same fixture with exact values, IDs, mappings and historical reads; record limits without extrapolating fixture timings to production.

## Acceptance Criteria

- All child tickets in `deps` are either closed with measured before/after evidence and independent review, or explicitly recorded with their scoped architectural decision (`ct-eipa`, `ct-csyg`).
- Local Python and native (`docspec-rs` `main`) test suites pass at the final merged head against the single frozen `ct-oxg6` binary.
- Aggregate qualification report distinguishes execution batch size, row-group size, and target file size, and records combined parent/child RSS, actual DuckDB/DataFusion spill, decoded rows/bytes, and old/new retained bytes.
- Prune/archive completed task worktrees (`docspec-host-transport`, `docspec-keyed-updates`, `docspec-typed-preparation`, `docspec-reuse-integration`; note: `docspec-rs` secondary worktrees were already unified onto `main` `298053b` and pruned on 2026-10-20).
- Do not restart production migration, mutate dirty UI/news-lake files on primary `congressional-tech` `main`, or close `ct-2ukk` without its separate production evidence.

## Notes

**2026-10-20T19:00:10Z**

Storage qualification must distinguish execution batch size, row-group size and target file size; include combined parent/child RSS, actual spill and old/new retained bytes. No page-index/Bloom/delete-file feature claims unless the pinned reader consumes them safely. Local scan-byte counters omit catalog/manifests/retries; provider costs require separate bounded evidence.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit expanded `deps` to include all 22 child tickets of `ct-mi03` (adding `ct-wjce`, `ct-xl0y`, `ct-3180`, `ct-3li2`, `ct-cpio`, `ct-vt7i`, `ct-clvr`, `ct-csyg`, `ct-bt1q`, `ct-3faj`) so no unreviewed child can bypass the integration gate. Recorded that all 4 secondary `docspec-rs` worktrees are already unified on `docspec-rs` `main` (`298053b`) and pruned.
