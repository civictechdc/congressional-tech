---
id: crm-zlgg
status: closed
deps: []
links: []
created: 2026-10-28T02:40:01Z
type: task
priority: 0
assignee: mikewolfd
---
# Package the guarded M1 smoke sequence for owner execution

## Acceptance Criteria

Pinned optimized probe runs create, append three days, observe exact rows, race, purge and records remaining objects; local fake proves order, fail-stop and credentials stay in inherited environment


## Notes

**2026-10-28T03:25:10Z**

Eleven process-fake checks pass; semi-formal code review APPROVE. Engine supplied optimized darwin-arm64 probe from eb3a121 with native no-connection plan. Release independently verified SHA-256 31d70fcba7013f6914b78bdd1be83eefbde8e0c4d9dfae7262f81f2c98705f0b, size137211008 and wrapper plan against actual binary. Exact owner environment/execute/stop commands are documented; live Basin smoke remains owner gate.
