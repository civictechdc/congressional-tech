---
id: ct-tdsx
status: open
deps: [ct-2d3k]
links: [ct-d3un]
created: 2026-10-19T16:40:41Z
type: task
priority: 2
assignee: mikewolfd
tags: [overlap-followup]
---
# Define bounded startup handling for mandatory recovery status

Recovery loading is intentionally fail-closed and verifies the complete sidecar, but currently consumes the whole response with no recovery-specific deadline or pre-allocation byte admission. Establish the size/time policy separately from optional reviews without adding baseline-only fallback.

## Acceptance Criteria

- Inspect saved sidecar sizes/startup receipts and declare a proportional recovery byte/deadline policy; do not acquire new sources or repeat hosted publication for this decision.
- If limits are adopted, reject invalid/oversized/hung recovery input visibly while preserving missing-sidecar validity and mandatory failure on corrupt bytes, digest, catalog identity or positions.
- Distinguish encoded transfer Content-Length from decoded byte counts, as the review loader already does; preserve exact decoded-length/hash authority.
- Cover ignored AbortSignal, streamed overrun, valid encoded/CORS response, absent descriptor and corrupt bindings with focused fixtures, or document why the measured current route is intentionally retained.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: apps/site/src/components/filename-recoveries.mjs:2:loadRecoveries. See docs/package-overlap-rescore-20261019.md for the full grade map.
