---
id: cefs-5dls
status: in_progress
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
