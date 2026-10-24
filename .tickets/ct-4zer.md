---
id: ct-4zer
status: closed
deps: [ct-2d3k]
links: [ct-d3un, ct-2wsw]
created: 2026-10-19T16:40:41Z
type: task
priority: 1
assignee: mikewolfd
tags: [overlap-followup]
---
# Measure broad browser search cost and choose a bounded improvement

Arbitrary-field and observation searches still scan whole source columns or all logical blocks/reference lists. The retained current-catalog source-URL case completed in 27.523s; admitted-text fixture savings do not establish good broad-search latency. Full physical Parquet chunks, active column arrays, masks and exact fallback are distinct costs. Evaluate the smallest change that reduces measured repeated work without introducing another unsupported query path.

## Acceptance Criteria

- Reuse saved current-catalog baseline receipts; do not rerun acquisition or expensive qualification just to establish the known baseline. Define a representative case set and latency/resource target before a new bounded experiment.
- Separate transfer, Parquet metadata/physical chunk decode, normalization, source/group scan and observation/reference scan costs; report cold/warm time, work counters and peak active/retained estimates.
- Compare a bounded candidate such as row-group consumption or a narrowly justified prepared index against exact scan behavior; preserve arbitrary fields, same-source AND, Unicode/nested/null JSON search, review/recovery overrides, order and numeric paging.
- Preserve cooperative cancellation and independent shared waiters; keep one supported search route or document a measured reason for any added representation. If no improvement meets the target, retain the scan and record the measured bottleneck and decision.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: apps/site/src/components/filename-catalog.mjs:10:text, apps/site/src/components/filename-catalog.mjs:194:read, apps/site/src/components/filename-catalog.mjs:242:column, apps/site/src/components/filename-catalog.mjs:255:search, apps/site/src/components/filename-observations.mjs:67:scan, apps/site/src/components/filename-observations.mjs:81:matchingSources. See docs/package-overlap-rescore-20261019.md for the full grade map.

**2026-10-19T16:56:07Z**

Prioritized for efficiency and architectural debt per user direction. Require measured work/resource changes and simpler ownership; preserve behavior and data.

**2026-10-19T19:30:36Z**

Measured exact merged3757f55 against bounded row-group candidate on8192 synthetic sources/4096 groups,32 source groups,5 cases x cold/warm x3. All30 result hashes match; warm normalization8192→0 but wide warm latency32.24→32.27ms, cold wide+27%/AND+30.7%; decoded cache19.10→34.51MB and RSS171.62→179.62MB. Candidate misses unchanged target and is reverted; retain current exact scan.104 focused filename tests pass. docs/experiments/efficiency-debt/search.md and search-evidence.json bind receipts under primary output/efficiency-debt-20261019/search/. Remains in_progress pending independent review; no full catalog/live qualification.

**2026-10-19T19:39:00Z**

Independent review accepted the measured retain-current decision at 9918394. All 30 paired results match; cache candidate misses the latency target and increases memory. Production search remains unchanged; 104 retained checks pass.

## Audit 2026-10-24

- Verdict: SUPERSEDED (batch standalone).
- Grades: proposal 82 → 70, work 75 → 75.
- Problem: The fixture was 8,192 synthetic sources (~0.5% of the 1.68M-row catalog whose search took 27.5 s), so it can't see the real bottleneck; the doc admits none was profiled.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/standalone/standalone-verdicts.md:35
- Covered by: WS11 (ct-2wsw).
- See docs/reviews/2026-10-24-ticket-audit/README.md
