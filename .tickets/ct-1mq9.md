---
id: ct-1mq9
status: open
deps: []
links: [ct-z4i9, ct-yndj]
created: 2026-11-11T04:24:14Z
type: task
priority: 3
assignee: mikewolfd
tags: [lake, maintenance, perf]
---
# readings regrows after compaction: every commit adds files and every append re-reads them all

Follow-up to ct-yndj (measured 2026-11-11 from retained run folders, read-only). Each readings append anti-joins the whole table: seconds = 1.39 + 14.81 ms per existing data file (n=1,267 remote appends, 599..1,909 files, r=0.79; exact file counts from each run's readings/plan native_inputs, maintenance-prep/append-cost.tsv). The pinned writer never merges files, so every commit adds at least one file per partition it touches, and a compacted table (ct-yndj runbook, about one file per (parser, parser_version)) regrows. Rate today: since ct-z4i9 the nightly commits once per producer pass (daily.py:1041 leaf parsers in mode daily, one batch; daily.py:813-814 HTML metadata with the byte bound): 2 commits and +3 files from 2026-11-09T20:20Z to 2026-11-10T19:16Z. Before that fix one run (nightly 20261109T195731) made 832 appends, 1,072 -> 1,907 files. At 3 files a night the 256-file threshold in model/jobs/maintenance.json is crossed in about 77 nights. Two gaps keep the recurrence manual: (1) maintenance_decision needs file_count, manifest_count and scan_planning_seconds, but the engine's native_inputs report manifest_count and planning_seconds as null (all 252 retained remote records), so lake_maintenance.observations can only be hand-filled; (2) produce_html_metadata (daily.py:822-886, operator path, only tests call it) still takes a plain batch_size with no byte bound, so a batch_size of 1 (d2ec0211) would again make one commit per row.

## Design

Options, cheapest first: (a) repeat the ct-yndj move by hand when data files pass the threshold, measured by mp_readings_move.py measure; (b) let the weekly job decide from data_file_count and snapshot_count once the engine reports manifest_count (engine ask), still starting the move only on an owner's word; (c) give produce_html_metadata the same byte bound as the nightly derived pass. Measure files added per nightly for two weeks after the first move before choosing a cadence.

## Acceptance Criteria

The owner picks a trigger and cadence (or records why it stays manual), based on two weeks of measured files-per-nightly after the first ct-yndj move; produce_html_metadata either takes a byte bound or records why not.

