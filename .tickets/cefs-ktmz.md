---
id: cefs-ktmz
status: in_progress
deps: []
links: []
created: 2026-10-28T16:31:15Z
type: task
priority: 2
assignee: mikewolfd
---
# Prepare G07 filename viewer removal

Remove the superseded filename reader and preparer; preserve committee explorer and archive reader. Preparation branch only, deploy and switch gated.


## Notes

**2026-10-28T16:52:45Z**

G07 prepared: archive reader/worker/canary and committee six workspaces remain; filename route, UI, reader, preparer and dead tests removed. Remaining explorer 82 pass, mixed raw/CI/archive tests 110 pass in 11.02s, Astro 29 pages in 2.45s. Canonical review binding is used by the kept raw writer and retained. G06/G12/G13 dormant callers require paired owner deletion before whole-branch full-lane acceptance; no merge.
