---
id: ct-o6d1
status: closed
deps: [ct-2d3k]
links: [ct-d3un, ct-2wsw]
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

**2026-10-19T19:34:32Z**

Defined exact best-effort allocation/string-limit rule: lazy detail and20/default100max observation items are not byte bounds; complete JSON copy remains explicit;16MiB logical counter remains diagnostic. Bounded16.8MB serialized adversarial fixture crosses counter without rejection, preserves field order/null/empty/nested/Unicode/duplicates; logicalpart65537B, joined0, cache346B, peakRSS412.45MB/action1.225s. Ordinary complete-JSON Blob adds16.80MB (+25.9% known result/clone/format model), misses25% reduction target; retain current exact route and source-Parquet recovery, no new format/threshold.75 focused reader/worker/UI tests pass including resource failure/retry and visible reader/format/clipboard failure without partial copy. docs/experiments/efficiency-debt/complete-export.md/evidence.json; raw receipts primary output/efficiency-debt-20261019/complete-export/. Pending independent review; no browser/fullcatalog or realclipboard qualification.

**2026-10-19T19:39:00Z**

Independent review accepted 996ba97. Exact JSON export and visible failure/retry policy documented; 75 focused checks pass. Alternative full Blob staging misses the memory target, so the existing production path is retained.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch standalone).
- Grades: proposal 74 → 62, work 76 → 76.
- Problem: The only candidate evaluated was a Blob built from the complete JSON string, which by construction cannot cut memory (+25.9% against a target of -25%).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/standalone/standalone-verdicts.md:37
- Covered by: WS11 (ct-2wsw).
- See docs/reviews/2026-10-24-ticket-audit/README.md
