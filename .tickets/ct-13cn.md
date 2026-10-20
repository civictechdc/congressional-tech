---
id: ct-13cn
status: open
deps: [ct-q968]
links: []
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Support native version comparisons for R2-backed data

Reuse DocSpec compare/changes for a concrete diagnostic consumer after remote support is implemented. Preserve duplicate multiplicities, null semantics and exact pinned versions.

## Acceptance Criteria

Native remote compare/change route and bounded diagnostic output qualified against an independent reference. Report reads and elapsed time; never treat metadata equality as semantic equality.


## Notes

**2026-10-20T18:35:21Z**

User explicitly authorized extending DocSpec-rs itself for R2 support on2026-10-20. Implement in isolated native worktrees, qualify locally before isolated provider tests, preserve production data and mappings. Backend refusal is a dependency to solve, not grounds for closing this ticket as deferred.
