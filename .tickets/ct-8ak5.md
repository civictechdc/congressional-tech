---
id: ct-8ak5
status: open
deps: []
links: []
created: 2026-10-30T14:32:30Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, model, parquet, track1]
---
# T1.1: Fix Parquet sort order on witnesses, rosters, and url_variants in build_prepared_release

Fix Parquet sort order on 3 release files in packages/viewer_publication/src/viewer_publication/archive_model.py (build_prepared_release):
- witnesses.parquet: change ['witness_key'] -> ['occasion', 'panel_order', 'display_order', 'witness_key'] (docs/plans/phase-2-annex-20261028.md §3).
- rosters.parquet: change ['congress', 'system_code', 'bioguide_id'] -> ['system_code', 'rank', 'bioguide_id'] (docs/plans/phase-2-annex-20261028.md §3).
- url_variants.parquet: change ['canonical_url', 'variant_url'] -> ['variant_url', 'canonical_url'] (docs/engine-first-data-model.md §8.1).

## Acceptance Criteria

witnesses.parquet, rosters.parquet, and url_variants.parquet are exported in the exact sort orders required by phase-2-annex-20261028.md §3 and engine-first-data-model.md §8.1; model tests pass.

