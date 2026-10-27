---
id: cefr-wzgg
status: closed
deps: []
links: []
created: 2026-10-27T13:51:15Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B3: one create-only body store and refusal matrix

## Acceptance Criteria

Refuse unsafe raw writes and credential URLs before I/O; atomic local and single-PUT R2 adapters; all surviving raw writers use the store; focused contracts pass.


## Notes

**2026-10-27T15:38:48Z**

Local done: shared refusal/atomic/create-only store and all surviving raw writers; reviewed source-checksum/PDF metadata and URL findings fixed. B3 routing architecture APPROVE with123 checks; latest store/ratchet group50 passed. B0 replacement remains deliberately separate; old live interfaces remain delegates until F5.
