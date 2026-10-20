---
id: ct-rcs8
status: open
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

