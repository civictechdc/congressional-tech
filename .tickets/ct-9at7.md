---
id: ct-9at7
status: closed
deps: []
links: [ct-p6aq]
created: 2026-10-18T19:28:38Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Let canceled searches stop CPU work promptly

Search scans sources/groups synchronously inside the worker. Cancellation arrives as another worker message and cannot interrupt that loop. The main thread rejects promptly, but abandoned scans still delay new worker requests.

Source: apps/site/src/components/filename-worker.mjs:4-5; filename-catalog.mjs:255-317.

## Acceptance Criteria

Process scans in bounded chunks that yield and check cancellation. Measure cancellation latency and completed work on a wide fixture, separately from throughput. Preserve same-source filter conjunction, reviewed categories, result order and late-result suppression; avoid one timer per row.

<!-- grade-followup:start -->
## Grade review follow-up

Cover both scalar/group scans and observation-search loops using the actual worker message boundary; preserve same-source and reviewed search semantics.

- Bound work between event-loop yields and measure cancellation latency separately from throughput.
- Reference results/totals/order, review pins, null filters and same-source conjunction remain exact; no timer per row.

[Function scope and checks: 5 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:244). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:20:46Z**

Bound scalar/group scans at 512 visits per event-loop yield; observation/reference loops count work across blocks and long lists. Direct work-count checks plus actual worker cancellation and immediate info requests pass, late canceled replies suppressed. Fixture latency/work and throughput boundary documented in browser.md. 17 focused checks passed.
