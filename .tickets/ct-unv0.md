---
id: ct-unv0
status: closed
deps: []
links: []
created: 2026-10-22T17:36:18Z
type: bug
priority: 0
assignee: mikewolfd
parent: ct-syem
tags: [dx, tests, scripts, viewer-publication, corpus-recovery, architecture]
---
# Fix broken scripts/dev.py inventory gate, align pytest.ini with test-suites.toml, and invert packages/* -> scripts/publication/* dependency

CS300 Audit Finding (Scripts, Root Tests & DX Auditor):
1. Broken Canonical Test Runner (scripts/dev.py inventory & scripts/dev.py test <lane>): Running .venv/bin/python scripts/dev.py inventory immediately exits with code 1 ('ERROR: Unassigned test: packages/docspec_client/tests/test_export_policy.py, test_ipc_and_merge.py') because packages/docspec_client was omitted from pyproject.toml:5-15 ([project].dependencies), test-suites.toml:21-30 ([environment.imports]) & 39-57 ([lanes.production-offline].roots), and pytest.ini:2 (testpaths). Furthermore, pytest.ini:2 omits packages/congress_shared/tests and includes docs/experiments/filename-patterns-20261015 (which fails under bare pytest without a pre-built baseline).
2. Inverted Package -> Script Dependencies & AST-Parsing Hack: Library packages packages/viewer_publication (attempt.py:94-95, plan.py:35-65, native.py:25-104) and packages/corpus_recovery (publication.py:16-68) dynamically load hyphenated CLI scripts scripts/publication/publish-viewer-r2.py and publish-filename-viewer.py via importlib.util.spec_from_file_location (also used in 37 test files). Worse, scripts/publication_preflight.py:44-54 (publisher_constants) reads publish-viewer-r2.py as text and runs ast.parse(...) to extract PREFIX, PUBLIC_URL, REVIEW_DATA_URL, and REVIEW_SOURCE!
3. Hardcoded /Users/mikewolfd/... Paths & Dead apps/site/scripts sys.path Entries:
   - 4 root test files hardcode /Users/mikewolfd/Work/spicy-stack/docspec-rs/target/debug/docspec (tests/test_native_features.py:27, test_catalog_rows.py:506, test_docspec_runtime.py:289, test_document_review_catalog.py:167) plus docs/recovery/reviews/review-root-probes/probe.py:4.
   - 16 Python files still insert the deleted Python directory ROOT / 'apps/site/scripts' onto sys.path.

## Acceptance Criteria

1. Register docspec_client in root pyproject.toml dependencies, test-suites.toml, and pytest.ini (and add congress_shared/tests while removing docs/experiments/filename-patterns-20261015 from default pytest.ini testpaths) so scripts/dev.py inventory and bare pytest pass cleanly. 2. Move reusable viewer publication, R2 transport, and release identity logic into packages/viewer_publication so packages/* never load scripts/publication/* via spec_from_file_location and publication_preflight.py:44-54 imports constants normally without ast.parse. 3. Replace all hardcoded /Users/mikewolfd/... paths with a shared conftest/docspec_client binary resolver and remove all 20 dead apps/site/scripts sys.path references.


## Notes

**2026-10-22T17:42:50Z**

Subagent Self-Review Additions:
1. pytest.ini:6 (pythonpath): In addition to pytest.ini:2 (testpaths), add packages/docspec_client/src to pytest.ini:6 (pythonpath).
2. All 6 hyphenated scripts in scripts/publication/: Explicitly migrate all 6 hyphenated scripts (publish-viewer-r2.py, publish-filename-viewer.py, apply-r2-edge-rules.py, backfill-uncompressed-pdfs.py, publish-docspec-runtime.py, filename-test-fixture.py) into packages/viewer_publication so all 37 importlib.util.spec_from_file_location call sites across packages/ and tests/ can be replaced with normal imports.
3. Additional hardcoded path citation: Also scrub docs/plans/table-audit-and-consolidation-20261021.md:1-210 (50+ hardcoded file:///Users/mikewolfd/Work/congressional-tech/... links committed to git).
