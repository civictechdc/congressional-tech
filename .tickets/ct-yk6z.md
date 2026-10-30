---
id: ct-yk6z
status: closed
deps: []
links: []
created: 2026-10-30T14:32:30Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, site, explorer, w1, track2]
---
# W1: Add top-level entity browse tabs to ArchiveExplorer.tsx

Expose top-level browse tabs in apps/site/src/components/explorer/archive/ArchiveExplorer.tsx for Documents (367,008), Hearings (18,687), Committees (817), Witnesses (56,066), Members (12,770), and Bills & Nominations (12,579) backed by the existing /entities worker endpoint (reader.listEntities(kind, args) in apps/site/src/components/explorer/reader/archive.ts and archive-worker.ts).

## Acceptance Criteria

Users can browse Documents, Hearings, Committees, Witnesses, Members, and Bills & Nominations directly from top-level tabs in ArchiveExplorer.tsx using reader.listEntities.


## Notes

**2026-10-30T15:06:23Z**

Completed and verified in main (verify-archive-contract.py exit 0, 97/97 test:explorer, 11/11 test:archive-native, 29 Astro pages built).
