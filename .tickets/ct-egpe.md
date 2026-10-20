---
id: ct-egpe
status: closed
deps: [ct-oxg6]
links: [ct-q968, ct-bt1q, ct-3faj]
created: 2026-10-20T22:15:53Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Share the configured DocSpec client across archive and news

The news adapter duplicates runtime startup, temporary-file transport and schema conversion, defaults to a mutable debug binary, and removes producer files after uncertain requests. Reuse the maintained archive client and inject one pinned runtime; keep news merging and publication policy in news_lake.

## Acceptance Criteria

- Migrate both packages to one owner for host readiness, deadlines, EOF draining, exact-pin streaming and unknown-outcome Build/Update input custody. Keep feature request builders thin.
- Preserve explicit application schemas, UInt64, actual Decimal values, nested null/empty/duplicate values and error meaning; do not infer every Decimal as UInt64.
- Remove news free-port probing, mutable developer binary defaults, duplicated conversion, and temporary Arrow read files after caller migration.
- Test both actual callers locally with the same frozen binary; measure process count, copied/read bytes and memory. Preserve ongoing primary news/UI edits.


## Notes

**2026-10-20T22:15:53Z**

2026-10-20 adoption review: packages/congress_api/src/congress_api/retention/docspec.py and primary packages/news_lake/src/news_lake/storage/docspec_backend.py. Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.
