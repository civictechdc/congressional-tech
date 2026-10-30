---
id: ct-gqwm
status: closed
deps: []
links: []
created: 2026-10-30T16:20:32Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
---
# W7 (Visual Swarm): Entity graph normalization, roster/member/bill joins, and strict Congress/Chamber filtering

From 5-Persona Visual Review Swarm (Personas 1, 3, 4, 5): Join rosters.parquet with membersIndex(), normalize member terms dates & header metadata, join bill sponsors/amendments/CBO links, derive congress for meetings/bills/nominations, enforce strict congress/chamber filtering in listEntities, and deduplicate hearing sittings/recordings.


## Notes

**2026-10-30T16:20:32Z**

Implemented and verified in 830d8d62 (merged to main in 4925103e).
