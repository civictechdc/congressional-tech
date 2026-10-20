---
id: ct-jo8n
status: closed
deps: [ct-qkvr, ct-nloa]
links: []
created: 2026-10-20T22:15:53Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Wire native news ingestion and views to exact published releases

The alternative news backend is exercised by tests but has no maintained non-test caller. Its view builders repeatedly read independent latest heads and retain committed members only in memory. Connect it to the existing news ingestion/release path while preserving C1-C9 and I1-I6.

## Acceptance Criteria

- Obtain the reviewed news changes from their owner; integrate through the existing coordinator and reader entry points without overwriting primary UI/news work.
- Capture one complete exact input set; propagate returned pins through bridges, joins, aggregates and assembly. Use native input capture/generation sealing/dependency corrections where they prove the required relationships. Preserve explicit empty members and all required release tables.
- Retain the application release, availability, cursor and rights-policy authority; never substitute native latest or add a second mutable selector.
- Test fresh-process resume, partial ingestion, concurrent input advance during assembly, stale seal, changed dependency and lost publication response. The previous release stays usable; declared release matches every value read.
- Exercise the actual command/service caller and retired-release refusal before removing superseded backend routes; migration preserves old snapshots and mappings.


## Notes

**2026-10-20T22:15:54Z**

2026-10-20 adoption review: packages/news_lake/src/news_lake/storage/docspec_backend.py (primary checkout). Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.
