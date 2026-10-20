---
id: ct-rcs8
status: closed
deps: [ct-l5q1]
links: []
created: 2026-10-20T07:37:34Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Preserve oversized catalog rows in bounded native storage

The selected documents archive contains a 43,807,597-byte Arrow row; native catalog chunks admit at most16MiB. Publication preserved it by copying the archive, so prior renderer success does not qualify native adoption.

## Design

Locate every oversized row in the exact selected files. Reuse the maintained typed storage and lookup owners. Choose a bounded representation that reconstructs every field and ordered repeated value while retaining existing source/document IDs and mappings; do not raise limits or discard values.

## Acceptance Criteria

Record full-table scan coverage and exact oversized-row causes. Add failing preservation/readback tests, implement the smallest coherent representation change, and prove exact old/new typed readback, bounded chunks, resumed import and unchanged unrelated rows. Independently review; production adoption remains gated by complete preservation checks.


## Notes

**2026-10-20T08:26:58Z**

Complete current scan: 725 files / 8,623,851 rows. Shared typed occurrence storage preserves the exact 43,807,597-byte selected document and all 33,479 occurrences through actual native write/read; largest physical test chunk 4,081,155 bytes. Independent backend and consumer review approved. Final browser checks preserve complete large records, field order, null/empty/duplicates, reviews and stable links. Integration c2f4bcad includes corrected test pins; 100 focused tests passed, broader 310 passed plus four fixture corrections separately retested. Receipt: adoption-survey/typed-rows-implementation.json. Production adoption remains separately gated.
