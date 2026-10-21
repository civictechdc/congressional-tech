---
id: ct-jo8n
status: closed
deps: [ct-qkvr, ct-nloa, ct-5fkx]
links: [ct-nloa, ct-qkvr, ct-5fkx, ct-f11a, ct-4nyy, ct-gf8i, ct-n6lj, ct-csjp, ct-vt7i]
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

**2026-10-20T23:32:30Z**

Reopened by evolutionary-refactoring audit at `main` (`8221566d` / `33ce7877`):
1. `packages/news_lake` still has zero non-test callers of `docspec_backend.py`: `storage/coordinator.py`, `storage/releases.py`, `analysis/views.py`, and `analysis/export.py` never import or invoke `DocSpecLake`, `DocSpecNewsViews`, or `DocSpecClient`.
2. `DocSpecLake.committed` (`docspec_backend.py:951`) and `DocSpecNewsViews.pins` (`:1127`) remain ephemeral in-memory dicts; on fresh-process resume (`DocSpecNewsViews(client)`), `_pin` (`:1151-1156`), `_bridge_pin_for_refresh` (`:1168`), and `_base_version` (`:1279`) still fall back to `client.latest(dataset)` / `client.try_latest(dataset)` instead of reading durable release-pinned versions.
3. Multi-poll generation sealing across `Update`s is blocked by `ct-5fkx` (`UpdateSpec` ignores `spec['relationship']` at `docspec_backend.py:924-925`).

**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A | Impl: D+ (Reopened). Zero non-test callers in packages/news_lake; DocSpecLake.committed (:951) and DocSpecNewsViews.pins (:1127) are ephemeral in-memory dicts that fall back to client.latest() on fresh-process resume.

**2026-10-21T02:20:25Z**

Implemented and verified: wired DocSpecLake.publish_release / read_release / find_release into news_lake.storage.releases (releases.py:183-196,290-310) and DocSpecNewsViews into news_lake.analysis.views (views.py:150-153,204-207) and news_lake.analysis.export (export.py:43-62). Added durable workspace state (.news_lake_committed.json, .news_lake_views.json, releases/<id>.json), explicit empty-table preservation across all 12 CONTENT_TABLES, and capture_inputs verification. Verified in test_published_release_lifecycle_fresh_process_resume_and_retire.
