---
id: ct-nc7l
status: open
deps: [ct-q968, ct-adu0, ct-eipa, ct-qdkd, ct-a70m, ct-n7la, ct-dmca, ct-gziq, ct-sb0s, ct-13cn, ct-oxg6, ct-wmtx]
links: []
created: 2026-10-20T18:24:29Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Qualify integrated DocSpec reuse and clean up worktrees

Integrate supported changes after independent review. Compare aggregate cost on the same fixture with exact values, IDs, mappings and historical reads; record limits without extrapolating fixture timings to production.

## Acceptance Criteria

Local tests and maintained native execution pass at final merged head. Preserve before/after evidence, open unsupported-feature tickets honestly, merge reviewed commits, archive only task worktrees. Do not restart production migration or close ct-2ukk without its separate production evidence.


## Notes

**2026-10-20T19:00:10Z**

Storage qualification must distinguish execution batch size, row-group size and target file size; include combined parent/child RSS, actual spill and old/new retained bytes. No page-index/Bloom/delete-file feature claims unless the pinned reader consumes them safely. Local scan-byte counters omit catalog/manifests/retries; provider costs require separate bounded evidence.
