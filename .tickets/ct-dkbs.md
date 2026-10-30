---
id: ct-dkbs
status: closed
deps: []
links: []
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, site, explorer, w2, track2]
---
# W2: Separate entity inspector views from document search list in ArchiveExplorer.tsx

Render HearingDetail, CommitteeDetail, WitnessDetail, MemberDetail, and SubjectDetail in apps/site/src/components/explorer/archive/ArchiveExplorer.tsx as first-class views rather than stacking the paginated document search table underneath an open entity inspector.

## Acceptance Criteria

Opening an entity inspector (hearing, committee, witness, member, bill, nomination) renders it as a dedicated view with clean back/tab navigation and without the document search table stacked underneath.


## Notes

**2026-10-30T15:06:23Z**

Completed and verified in main (verify-archive-contract.py exit 0, 97/97 test:explorer, 11/11 test:archive-native, 29 Astro pages built).
