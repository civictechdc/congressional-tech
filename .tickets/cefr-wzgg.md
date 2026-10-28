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

**2026-10-28T01:35:51Z**

Owner retro-review reopened B3: remove every body_identity bypass and its option/plumbing; validate file keys before source open. New sync/async/file/local malformed-name contracts written first. Project-runner baseline: 57 failed / 39 passed, expected red; existing four-file storage baseline: 102 passed. No production storage or network writes.

**2026-10-28T01:37:03Z**

Retro-review local repair: removed body_identity option/plumbing and all four bypass calls; R2 put_file validates names before opening source. New 96-case delegate/preparation contracts use recording fakes and local call profiling, no monkeypatch. Expected-red commit e5fe76cf: 57 failed / 39 passed. Focused production-offline now 198 passed in 1.23s with approved 48636e5 runtime. Positive write fixtures use SHA-derived names; legacy suffix support, MD5, collisions, retries and streaming assertions retained. Source wc 282/576/278 -> 282/577/278, net +1 early validation line. Loopback fixtures updated but not executed under no-network-writes scope. Awaiting parent CODE/ARCH review; no real storage writes.

**2026-10-28T01:58:40Z**

Retro-review fixed e5fe76cf/f6a6f1a0: 57 new red cases before behavior; focused production-offline198passed1.23s, mandatory CODE/ARCH APPROVE no findings (run2/review-body-{code,arch}). All body_identity bypasses removed, file names checked before open, valid suffixes retained. Native-loopback fixture keys updated but no network PUT qualification run. Source1136to1137lines; one policy variation point removed.
