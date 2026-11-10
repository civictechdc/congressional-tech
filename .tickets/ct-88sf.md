---
id: ct-88sf
status: in_progress
deps: []
links: [ct-w564]
created: 2026-11-10T16:19:14Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine, observability, memory]
---
# Engine evidence: name the failing statement, refuse a missing input by name, then state limits and real memory per statement

From the docspec-rs feedback root-cause analysis (causes E and D; .cache/archive-release/investigations/docspec-feedback-20261110/root-cause/PLAN.md, X2). Two phases on branch dx/engine-evidence in docspec-rs, cut from fix/nested-slice-bytes. Phase 1 (no metric event needed): the error the CLI reports names the failing step, output or query; a missing or empty Parquet input is refused before planning, naming the input and its path (today it surfaces as a SQL schema error); the three remaining error sites in src/job/json_lines.rs keep their cause; the CLI raises its soft open-file limit at start. Phase 2 (after the other session's branch reaches its final tip, because src/job/metrics.rs is held until then): a start event with the limits in force and the derived pool, shared-admission and retention-ceiling bytes; process peak memory on step, output and query events; the pool peak on output events; the shared half's lowest available per statement, beside the count of refused compaction copies; a last event naming the failed statement; after ct-qxfc, a per-step join summary. Links ct-w564, ct-64t4, ct-xnn6.

## Acceptance Criteria

Phase 1: a failing step, output and query are each named with the code unchanged; a missing input is refused naming the path while a zero-row file still works; the open-file limit rises under a low soft limit; no pipeline caller that matches engine error text breaks; engine check green; independent review. Phase 2: each new field checked against a different instrument in the prefix run (process peak against the watchdog timeline; shared low-water against the debug log; start event against the limits file). Outward: binaries, pin move.

