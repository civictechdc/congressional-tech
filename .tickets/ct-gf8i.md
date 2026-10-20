---
id: ct-gf8i
status: closed
deps: [ct-jo8n]
links: [ct-csjp, ct-vt7i, ct-gziq]
created: 2026-10-20T22:15:53Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Adopt typed native news joins and incremental coverage summaries

News already uses native Date32 grouping and CountDistinct. Finish the remaining view work: typed occurrence spans instead of JSON, changed bridge rows instead of full rematerialization, and native repeated-text group membership using qualified deterministic set aggregation.

## Acceptance Criteria

- Use list<struct> mention occurrences end to end; compare Unicode offsets, span merging, null/empty/duplicate values and nested exports against the current domain reference.
- Update only changed entity_roots, selected_mentions and survivor_items, then Refresh against exact old/new inputs. Preserve identity decisions, selected runs, survivor rules and join cardinality.
- Coverage must list groups repeated across distinct item IDs anywhere in the corpus, then associate them with each date bucket; preserve cross-date syndication, same-item duplicates, undated buckets and sorted output. A per-day CollectSet alone is wrong.
- Native 22a804e includes CollectSet in local Refresh, producing sorted unique non-null lists. Verify this operation on the intended backend; remove JSON conversion and the second full Python survivor scan only after full/incremental parity and hot-group resource checks.
- Measure bridge rows rebuilt, payload read/written and aggregate memory/spill; existing CountDistinct/Date32 use is not a new adoption claim.


## Notes

**2026-10-20T22:15:54Z**

2026-10-20 adoption review: packages/news_lake/src/news_lake/storage/docspec_backend.py (primary checkout). Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.
