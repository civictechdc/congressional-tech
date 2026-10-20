---
id: ct-nloa
status: closed
deps: [ct-egpe]
links: [ct-eipa, ct-csyg]
created: 2026-10-20T22:15:53Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Bound news upsert reads to the incoming IDs

DocSpecLake._commit_upsert materializes the entire selected dataset to merge one poll. Use the maintained native keyed selection/update path when available, or the existing bounded application routing approach; preserve the news evidence-union and late-arrival rules.

## Acceptance Criteria

- Fetch only affected existing IDs from one exact release; keep _merge_upsert policy in news. No new general-purpose query engine or second lifecycle store.
- Preserve ordered evidence unions, earlier first_seen_at, later recorded_at, optional fields and same-ID replay/conflict behavior.
- Test a fixed poll with 1x and 10x unrelated records; measure actual payload reads, bytes, memory and writes, not just returned row count.
- Current HTTP reads have no public filter API: qualify an upstream capability before using it, never invent an endpoint or claim internal pushdown supplies one.


## Notes

**2026-10-20T22:15:53Z**

2026-10-20 adoption review: packages/news_lake/src/news_lake/storage/docspec_backend.py (primary checkout). Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.
