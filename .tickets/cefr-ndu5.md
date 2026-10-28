---
id: cefr-ndu5
status: closed
deps: []
links: []
created: 2026-10-28T11:12:40Z
type: bug
priority: 1
assignee: raw
parent: cef-wylm
---
# Keep Linux parser address-space budget above initialized mappings

Owner portability correction: set the persistent parser child address-space ceiling to its initialized virtual size plus the configured budget, once after imports/protocol setup; retain the supervisor RSS ceiling and reject an inherited finite hard limit that cannot fit.

## Acceptance Criteria

Fake large-VSZ and inherited-limit fixtures pass; persistent actual worker keeps one ceiling across inputs; existing parser/resource focused tests pass; fresh CODE review; release reruns the named Linux cases.


## Notes

**2026-10-28T11:17:43Z**

Contracts11eeb358:20 expected missing-helper failures/9 existing passes. Behavior focused41PASS5.09s on macOS through project production-offline runner, including actual persistent worker with2GiB untouched mapping, fake3GiB baseline and finite-hard-limit refusal; no monkeypatches. RSS supervisor budget unchanged. Actual Linux AS branch still requires release replay of the same three cases. Fresh CODE review pending.

**2026-10-28T12:18:12Z**

Closed after CODE APPROVE (run2/linux-worker-code-review/review.md), 41 focused macOS checks in 5.09s, and release actual three Linux 885 rechecks passing on a27a3351/raw5b3a16f1 in157.29s. The supervisor RSS limit and finite inherited limit checks remain unchanged. Immutable Linux packet retains pins and replay evidence; unrelated QEMU fanout timeout remains a hosted native gate.
