---
id: ct-qkvr
status: closed
deps: [ct-egpe]
links: []
created: 2026-10-20T22:15:53Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Preserve news append history across successive native batches

DocSpecLake._commit_append sends only the new batch as an independent Build. Local Build replaces the current source result; old immutable releases survive but the current view loses prior rows. R2 refuses a later Build. Use an exact-base append/update representation that retains all earlier logical evidence.

## Acceptance Criteria

- First reproduce two distinct polls by reading the actual native result; do not supply merged Python records to hide missing history.
- Preserve append ID uniqueness: identical replay is a no-op and conflicting reuse refuses. Keep old pins readable and source bytes unchanged.
- Bind retry to exact base and content; cover lost replies, interrupted admission, stale writers and coupled relationships.
- Qualify the supported local and R2 paths; no whole-history read/rewrite for a small append. Record changed/reused rows and bytes.


## Notes

**2026-10-20T22:15:53Z**

2026-10-20 adoption review: packages/news_lake/src/news_lake/storage/docspec_backend.py (primary checkout). Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.
