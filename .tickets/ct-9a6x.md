---
id: ct-9a6x
status: in_progress
deps: [ct-2d3k]
links: []
created: 2026-10-19T16:35:49Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d3un
tags: [overlap-rescore]
---
# Reuse the maintained CSV writer for GPO retention

GPO retention repeats retention.tables.write_csv temporary-file and CSV mechanics with only field selection and sorted row order added.

## Acceptance Criteria

GPO retains its public function and sorted package order, delegates atomic CSV writing to retention.tables, and matches baseline bytes and failure cleanup including Unicode, quotes and embedded newlines.

## Notes

**2026-10-19T16:44:52Z**

GPO now delegates CSV mechanics to retention.tables.write_csv, retaining its public wrapper, dataclass field order and sorted package IDs. Sorting stays lazy inside the shared temporary-file cleanup boundary. Exact baseline bytes match empty and Unicode/quote/newline fixtures; injected replacement, invalid-field and sort failures preserve the destination and remove temporary files. All 25 focused CSV/GPO source-fidelity checks passed. Primary log: output/package-overlap-rescore-20261019/browser-package-gpo-csv.log. Awaiting independent review.
