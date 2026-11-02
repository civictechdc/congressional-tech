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


## Notes

**2026-11-02T04:01:45Z**

Final review correction: all 976 docs.house.gov rows are in raw witness XML (226 bodies), parsed in appearance_records, but 225 have NULL event_id. Rows have no URL; receipts' original_path wlist/{event}.xml states it. The 98 searched meeting XML only. 19,475 distinct rows; 849 and 1,300 are named with owners, not migrated. Code on worktree-agent-a704015cc138b456b @ da425206. All branches: not merged; parser pins are recomputed once at integration; no backfill, lake write or full model run has happened.

**2026-11-02T13:22:51Z**

2026-11-02 impl-f (r1b-f, 12 commits): 187 House witness lists attached; the old Explorer witness ledger's rows attached to their meeting go from 11,779 to 12,856; 40 path-only lists need e1's captures.original_path (f's last commit fails at planning until e1 merges, deliberately).

**2026-11-02T13:43:11Z**

2026-11-02 green-f: 187/187 House lists attach via their own receipt path (827 rows); 40 lists (190 rows) wait on e1; no site or MCP check of the migrated rows yet (requested).
