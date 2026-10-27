---
id: cef-nbn3
status: closed
deps: []
links: []
created: 2026-10-27T10:52:45Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, F0]
---
# F0: convert pinned catalog and build hand-written release fixture

## Acceptance Criteria

Pinned catalog pair becomes the DM8.1 release through engine SQL/export; all 1.24M rows survive; links choose first list row; small fixture covers alternates, hearing, versions, all recovery kinds and hidden document. Local runner verifies both.


## Notes

**2026-10-27T15:31:00Z**

Done: three project-runner native contracts pass; corrected full generation preserves1241157rows,37346duplicate source addresses removed, all key invariants0. Independently checked SHA256/MD5/size/footerrows/created_by/releaseID for every file. Final immutable release shared with site; local fixture only, no publish.
