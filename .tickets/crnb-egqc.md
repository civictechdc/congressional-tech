---
id: crnb-egqc
status: in_progress
deps: []
links: []
created: 2026-10-28T14:17:16Z
type: task
priority: 0
assignee: mikewolfd
---
# Bound native CI test clients to a shared small profile

## Acceptance Criteria

Legacy native tests use one explicit 2-CPU 2-GiB memory and scratch profile without changing production defaults, assertions or explicit tight limits; original tiny helper stays unchanged. Native focused cases pass and one required code review closes all findings.

