---
id: ct-d0o0
status: open
deps: []
links: [ct-77zb, cef-nkzp, ct-h1nd, ct-sh4j, cefr-7sar, ct-kac4]
created: 2026-11-01T17:43:18Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [testing, datafusion, captures, committees, phase2]
---
# Add fast production-offline gate for receipt-envelope variety, committee reference keys, and SQL pre-aggregation semi-join pushdown

Catch real-corpus receipt envelope shapes, House select/task-force committee code mappings, and unfiltered DataFusion captures/readings aggregations in <5s during production-offline pytest runs before launching full pipeline runs.

## Design

1. Add packages/congress_api/tests/test_corpus_variety_gate.py with a compact fixture containing one anonymized line from every distinct historical receipt envelope shape across the 2,292 production receipts (including 2026-10-12 nested error: {"type": "http_error"} dicts on prior_attempts, prior_attempts slots 0..3, Zyte provider_response, previous_receipt, and Wayback container lines) and assert 100% parity between captures.py and capture_backfill_guard.validate_generation.
2. In test_corpus_variety_gate.py, cross-check normalize_house_committee_code (_HOUSE_SELECT_CODES and task-force mappings in meeting_records.py) against all hl* and ht* codes in reference committees data so missing_committee_keys cannot regress.
3. Add packages/viewer_publication/tests/test_sql_plan_guards.py inspecting all model/sql/*.sql and archive_model.py queries to forbid FROM captures or FROM readings GROUP BY / DISTINCT CTEs that do not join a candidate_* SHA CTE or selective filter.

## Acceptance Criteria

- Both new test modules are enrolled in test-suites.toml (production-offline) and execute in <5s total.
- Reverting the nested-error fix in captures.py, removing any hl*/ht* code from normalize_house_committee_code, or removing candidate_*_shas joins from appearance-records-resolved.sql / meeting-records-resolved.sql / archive_model.py deterministically fails the gate.

