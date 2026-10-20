---
id: ct-sb0s
status: open
deps: [ct-eipa, ct-dmca]
links: []
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Support R2-backed occurrence evidence updates

Evaluate native evidence updates (`UpdateEvidenceSpec`) for source provenance/annotations without rewriting source values. Current remote backend refuses this operation via `require_local()`. Preserve stable occurrence identity (`__docspec_occurrence_id`), duplicate multiplicity, and review ownership.

## Acceptance Criteria

- Extend `docspec-rs` evidence updates to operate on configured R2/S3 object storage through the unified `Engine` remote capability boundary (shared with `ct-dmca`), preserving immutable `source`-group Parquet files untouched while writing/selecting only the updated evidence group.
- Prove exact local and isolated R2 provider preservation and interrupted-phase recovery: zero rewritten source bytes, identical source object digests, preserved duplicate multiplicities and occurrence ordinals, and no reinstated or silently withdrawn review states.
- Migrate a real congressional provenance/evidence consumer before closure.

## Notes

**2026-10-20T18:35:21Z**

User explicitly authorized extending DocSpec-rs itself for R2 support on2026-10-20. Implement in isolated native worktrees, qualify locally before isolated provider tests, preserve production data and mappings. Backend refusal is a dependency to solve, not grounds for closing this ticket as deferred.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit linked `ct-sb0s` to `ct-dmca`'s unified `Engine` remote capability check and reinforced the zero-source-rewrite invariant.
