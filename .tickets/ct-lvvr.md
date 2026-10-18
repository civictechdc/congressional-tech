---
id: ct-lvvr
status: in_progress
deps: []
links: [ct-p6aq, ct-zika, ct-p6ns]
created: 2026-10-18T19:25:28Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Bound shared browser caches and deduplicate first loads

Decoded-column caching retains four complete columns by count without a byte budget. Compressed range caches are limited per file, not across the reader. Concurrent first callers can also duplicate table and observation-store initialization.

Source: apps/site/src/components/filename-catalog.mjs:69-93,163-175,202-213,242-254. These are static scaling findings, not measured browser OOMs.

## Acceptance Criteria

Use an explicit aggregate retained-byte budget and share in-flight loads for the same table, column and observation store. A synthetic wide-column fixture must respect that budget. Failed loads evict; canceling one caller must not poison others. Preserve results and fidelity, and measure requests/decodes before and after.

<!-- grade-followup:start -->
## Grade review follow-up

Include concurrent ranges/table/columns/store, a monotonic row-group cursor, normalized-value copy accounting and optional decoded-reference/search representations within explicit retained-byte budgets.

- Account for compressed and decoded retained bytes separately from transient decode/worker-clone allocations.
- Concurrent callers share accepted loads; independent cancellation and failure eviction work.
- All new shard/reference/normalized caches have bounded admission/eviction and immutable-catalog ownership; wide-column fixtures preserve exact values.

[Function scope and checks: 13 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:493). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:15:45Z**

Implemented shared per-reader compressed/decoded byte budgets, shared in-flight ranges/tables/columns/observation stores, failed-load eviction and independent cancellation. Wide fixture exact fallback and cold/warm counters documented in docs/experiments/publication-remediation/browser.md; cache/catalog suite 16 passed.

**2026-10-18T23:20:12Z**

Reopened after exact closed-publication browser probe attempt-1: technical first-row cold19.086s/warm17.435s preserved352fields but reparsed metadata45times each (tableLoads45->90), despite warm0HTTPrequests. Parsed metadata exceeds64MiB decodedcache admission; source_url search timedout120s. Preserve existing cache budgets; reuse operation-owned table metadata across chunks/rowgroups without permanent retention. Receipt: primary output/publication-remediation-20261018/rollout/browser-layout-check/attempt-1/receipt.json. Frozen backend2feb8c7 complete qualification remains separate and intact.
