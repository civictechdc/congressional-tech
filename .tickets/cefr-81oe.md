---
id: cefr-81oe
status: closed
deps: []
links: []
created: 2026-10-27T14:07:19Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B4: set raw admission once at capture store construction

## Acceptance Criteria

New raw capture uses one explicit BodyStore policy and no review exclusion gate; preserved live imports have a prepared switch deletion.


## Notes

**2026-10-27T15:38:48Z**

Local acceptance confirmed by engine: target admission belongs to BodyStore, no exclusion gate;7 unreachable legacy exclusion lines removed9a3674cd,96 focused checks pass. Exact old live definitions/callers/line counts/source hashes prepared in codex-raw/cxb_switch_deletions.json for manager F5; active imports remain until switch.
