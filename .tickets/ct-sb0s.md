---
id: ct-sb0s
status: open
deps: [ct-eipa]
links: []
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Support R2-backed occurrence evidence updates

Evaluate native evidence updates for source provenance/annotations without rewriting source values. Current remote backend refuses this operation. Preserve stable occurrence identity, duplicate multiplicity and review ownership.

## Acceptance Criteria

Exact local/provider preservation and recovery tests, measured unchanged source bytes, no reinstated or silently withdrawn reviews. Real consumer migration required before closure.


## Notes

**2026-10-20T18:35:21Z**

User explicitly authorized extending DocSpec-rs itself for R2 support on2026-10-20. Implement in isolated native worktrees, qualify locally before isolated provider tests, preserve production data and mappings. Backend refusal is a dependency to solve, not grounds for closing this ticket as deferred.
