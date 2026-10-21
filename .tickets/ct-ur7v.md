---
id: ct-ur7v
status: closed
deps: []
links: [ct-mi03, ct-ur2y]
created: 2026-10-21T14:41:26Z
type: task
priority: 2
assignee: mikewolfd
tags: [news_lake, docspec, architecture]
---
# Consolidate news_lake production runtime onto DocSpecLake/DocSpecNewsViews and scope PyIceberg coordinator as test oracle

The architectural table audit identified that packages/news_lake maintains two parallel storage and view engines for the same 10 raw tables and 2 derived views (politician_articles, coverage_daily): (1) PyIceberg (storage/catalog.py, storage/coordinator.py) + Python full-memory view recomputation (analysis/views.py), and (2) DocSpecLake + DocSpecNewsViews (storage/docspec_backend.py) using native RefreshTransform::Join (preserving list<struct> occurrences) and RefreshTransform::Aggregate (using native CollectSet and CountDistinct). Maintaining two production engines for the same 12 tables splits authority.

## Design

Make DocSpecLake and DocSpecNewsViews the default production backend in packages/news_lake/src/news_lake/cli.py while explicitly scoping storage/coordinator.py and analysis/views.py as the reference differential test oracle (used by tests/test_docspec_backend.py to prove C1-C5 contract equivalence). Document this single-production-owner + reference-oracle boundary in packages/news_lake/docs/.

## Acceptance Criteria

- news_lake CLI defaults to the DocSpec backend for production ingestion, view materialization, and C5-authorized export.
- PyIceberg coordinator.py and Python analysis/views.py are retained as the reference oracle for differential parity tests.
- All news_lake contract, backend parity, and CLI tests pass.

