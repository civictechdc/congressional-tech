---
id: ct-9wl3
status: closed
deps: []
links: [ct-adtz, ct-aapl]
created: 2026-11-01T10:37:52Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [regression, tests, review-provenance, capture-scheduler, imports]
---
# Resolve 3 pre-existing commit 12ac8bf2 test regressions uncovered by 5-suite cross-cutting validation

Cross-cutting 5-suite regression validation (9,734 tests) uncovered 3 pre-existing test failures on HEAD (commit 12ac8bf2 'Implement evidence-bound corpus recovery and durable acquisition'):
1. packages/viewer_publication/tests/test_review_provenance.py::test_cli_writes_only_reviews_prefix_and_rejects_duplicates: commit 12ac8bf2 changed _put_identical in review_provenance.py to return silently on identical existing bytes rather than raising ValueError('Refusing to overwrite existing review provenance object...').
2. packages/congress_api/tests/test_capture_review_contract.py::test_discovery_bound_drains_existing_queue_and_reports_real_resource_stop[9]: commit 12ac8bf2 switched AdmissionBudget request accounting from pre-reserving MAX_HOPS=3 per URL (3*3=9) to charging actual wire hops (1 per non-redirect URL), so request_budget=9 admits all 5 URLs instead of stopping after 3.
3. packages/congress_api/tests/test_congress_api_imports.py: commit 12ac8bf2 introduced a module import flagged by the congress_api import-hygiene test.

## Acceptance Criteria

1. Reconcile review_provenance.py duplicate-object handling with test_review_provenance.py::test_cli_writes_only_reviews_prefix_and_rejects_duplicates so append-only provenance guarantees and idempotent replay semantics are explicit and tested.
2. Reconcile test_capture_review_contract.py::test_discovery_bound_drains_existing_queue_and_reports_real_resource_stop request_budget parameterization with per-hop wire request accounting in capture_scheduler.py.
3. Resolve the import violation in test_congress_api_imports.py.
4. All 3 tests pass under uv run pytest.


## Notes

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 5 Engineer (4c90d67e, 99% confidence) & Cluster 2 Engineer (b009d889, 100% confidence) across Round 1 & Round 2:
  1. Updated `test_review_provenance.py:66-80,195-208` to test both idempotent identical-byte replay and fail-closed `RuntimeError` on conflicting bytes.
  2. Parameterized `budget` in `test_capture_review_contract.py:170-193` to `[100, 3]` matching per-hop wire request accounting in `capture_scheduler.py`.
  3. Moved `durable_json` into `retention/provenance.py:237-246` (`acquisition -> retention`), inverted `parsers/text.py` -> `lake/pdf_text.py` (`lake -> parsers`), and removed `SCOPED_IMPORTS` from `test_congress_api_imports.py` (`49 passed` across all 3 test files with zero import-fence exemptions).
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (100%), Green Team PASS (100%), Greybeard PASS (100%), Evolutionary Refactoring PASS (99%).
