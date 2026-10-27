---
id: cef-b0a9
status: closed
deps: []
links: []
created: 2026-10-27T19:37:00Z
type: task
priority: 1
assignee: mikewolfd
---
# Supervise persistent parser workers within input bounds

D2 first slice: persistent initialized subprocess per parser/version, bounded inputs/output/time/RSS, retry one crash/hang/resource failure, stable unreadable result after second failure. Startup and infrastructure errors remain explicit. Done when focused fixtures and code/architecture reviews pass.

