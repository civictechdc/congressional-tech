---
id: ct-pyai
status: closed
deps: []
links: []
created: 2026-11-11T00:14:12Z
type: bug
priority: 2
assignee: mikewolfd
tags: [engine, docspec, query]
---
# Engine: a job query's JSON rows keep only the last of same-named columns, in name order

Measured on the pinned engine (b0342a7), 2026-11-10 by the W4 builder. A job query serializes each result batch with arrow's JSON writer (JsonArray, one object per row) and parses the whole buffer back with serde_json::from_slice into a Value (src/job/query_result.rs:58-76, fn query at :50). serde_json's default map sorts its keys and an object with a repeated key keeps the last value. So `SELECT k.sha, c.sha FROM k LEFT JOIN c ON c.sha = k.sha` and `SELECT *` over that join return one `sha`: the right side's NULL replaces the left key, silently. Every result also comes back with its columns sorted by name. Evidence: .cache/archive-release/investigations/docspec-feedback-20261110/refactor/query-helper/qh_probe3.out (dup-rows: [{sha: a}, {sha: null}]) and qh_probe4.out. The result is also charged to the memory pool at many times its JSON size (a batch reserves 8 times its array memory, :69-71; a 2 MiB result passed 32 MB allocated under a 64 MiB pool, qh_probe6.out). Pipeline side (claude/dx-query-helper, W4): provenance.query plans the statement with EXPLAIN FORMAT pgjson in the same job, refuses repeated output names and puts rows back in the statement's order. Existing run_job callers with ad hoc queries get no such check.

## Acceptance Criteria

The engine refuses a query whose result schema repeats a field name (or returns rows with an ordered column list, or Parquet results as X4 proposes), with a test on the one line. Then the pipeline's pgjson check in provenance.query_result can go.


## Notes

**2026-11-11T14:30:07Z**

validated 2026-11-11, left open: the engine side is unchanged on dx/one-line 8db7ebb (no refusal of repeated output names in src/job/query_result.rs). Only the pipeline guard exists: provenance.query's pgjson check (W4, on main since 623b6a63). Remains: the engine change and a test on the one line, then removing the pipeline check.

**2026-11-12T16:00:00Z**

Closed with Pin 2 (`docspec-rs` `e3d9092a6393e654efe221d662a76daf8fd56ca5`, hosted CI run `43238636122` 7/7 green) and CT caller cleanup on `claude/ct-wave-2-pin2`.
- Engine fix (`docspec-rs` commits `9de11eb` and `edf364e` in `src/job/query_result.rs`, `src/job/retained.rs`, `src/job/prepare.rs`, and `src/engine/managed_job/execution.rs`): `docspec` now refuses any job query whose output schema repeats a field name before execution with `invalid_sql` (`duplicate output column name "..."`), records `columns: Vec<String>` in exact SQL projection order on `QueryResult`, and replaces the `8x` JSON buffer over-reservation with exact Arrow + serialized-buffer reservation against the memory pool.
- CT caller cleanup (`packages/congress_api/src/congress_api/retention/provenance.py`, `packages/congress_api/src/congress_api/lake/tables.py` `table_columns`, `scripts/dev.py`, `packages/congress_api/tests/test_provenance_job.py`, `.github/tests/test_dev_environment.py`): removed the extra `EXPLAIN FORMAT pgjson` planning query from `provenance.query_result` and `provenance.explain`, eliminated redundant `result.json` re-parsing in `_query_job`, and migrated `tables.table_columns` to `SELECT * FROM t LIMIT 0` via `query_result` (preserving schema order even on empty pins). Verified in `test_provenance_job.py` and `test_lake_tables.py` and on published `witnesses.parquet` (`witness_key = 'd0b690cee4b9bda7'`) in `.cache/archive-release/release-20261112-pin2/benchmarks/verify_horizontal_slice.py`.
