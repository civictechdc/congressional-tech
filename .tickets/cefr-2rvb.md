---
id: cefr-2rvb
status: closed
deps: []
links: []
created: 2026-10-29T04:25:48Z
type: bug
priority: 1
assignee: raw
---
# Bound R2 GET transport retries in the existing SDK policy

ConnectionClosedError escaped the configured GET throttle budget. Add connection/timeout/reset transport conditions to the single SDK policy; retain fail-fast exhaustion and write budgets.

## Acceptance Criteria

Fixture-first real SDK with fake transport covers recovery/exhaustion, legacy and standard, mixed503/transport attempts, no extra stream layer, nonGET controls; focused runners and one code review; active owned-v2 remains frozen.


## Notes

**2026-10-30T14:32:56Z**

Completed bounded R2 GET transport retry policy and merged to main.
