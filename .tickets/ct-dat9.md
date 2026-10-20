---
id: ct-dat9
status: closed
deps: [ct-si9g, ct-v5kb, ct-ihve, ct-365w]
links: []
created: 2026-10-20T02:20:21Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Wire one resumable update path and retire rebuild routing

corpus_recovery/publication.py:132 enters catalog construction for publication; cli/raw_sync.py:299 passes repair=True for rebuild mode. Integrate the completed incremental boundaries rather than layering another dispatcher on these paths.

## Design

Keep the current writer ownership, conditional publication, intent/readback journal and continuation owner. Wire raw changes through catalog partitions to viewer selection. Update existing commands and workflow callers instead of adding mode flags that select a second engine.

## Acceptance Criteria

- Baseline current phase, CLI and failure behavior before edits. Inventory scheduled, local, recovery, dynamic and workflow callers; migrate required callers together.
- Provide update, resume and explicit scoped reprocessing with no operational full-rebuild fallback. Keep any full reference computation offline for tests only.
- Inject worker loss between chunks and writes. Fresh-host recovery resumes the same input/result versions; no expensive completed chunk repeats and no stale result becomes visible.
- An explicit global rule upgrade progresses through resumable batches. Keep the old consistent generation visible until the required dependency scope is complete, or prove an equally consistent versioned rollout.
- No-change and mapping-only paths perform only necessary work. Measure repeated work and writes; remove unused rebuild routing and duplicate phase logic after integration.

## Notes

**2026-10-20T07:41:04Z**

Explicit adoption, resume, rule-upgrade and renderer-upgrade CLI paths are integrated locally. Final45 CLI checks and68 runtime/workflow checks pass. Private Linux executable is pinned to source91eb44f, copied/read back from private runtime storage, and downloaded successfully through the maintained installer. GitHub descriptor and engine secret are configured; no workflow was dispatched. Hosted execution and production selection remain unverified.

**2026-10-20T16:02:11Z**

Implemented and independently reviewed: capture, recovery, adoption, source qualification, explicit upgrades and ordinary updates use the maintained native owners; operational rebuild/repair routes refuse. Resumable update and failure tests passed. Initial adoption fixes ct-9vtu/ct-y32m and actual production cutover/retirement remain required under ct-2ukk. Acceptance review: output/incremental-updates-20261019/review-merge/acceptance-20261020.md at 0382cac3. Grades: correctness A-, efficiency B+, DX B+, architecture A-. Local implementation closure does not claim production migration.
