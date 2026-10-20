---
id: ct-si9g
status: in_progress
deps: [ct-l5q1]
links: []
created: 2026-10-20T02:20:21Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Recompute only affected catalog records and document groups

raw_catalog.py:153-346 restores and traverses existing rows; catalog_staging.py:264 reconstructs grouping state even when group results can be reused. Persist dependency and grouping state instead of rebuilding it for each update.

## Design

Keep the maintained source-association, availability, filename and group-identity rules. Feed them only changed facts and the complete affected old/new components. Store versioned results and summary contributions through ct-l5q1's owner. Develop against its executable change fixtures in parallel with the raw writer; live raw integration belongs to ct-dat9.

## Acceptance Criteria

- Characterize outputs before structural edits. Separate changing storage/execution from changing domain policy; policy changes are outside this ticket.
- Compare every field and duplicate count against the bounded reference for additions, corrections/deletions, evidence/state edits, alias merges/splits and targeted rule upgrades.
- Preserve source/document ID algorithms, nested evidence and unaffected interpretations. Include removal of a connecting edge and a large affected component; do not pretend affected work is always small.
- Measure records visited, receipts/bodies read, classification calls, group work and serialized bytes. A fixed change in a larger unrelated corpus must not trigger a global scan, including in validation.
- Resume bounded work within large components. Missing dependency information stops with a precise error. Remove replaced disposable grouping/restore passes after maintained callers migrate.

## Notes

**2026-10-20T03:24:07Z**

Reviewed dependency core 6901878 merged as f7b2694. Shared grouping/source-ID policy and exact native dependency lookup preserve old aliases, nested values and source order; deletion closes both sides of an old bridge. Eleven independent tests passed in 1.26 s. Fixed-change lookup counts stay equal with 10 / 1,000 unrelated fixture sources. Persisted routing writes, large-component resume and maintained callers remain in progress; no end-to-end speed claim. Review: output/incremental-updates-20261019/catalog/closure-review.md.

**2026-10-20T03:35:46Z**

Independent review of 2a45bca passed 18 focused checks, including actual local native storage, but found per-alias dataset creation unsuitable at archive scale. Coalesce small aliases into bounded shared native leaves, retain bounded large-alias overflow, and measure native call counts for adoption and fixed changes. This checkpoint is not merged or production-qualified. Review: output/incremental-updates-20261019/catalog/routed-storage-review.md.
