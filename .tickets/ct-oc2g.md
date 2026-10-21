---
id: ct-oc2g
status: open
deps: [ct-2ukk]
links: [ct-2ukk, ct-czsd]
created: 2026-10-21T14:41:26Z
type: task
priority: 3
assignee: mikewolfd
tags: [viewer_publication, site, ci, cleanup]
---
# Retire legacy catalog-v5.ts browser parser and decouple deploy-pages.yml pipeline-data staging after ct-2ukk cutover

The Table Audit and Chesterton's Fence Audit identified two remaining transitional artifacts: (1) apps/site/src/lib/duckdb.ts and packages/viewer_publication/src/catalog-v5.ts retain the legacy v5 monolithic/partitioned browser manifest parser alongside the native v6 parser (catalog-v6.ts), and (2) .github/workflows/deploy-pages.yml stages 7 intermediate pipeline tables (house-hearings, senate-hearings, crs-products, gao-reports, cbo-publications, committee-RollCall, unresolved-links) under apps/site/public/pipeline-data/ during build-coverage.py before deleting them prior to Pages upload.

## Design

Gate this cleanup on completion of ct-2ukk (live v6 cutover qualification). Once ct-2ukk closes and public-data/catalog.json is on version 6: (1) remove catalog-v5.ts runtime fallback from apps/site/src/lib/duckdb.ts (moving v5 fixture tests to historical compatibility tests if needed), and (2) move deploy-pages.yml intermediate Parquet staging for build-coverage.py out of apps/site/public/ into a dedicated runner scratch directory so intermediate tables never enter the Astro public asset tree.

## Acceptance Criteria

- Blocked on ct-2ukk completion.
- deploy-pages.yml stages intermediate pipeline Parquet inputs in a scratch directory outside apps/site/public/.
- apps/site/src/lib/duckdb.ts requires version 6 native catalog manifests in production while preserving historical test coverage.

