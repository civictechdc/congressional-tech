---
id: cefr-7cj1
status: in_progress
deps: []
links: []
created: 2026-10-27T21:02:06Z
type: task
priority: 2
assignee: raw
---
# B7: apply the owner recovery staging decisions

Resolve source category before display kind and use earliest valid same-body fetch only when exact recovered URL has no source time. Preserve excerpt decisions; restage locally with zero unresolved imports; live imports remain owner-gated.


## Notes

**2026-10-27T21:04:54Z**

Contract ac9a747c reproduced three failures/one pass. Native source selection now resolves categories before kinds and uses earliest parsed-UTC same-body fetch only when exact recovered-URL evidence has no valid time. All23 engine recovery import tests pass21.34s on engine-1c2473b. Local full restage and root independent review remain pending; no live imports.
