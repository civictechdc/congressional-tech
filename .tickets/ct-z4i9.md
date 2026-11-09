---
id: ct-z4i9
status: open
deps: []
links: []
created: 2026-11-09T02:50:56Z
type: bug
priority: 1
assignee: mikewolfd
tags: [perf, lake, daily]
---
# HTML-metadata backfill commits one readings row per catalog commit

Measured 2026-11-09: nightly 20261109T002515Z's html_metadata scoped backfill appended 293 readings snapshots carrying 293 rows (one row per Iceberg commit) between 00:33Z and 01:49Z before the watchdog stopped it for low disk. The 20261108T193702Z run made 135 commits for 173 rows. Each commit is a catalog round-trip, so the step is slow (tens of minutes) and every commit is another chance at the catalog connect timeout that orphaned producer records (ct-8unc). Evidence: .cache/archive-release/nightly/candidate/archive-daily/html_metadata-scoped/readings/batch-*/append/result.json and implementation/nightly-producer-recovery-20261108/check-*.json. Owner decision 2026-11-08 (questions tool): 'Ticket and fix next'.

## Design

Measure first: why each batch holds one row (batch_size, scope ordering, per-body batching in readings.run / produce_html_metadata). Then accumulate parsed rows and append once per run or per size bound (engine-first; no custom catalog code). Keep per-batch work dirs for resume. Big O: commits should scale with output bytes / size bound, not with rows.

## Acceptance Criteria

1) A measurement names the cause with numbers. 2) A nightly-equivalent backfill of N rows makes at most ceil(bytes/bound) commits; test proves it. 3) Producer records and gate 5 still pass (ct-8unc semantics unchanged). 4) Wall time of the html_metadata step measured before/after on the same scope.

