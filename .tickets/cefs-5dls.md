---
id: cefs-5dls
status: closed
deps: []
links: []
created: 2026-10-28T16:38:56Z
type: task
priority: 2
assignee: mikewolfd
---
# Prepare G08 review viewer removal

Remove superseded public review staging and reader while preserving canonical review inputs and the raw review writer; preparation only.


## Notes

**2026-10-28T16:49:59Z**

Lead/raw delegated the kept CLI default retarget. Canonical descriptor and identities SHA pins unchanged; actual old-explicit versus canonical-default native CLI produced byte-identical 86-record provenance (1 test, 0.59s). Six maintained raw-review tests pass; explorer 82 pass, Astro 29 pages. Review viewer deletion remains prepared and uncommitted separately.

**2026-10-28T16:53:26Z**

G08 viewer deletion prepared separately after 0f736701 default retarget. Raw writer, canonical review inputs and review identity binding stay. Actual old/default CLI output: identical 86 records; canonical SHA pins unchanged. Removed stager, legacy reader/tests and duplicate site JSON; npm build now Astro only. Remaining explorer 82 pass, mixed raw/CI/archive 110 pass, Astro 29 pages. No merge; final shared closure/full lane/review pending.

**2026-10-29T03:40:00Z**

G08/defaults complete: old review viewer/stager removed; canonical review data and filename_review_binding APIs preserved. Raw old/default CLI outputs remain identical86 records. Local strip prepared on prep/strip-site-20261028, code41c7112c after normal integration870. All six full shards completed under4GiB; current13062 selected test IDs exactly match full executed set minus six approved retired subjects, zero surviving failures/omissions; original red receipts preserved. Closure26 focused +83 explorer tests and29-page Astro pass. Imports1495Python/73site zero dangling; whole-tests deleted-path audit zero unclassified site references. Engine original/additive CODE approved; final closure is deleted subjects only, no shared production change. Exact deploy archive checker passed desktop/phone/404/legacy/saved/heap. Lead owns normal merge and Pages/live recheck; no push or live actions by site. 
