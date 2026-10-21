---
id: ct-oc2g
status: open
deps: [ct-2ukk]
links: [ct-2ukk, ct-czsd, ct-a3le, ct-8ax6, ct-xu1o, ct-dzyf, ct-aia9, ct-sb0s, ct-te1p, ct-13cn, ct-n6lj, ct-mi03, ct-dmca, ct-8kl2, ct-gziq, ct-gi01, ct-2yl5, ct-bwac]
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

## Notes

**2026-10-21T16:40:00Z**

Verified that `.github/workflows/deploy-pages.yml:79-96` already checks out `pipeline-data` at root `path: pipeline-data` (outside `apps/site/public/`) and stages only `pipeline-data/committee-explorer/public` into `apps/site/public/data/explorer`. Remaining scope gated on `ct-2ukk`: retire the runtime `catalog-v5.ts` fallback in `apps/site/src/lib/duckdb.ts` once live v6 cutover completes.


## Notes

**2026-10-21T15:55:59Z**

Cross-skill validation + code inspection (main 9e5cf42e): the cited path apps/site/src/lib/duckdb.ts does not exist (apps/site/src/lib/ contains only paths.ts); the v5/v6 parsers live at apps/site/src/components/explorer/reader/filenames/. Cleanup scope is deeper than removing a runtime fallback: catalog-v6.ts:14 imports rangeFile, sourceContext, savedCopyUrl, apiReference and videoReference from catalog-v5.ts, and catalog.ts:3-5 imports and re-exports both parsers. Extract those five helpers before deleting v5, or v6 breaks.
