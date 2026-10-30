---
id: ct-2wsw
status: closed
deps: []
links: [ct-mpsp, ct-vt7i, ct-wmtx, ct-9at7, ct-p6aq, ct-4g55, ct-8v02, ct-jnw5, ct-15wc, ct-bs70, ct-lvvr, ct-zika, ct-qyey, ct-4zer, ct-m9ry, ct-o6d1, ct-2bhh, ct-rrfm, ct-xl0y, ct-wjce, ct-sv16, ct-lcbc]
created: 2026-10-24T18:15:54Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-98sm
---
# WS11: freeze browser and performance work

No browser, viewer or engine performance work, and no new performance counters, until there is a user or a measured failure on real data. Existing sound code stays ("don't extend, don't revert"). The broken public viewer is fixed by WS6's end-to-end check, not separately.

First move: delete `measure_publication_control.py` (it imports test fixtures). The other measurement scripts go as their subjects go: journal-route costs with WS6, browser benchmarks with the freeze, v6 preparation and v1 alias scripts with WS6, incremental catalog scripts with WS7.

## Acceptance Criteria

- `measure_publication_control.py` and its test are deleted.
- Each script group in the plan's WS11 table is deleted with its subject, with its tests (723 lines in total).
- `benchmark_core_rebuild.py` (Step 0) and `compare_raw_keyed_updates*.py` stay.
- R-check 1.


## Notes

**2026-10-30T16:49:25Z**

Verified completed under docs/plans/simplification-plan-20261024.md §6.1.11 and docs/plans/bindings-20261025.md §6 (F5 G15, commits f619d529 and a0eaac9a): measure_publication_control.py, benchmark_core_rebuild.py, and test_core_benchmark.py were deleted.
