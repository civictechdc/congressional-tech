---
id: ct-yf1c
status: open
deps: []
links: [ct-n2cy, ct-lgxk]
created: 2026-11-02T04:01:45Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [model, release, phase2]
---
# Documents publish with blank filenames

The live release has 2,901 blank filenames. review-c-explorer: 1,426 are PDFs from EPW and Small Business Files.Serve URLs with no name in the URL; 1,320 are HTML, mostly hearing pages; 169 are recovery-only; 62 PDFs and 21 XML have blank names despite named URLs because of trailing slashes or a NULL-address saved row. saved-files still selects those rows.

## Acceptance Criteria

Every listed document has a usable name or title rule, and saved-files does not select a NULL-address row.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): 1,446 Files.Serve PDFs have no name in the URL or headers; fix uses trailing-slash names and puts the named copy of the saved body first. impl-g.
