---
id: ct-j9o7
status: open
deps: []
links: [ct-vq2a, ct-yci9]
created: 2026-11-05T02:36:33Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-gi01
tags: [data-model]
---
# Map type-less BILLS-<congress><number><version> filenames to their GovInfo package when unambiguous

saved-copy-identity (ct-vq2a) drops 1,587 package ids shaped BILLS-1162899ih (no bill type). Where another copy names the typed form it is now corrected (BILLS-1181776ih -> BILLS-118hr1776ih); the rest are dropped. Many are House bills, but a Senate bill number can collide. Evidence: .cache/archive-release/investigations/saved-copy-identity/replay.parquet (b_pkg vs n_pkg).

## Acceptance Criteria

Map to hr only with corroboration (the meeting's measure, a same-bytes typed copy, or the bill's own text/title); otherwise stay empty. Fixture for a collision that must not map.

