---
id: ct-3ebz
status: closed
deps: []
links: []
created: 2026-10-30T14:32:31Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, site, refactor, w4, track2]
---
# W4: Modularize ArchiveDetail.tsx & archive.ts and retire reader/filenames/

Split apps/site/src/components/explorer/archive/ArchiveDetail.tsx (957 lines) into focused inspector modules (ArchiveRows.tsx, HearingDetail.tsx, CommitteeDetail.tsx, WitnessDetail.tsx, MemberDetail.tsx, SubjectDetail.tsx), extract Phase-2 entity helpers from apps/site/src/components/explorer/reader/archive.ts (1,350 lines) into archive-entities.ts, and move cache.ts, client.ts, cooperative.ts, and startup.ts out of apps/site/src/components/explorer/reader/filenames/ while keeping verify-archive-contract.py green.

## Acceptance Criteria

ArchiveDetail.tsx and archive.ts are decomposed into focused modules, reader/filenames/ is retired, and verify-archive-contract.py and site build/tests pass.


## Notes

**2026-10-30T15:06:23Z**

Completed and verified in main (verify-archive-contract.py exit 0, 97/97 test:explorer, 11/11 test:archive-native, 29 Astro pages built).
