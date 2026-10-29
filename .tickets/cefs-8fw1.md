---
id: cefs-8fw1
status: closed
deps: []
links: []
created: 2026-10-28T18:34:30Z
type: bug
priority: 2
assignee: mikewolfd
---
# Contain long archive format labels

Long format labels overflow the archive capture-date column. Wrap within the format grid cell and bind the fix with the actual built-page browser contract on desktop and phone.


## Notes

**2026-10-28T18:35:28Z**

Built-page assertion reproduces the desktop overflow with HTML_REQUIRES_DOCUMENT_DISCOVERY: contract fails at text containment before the CSS fix. Fixture expectation written before implementation. Both desktop and phone will be checked by the existing archive contract.

**2026-10-29T03:40:00Z**

Long format labels contained by min-width:0 and overflow-wrap:anywhere. Built-page HTML_REQUIRES_DOCUMENT_DISCOVERY assertion reproduced failure before fix and passed desktop+phone after086. Local strip prepared on prep/strip-site-20261028, code41c7112c after normal integration870. All six full shards completed under4GiB; current13062 selected test IDs exactly match full executed set minus six approved retired subjects, zero surviving failures/omissions; original red receipts preserved. Closure26 focused +83 explorer tests and29-page Astro pass. Imports1495Python/73site zero dangling; whole-tests deleted-path audit zero unclassified site references. Engine original/additive CODE approved; final closure is deleted subjects only, no shared production change. Exact deploy archive checker passed desktop/phone/404/legacy/saved/heap. Lead owns normal merge and Pages/live recheck; no push or live actions by site. 
