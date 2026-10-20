---
id: ct-a70m
status: open
deps: [ct-qdkd]
links: []
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Use protected native retention and restore planning

Expose safe inspection/planning of native-owned retained data and restore prerequisites using maintained APIs (`NativeDatasets.inspect_retention` -> `POST /retention/inspect` and `NativeDatasets.plan_removal` -> `POST /retention/removal/plan` in `packages/congress_api/src/congress_api/retention/docspec.py:290-295`, backed by `docspec-rs/src/engine/retention.rs`). Keep filesystem caches (`catalog-dependency-preparation-v1`) and non-native archive data outside native retention ownership. No automatic deletion or expiration.

## Acceptance Criteria

- Read-only operator planning surfaces native `RetentionInspection` / removal plans listing protected vs. reclaimable native ownership and remote quiescence requirements alongside application-selected pins.
- Tests prove application-selected releases, active-reader pins, and incomplete-operation data cannot be proposed as unprotected or reclaimable.
- No live removal, automatic compaction/expiration, or restoration side effects in this ticket.

## Notes

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit verified that `NativeDatasets.inspect_retention` and `plan_removal` are already wired on the persistent host adapter in `codex/docspec-host-transport` (`docspec.py:290-295`). Once `ct-q968` and `ct-qdkd` land, bind application-selected pins into the read-only operator retention planner and test protection invariants.
