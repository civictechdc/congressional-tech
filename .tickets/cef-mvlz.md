---
id: cef-mvlz
status: in_progress
deps: []
links: []
created: 2026-10-28T01:35:13Z
type: bug
priority: 0
assignee: mikewolfd
---
# Share filename inputs between the model and producer

Owner review B3: one native filename-inputs definition including flat Content-Disposition, shared by E2 and D3 through a fixed filename_captures alias. Delete the producer copy and pin the shared SQL in the catalog version. Native parity fixture compares actual D3 work-list and model effective-name pairs; prior NULL-header failure is bound by3c77e8ba/e553b6e9.


## Notes

**2026-10-28T05:11:54Z**

Ownership transferred to raw by owner decision 20261028T051000Z. Shared filename input/producer binding already integrated; root will not start further changes here. Coordinate model source/input seam through engine; currentmodel native file-name consumers and fixture2PASS remain unchanged.
