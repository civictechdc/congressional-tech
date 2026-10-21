---
id: ct-lcbc
status: closed
deps: [ct-wmtx]
links: [ct-mi03, ct-a1aa, ct-wmtx, ct-mpsp, ct-a70m, ct-qdkd, ct-gfv8]
created: 2026-10-20T20:37:00Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, catalog, retention, efficiency]
---
# Compact superseded lifecycle revisions behind the oldest active release pin

Profiling a 2-operation lifecycle (`initial` Build + `refresh-1` Refresh) via `Engine::inspect_retention` produces `current_revision = 22` (~11 SQLite `records` revisions per operation across `admission`, `processing`, `evidence`, `readback`, `result`, and `authority`; see `docspec-rs/iceberg_optimization_report.md:50-56`). At hourly polling (`24` operations/day), a single dataset appends ~250–264 revisions/day.

In `docspec-rs/src/catalog.rs:255-278` and `:370-420`, `DatasetCatalog::open` replays every historical row from `records WHERE dataset = ?1 ORDER BY revision` on cold open and charges the cumulative historical `row_bytes` (including superseded revisions) against `limits.max_metadata_bytes` (default `32 MiB` in `src/budget.rs:42`). Existing `retire_operations`, `retire_phases`, and `retire_grants` (`src/engine/retention.rs`) retire individual records on demand rather than compacting superseded lifecycle history.

## Design

At the existing `DatasetCatalog` (`src/catalog.rs`) and retention (`src/engine/retention.rs`) owners, add durable lifecycle baseline compaction behind the oldest active/protected `ReleasePin`. Coalesce superseded key revisions older than the retention frontier into one verified baseline checkpoint inside the existing SQLite transaction boundary, while preserving all selected releases, active reader grants, in-flight operations, and recovery roots. Do not introduce a second SQL authority or automatic background expiration.

## Acceptance Criteria

- Compacting lifecycle history behind the oldest protected `ReleasePin` reduces stored SQLite `records` rows and replayed `row_bytes` to O(live keys) regardless of prior superseded revisions.
- Cold `DatasetCatalog::open` after >250 hourly operations stays well within `limits.max_metadata_bytes` (`32 MiB`) and preserves exact selected `ReleasePin`s, `ExportPin`s, active reader grants, and incomplete operations.
- Crash/interruption recovery and `verify_release` pass before and after baseline compaction.
- Record before/after revision counts, replayed metadata bytes, and cold-open latency.

## Notes

**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A | Impl: B+ (Closed for embedded Rust). Engine::compact_lifecycle (src/engine/retention.rs:245-273, src/catalog.rs:527-661) compacts superseded SQLite revisions behind the oldest protected ReleasePin; CLI/HTTP exposure and Python operator wiring are tracked in ct-gfv8.
