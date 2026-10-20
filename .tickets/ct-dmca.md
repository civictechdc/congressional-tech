---
id: ct-dmca
status: open
deps: [ct-q968]
links: [ct-sb0s, ct-gziq]
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Support R2-backed schema changes and scalar backfills

DocSpec currently refuses schema evolution and derived scalar backfills on remote storage via `self.require_local()` guards. Identify the first congressional derived-field consumer, extend the maintained native owner (`docspec-rs`) only after exact preservation/recovery evidence, and remove any superseded application rewrite path.

## Acceptance Criteria

- **Evolutionary-refactoring boundary consolidation**: Before expanding remote operations in `docspec-rs`, consolidate scattered `if group != "source" { self.require_local()?; }` and per-command remote guards (`src/main.rs:653-685`, `src/engine/export.rs:76-78`, `src/engine/changes.rs:50-58`) into one authoritative `Engine` capability check so adding R2 support for an operation/group does not require shotgun edits across CLI, HTTP, and engine modules.
- Implement R2-capable schema evolution and scalar backfill in `docspec-rs` using configured remote object storage and durable phase checkpoints.
- Qualify locally first, then run isolated provider qualification on `congressional-tech-raw` (test prefix) covering supported column rename, nullable addition, scalar backfill, exact old/new pinned reads, and interrupted-phase recovery.
- No production data migration or blanket removal of unsupported native backend guards; unsupported nested edits remain explicit `remote_scope` refusals.

## Notes

**2026-10-20T18:35:21Z**

User explicitly authorized extending DocSpec-rs itself for R2 support on2026-10-20. Implement in isolated native worktrees, qualify locally before isolated provider tests, preserve production data and mappings. Backend refusal is a dependency to solve, not grounds for closing this ticket as deferred.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit added the Step 6 next-maintainer requirement: unify `docspec-rs` remote operation/group capability checks into a single `Engine` authority when implementing `ct-dmca`, `ct-sb0s`, and `ct-gziq`.
