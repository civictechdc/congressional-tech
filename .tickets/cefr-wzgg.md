---
id: cefr-wzgg
status: in_progress
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

**2026-10-28T01:35:51Z**

Owner retro-review reopened B3: remove every body_identity bypass and its option/plumbing; validate file keys before source open. New sync/async/file/local malformed-name contracts written first. Project-runner baseline: 57 failed / 39 passed, expected red; existing four-file storage baseline: 102 passed. No production storage or network writes.
