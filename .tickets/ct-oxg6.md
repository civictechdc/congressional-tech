---
id: ct-oxg6
status: open
deps: [ct-copj, ct-q968]
links: []
created: 2026-10-20T18:47:06Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, qualification]
---
# Qualify the new native host without changing retained migration state

Persistent transport requires native request deadlines and owned-port readiness. Freeze a reviewed DocSpec binary and qualify a separate application runtime; preserve the existing binary, credentials, workspace, failed operation and production selectors.

## Acceptance Criteria

Record native source revision and binary digest; test required host capability and exact-version reads through the new runtime; integrate dependency documentation and startup errors. No production import restart or config replacement. Retain existing operation recovery prerequisites.

