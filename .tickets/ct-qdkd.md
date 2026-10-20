---
id: ct-qdkd
status: open
deps: [ct-q968, ct-n7la]
links: [ct-a70m]
created: 2026-10-20T18:24:28Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Expose native progress and combined staging capacity

Use maintained `NativeDatasets.plan` / `inspect` / `retained_producer_inputs` (`packages/congress_api/src/congress_api/retention/docspec.py:253-295`) and combined capacity receipts (`packages/congress_api/src/congress_api/retention/native_capacity.py`, closed `ct-n7la`) to surface pending/completed native work and staging headroom to operators without introducing a second lifecycle or monitoring engine.

## Acceptance Criteria

- Operator inspection command/helper reports exact dataset/operation state, reusable completed preparation/native phases, unresolved retained producer inputs (`request-*/source.parquet` byte costs from `ct-3faj`), and combined filesystem capacity (`staging_budget_bytes`, `staging_retained_bytes`, `native_scratch_bytes`, `headroom_bytes`) without exposing `DOCSPEC_*` secrets or performing extra payload scans.
- Tests cover early insufficient capacity refusal, active/completed/failed native operations, unresolved producer input reporting, unchanged native limits, and changed configuration refusal.

## Notes

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit updated dependencies to explicitly include closed `ct-n7la` (`native_capacity.py`) alongside `ct-q968` (`NativeDatasets.inspect` / `retained_producer_inputs`).
