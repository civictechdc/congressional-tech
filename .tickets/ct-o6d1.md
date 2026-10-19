---
id: ct-o6d1
status: open
deps: [ct-2d3k]
links: [ct-d3un]
created: 2026-10-19T16:40:41Z
type: task
priority: 2
assignee: mikewolfd
tags: [overlap-followup]
---
# Define the exact-value browser memory and complete-export policy

The 16MiB observation threshold records oversized work rather than admitting it. Whole JSON text/parse results, complete source observations, structured clone, formatted JSON and clipboard can coexist beyond retained-cache budgets. Streaming decoded parts removes one copy but does not create a hard active-memory bound. Preserve the accepted exact-value route while evaluating whether a format or explicit export policy change is worth its cost.

## Acceptance Criteria

- Use saved large-value/clone/JSON accounting and current reader boundaries as baseline; distinguish retained caches, decoder part bytes, logical text, parsed values, full results, worker clone, formatted text and clipboard.
- State the supported maximum/decision rule and visible resource-failure behavior for ordinary detail versus explicit complete export. Do not silently turn the current accounting threshold into a rejection or truncate values.
- Evaluate one minimal incremental/value-addressable or download-based option only against a concrete resource target; preserve null versus empty, field order, duplicate observations, Unicode and exact original values.
- If a format/export change is justified, record the compatibility and user-visible policy decision before implementation, and prove bounded peak working state on an adversarial fixture. Otherwise record why the exact route and explicit Parquet recovery remain the accepted tradeoff.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: apps/site/src/components/filename-catalog.mjs:225:sourceRecord, apps/site/src/components/filename-observations.mjs:16:decode, apps/site/src/components/filename-observations.mjs:63:read, docs/youtube-coverage/research/filename-viewer.mjs:654:(closure). See docs/package-overlap-rescore-20261019.md for the full grade map.
