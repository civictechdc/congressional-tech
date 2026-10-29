---
id: crb-179o
status: closed
deps: []
links: []
created: 2026-10-28T02:37:15Z
type: task
priority: 0
assignee: mikewolfd
---
# Package the B1 scratch bucket lock probe for owner execution

## Acceptance Criteria

Standalone origin/main release contains maintained probe CLI, passing protocol and CLI tests, dry-run guard, exact owner lock checklist


## Notes

**2026-10-28T02:52:11Z**

Ten focused probe/CLI checks pass on origin/main-based release; dry run cannot connect and 403/409 results prevent raw locking. Semi-formal code review APPROVE. Real scratch lock probe, provenance review and raw locks remain explicit owner actions.
