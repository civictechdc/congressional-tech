---
id: ct-eb71
status: closed
deps: []
links: []
created: 2026-10-24T18:46:38Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-dzlf
tags: [audit-20261024, efficiency]
---
# Use Table.nbytes and drop the Arrow-Python byte-count round trips

Efficiency pass E3. Arrow to Python to Arrow round trips exist only to satisfy a self-computed byte-count equality (raw_storage.py:923,992,1136,1239,1253). Measured 2.37 us per row, about 9.3 s per pass over 3.9M captures; nbytes gives the size in microseconds. The engine's verified pin already binds the bytes.

## Acceptance Criteria

- The five round trips are gone and the streaming size budget uses nbytes.
- No test asserts a self-computed byte equality.
- Raw lanes pass.


## Notes

**2026-10-30T17:36:12Z**

Completed and superseded by G03 raw index deletion in c25ee9bb (wc -l: 11,617 -> 2,124, -9,493 net): packages/congress_api/src/congress_api/retention/raw_storage.py and packages/congress_api/tests/test_raw_storage.py (including all 5 Arrow-Python byte-count round trips) have been deleted, replaced by congress_api.lake.captures and congress_api.lake.tables.
