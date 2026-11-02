---
id: ct-x78c
status: open
deps: []
links: []
created: 2026-11-02T00:40:43Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [explorer, witnesses, phase2]
---
# Migrate or explain every old Explorer witness row with no new-table match

Owner decision 2026-11-01: keep these facts. 6,955 old Explorer witness rows are labelled old_state_only. Raw reads of 6,201 show House rows are 579 distinct, each counted in both old CSVs; 43 are unread and 118 have no held page; surname matches are leads only. Old Explorer retirement (ct-5kto) waits for this.

## Acceptance Criteria

Every distinct row is migrated with evidence, or has a named reason and owner; duplicates are counted once; site and MCP checks cover the migrated rows.

