---
id: ct-4zer
status: open
deps: [ct-2d3k]
links: [ct-d3un]
created: 2026-10-19T16:40:41Z
type: task
priority: 2
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
