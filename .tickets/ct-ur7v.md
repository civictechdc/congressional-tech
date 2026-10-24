---
id: ct-ur7v
status: open
deps: []
links: [ct-mi03, ct-ur2y, ct-nloa, ct-xu1o, ct-8ax6, ct-pgxn, ct-r60e, ct-qkvr, ct-d8cf]
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

## Notes

**2026-10-21T16:40:00Z**

Implemented in `b28cc9b7`: created `packages/news_lake/src/news_lake/cli.py` (`publish`, `views --verify-oracle`, `export`, `compact-lifecycle`), wired `news-lake = "news_lake.cli:main"` in `packages/news_lake/pyproject.toml`, exported `DocSpecClient`, `DocSpecLake`, and `DocSpecNewsViews` from `news_lake` and `news_lake.storage`, updated `packages/news_lake/README.md`, and verified in `packages/news_lake/tests/test_docspec_backend.py::test_news_lake_cli_publish_views_export_and_compact_lifecycle` (319/319 tests pass).


## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch standalone).
- Grades: proposal 84 → 74, work 86 → 80.
- Problem: No material finding.
- Status: Reopened: revisit under engine-first rule. It kept `analysis/views.py` as a Python oracle that re-implements the engine views. WS8 (ct-d8cf) replaces it with direct contract assertions unless the owner keeps it test-only (plan open question 6).
- See docs/reviews/2026-10-24-ticket-audit/README.md
