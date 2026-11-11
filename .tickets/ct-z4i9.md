---
id: ct-z4i9
status: in_progress
deps: []
links: [ct-1mq9, ct-yndj]
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


## Notes

**2026-11-09T16:29:56Z**

2026-11-09 (branch claude/ct-thread1-unattended): cause measured and fixed; orchestrator closes after the lane.

Cause: model/jobs/publish-daily.json set derived_scopes.html_metadata.batch_size to 1 (d2ec0211), and readings.run makes one native append per batch, so the nightly made one catalog commit per body. Measured from the batch dirs (read-only) in main .cache/archive-release/nightly/candidate/archive-daily/html_metadata-scoped/readings (the 2026-11-09 run there): 363 batches, 362 commits, 362 rows, 3.7 MB of written files. Wall 7,737 s. Commits took 7,169 s (93%), median 19.6 s each (p90 22.4 s). Parsing took 565 s, median 0.93 s per body including a worker start.

Fix: readings.run backfill takes an optional batch_bytes. A batch closes at batch_size items or once it holds batch_bytes stored bytes, so commits scale with bytes read, not rows. The daily derived pass already admits work only within max_work_items and max_stored_bytes (64 MiB). It now runs with batch_size=max_work_items and batch_bytes=max_stored_bytes, which is one parser batch and one commit. The scope's batch_size key is retired; publish-daily.json and its pin in publish.json are updated. readings.py is a shared reading file, so model/reading-version-diagnostics.json was re-snapshotted. Only workspace_sha256 changed. Equivalence: only batch grouping changed, and per-body parsing did not; doctor's fixed fixtures matched.

Tests: test_readings_budget_backfill.py::test_backfill_commits_scale_with_stored_bytes_not_rows covers 9 bodies at four bounds. Commits are at most ceil(stored bytes/bound), and every batch but the last reaches the bound. test_daily_producers.py's native derived test now uses 3 HTML pages: 3 rows in 1 commit. test_daily_producer_records.py (gate 5) passes unchanged in semantics. Its interrupted-resume case now leaves only the missing body as remaining work, because the pass appends once.

Local measurement (local catalog, no R2; same driver loop, 60 bodies): batch_size=1 took 60 commits in 18.84 s, and the byte bound took 1 commit in 0.58 s; both wrote 120 rows. Projected R2 nightly on the measured scope: 7,169 s of commits becomes about one 20 s commit, so the step is mostly parse time (at most 565 s, less with one worker pool). Acceptance 4 still needs the after measurement on a real nightly with the same scope; that needs R2, which this branch did not touch.
