---
id: crc-tm3n
status: closed
deps: []
links: []
created: 2026-10-28T05:23:00Z
type: task
priority: 0
assignee: mikewolfd
---
# Wire private Linux runtime into credential-free CI jobs

## Acceptance Criteria

Every offline workflow installs the pinned private binary before tests and exports local DOCSPEC_JOB_CONFIG without credentials, focused config/installer tests pass, engine receives branch for merge


## Notes

**2026-10-28T10:08:36Z**

Done: all offline workflows use the shared private installer with local credential-free configuration; strict source/hash/features/capability and failure-before-export tests pass. CI code through94bd and metadata73746484 normally merged into integration39c1d982. Focused landing119PASS and independent reviews APPROVE. Final qualified source pin, Linux artifact and hosted run remain separate landing gates; no live action performed.
