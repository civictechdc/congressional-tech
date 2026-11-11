---
id: ct-pyai
status: open
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
