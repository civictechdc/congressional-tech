---
id: ct-9a6x
status: open
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
