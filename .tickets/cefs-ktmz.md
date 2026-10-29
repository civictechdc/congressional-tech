---
id: cefs-ktmz
status: closed
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

**2026-10-29T03:40:00Z**

G07 complete: /filenames/ is the sole removed public route (30->29). New archive reader/worker and seed/successor fixtures retained. Local strip prepared on prep/strip-site-20261028, code41c7112c after normal integration870. All six full shards completed under4GiB; current13062 selected test IDs exactly match full executed set minus six approved retired subjects, zero surviving failures/omissions; original red receipts preserved. Closure26 focused +83 explorer tests and29-page Astro pass. Imports1495Python/73site zero dangling; whole-tests deleted-path audit zero unclassified site references. Engine original/additive CODE approved; final closure is deleted subjects only, no shared production change. Exact deploy archive checker passed desktop/phone/404/legacy/saved/heap. Lead owns normal merge and Pages/live recheck; no push or live actions by site. 
