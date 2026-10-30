---
id: cefr-3w18
status: closed
deps: []
links: [ct-adtz]
created: 2026-10-27T14:03:56Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B8: carry pinned assistant kind reviews into provenance

## Acceptance Criteria

Native identity join stages all 86 pinned selected kind reviews on stable link keys with assistant reviewer; append-only review recorder supports supersession; exact owner import command.


## Notes

**2026-10-27T14:12:10Z**

Contracts df7e33c6, implementation a1b8bfe0; B7/B8 focused 9 passed, import fence runner 22 passed (implementation commit body incorrectly said 3; retained cxb_import_fences.log is authoritative). Native full86 measurement and independent review pending. No live import.

**2026-10-27T14:51:32Z**

B8 staged all86 real pinned reviews natively; immutable shared raw-reviews-a1b8bfe0; measured byte pin and owner apply commands in b8 README (b4405e73). Authored review/correction CLI e615a1ca. Focused combined82pass includes latest helper behavior; independent review pending; owner provenance apply after E4 parity.

**2026-10-27T15:38:48Z**

Local done:86 pinned selected assistant reviews staged on stable body link keys; new authored/correction path validates public schema. CODE note-type concern fixed b7dba485,92 focused checks pass; architecture APPROVE. Immutable shared stage and exact owner command are in b8 README; public import waits E4 parity.
