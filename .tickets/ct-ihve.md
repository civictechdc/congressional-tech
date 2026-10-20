---
id: ct-ihve
status: in_progress
deps: [ct-v5kb]
links: []
created: 2026-10-20T02:20:21Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Update viewer assets and review bindings by stable identity

publish-filename-viewer.py:327-350 rebuilds browse rows and all ID shards. IDs resolve to shifting row positions, so an unrelated insertion can invalidate otherwise unchanged output.

## Design

Replace positional addressing at the publisher/browser boundary with stable document/source identity and reusable partitions. Keep the existing publication client, loaders and review policy. Update affected browse/search/facet contributions, recovery links and review bindings; avoid a parallel viewer service.

## Acceptance Criteria

- Characterize search/filter order, pagination, saved responses, deep links, review bindings and withdrawals before changing the representation.
- Insert/delete before existing browse entries without rewriting unrelated records. Correctly handle group merges/splits and late-loading browser requests against one pinned generation.
- Preserve unaffected reviews and prior withdrawals. Apply existing binding policy to changed groups and retain explicit reasons; do not silently change review decisions.
- Test a fresh browser and mapping-only edits. Prove mixed-generation, missing-partition and stale-cache rejection through the maintained loaders.
- Measure assets/bytes rebuilt, uploaded and downloaded for fixed changes. Reuse untouched files; remove superseded positional reader/writer paths after both sides migrate.

## Notes

**2026-10-20T04:07:17Z**

The dependency now exposes a reviewed stable logical table reader and conditional selector (main c59322d). Browser baseline: 37 JavaScript tests and 29 review/recovery Python tests passed. Dynamic viewer Catalog, publisher and browser must migrate together against stable source/document IDs; no fake Parquet compatibility layer. Final integration depends on ct-v5kb completion. Production remains unchanged.

**2026-10-20T04:22:09Z**

Implementation is active in the isolated incremental-viewer worktree against the reviewed native catalog reader and selector. Final closure still requires ct-v5kb and integrated qualification. Preserve exact historical saved links with a read-only v5 decoder; recurring writes use stable IDs and reusable v6 assets.
