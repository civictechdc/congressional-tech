---
id: ct-7e7q
status: in_progress
deps: [ct-upte]
links: []
created: 2026-10-20T08:27:12Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Skip absent observation roots during initial source qualification

The final 4/40 unrelated-record measurement reads the same alias leaf 111/903 times during setup. SourceObservationStorage.affected alternates a known absent before-root with the new after-root, clearing the bounded membership cache on each absent lookup. The exact catalog-copy adoption path avoids this loop, but required source qualification enters it.

## Design

Skip lookups for provably absent before/after roots in the existing source-observation owner. Reuse the exact-pin bounded cache; do not widen cache budgets or add another owner.

## Acceptance Criteria

Demonstrate red/green read counts for initial qualification and deletions, preserve exact affected sources and old/new membership, and repeat only the retained local 4/40 setup measurement affected by the fix. Independently review. No provider, corpus or browser qualification repeat.

