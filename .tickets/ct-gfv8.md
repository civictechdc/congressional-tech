---
id: ct-gfv8
status: closed
deps: [ct-lcbc, ct-a70m]
links: [ct-wmtx, ct-qdkd, ct-lcbc, ct-a70m, ct-r60e, ct-mi03, ct-ur2y]
created: 2026-10-20T23:52:13Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, catalog, retention, maintenance]
---
# Expose local lifecycle baseline compaction through CLI, HTTP, and protected operator maintenance

ct-lcbc added embedded Rust Engine::compact_lifecycle(&Id) -> Result<LifecycleCompactionResult> (docspec-rs/src/engine/retention.rs:245-273, src/catalog.rs:527-661) to compact superseded SQLite lifecycle revisions behind the oldest protected ReleasePin, but exposed no CLI subcommand (src/main.rs) or loopback HTTP route (src/http.rs). Consequently, Python callers (NativeDatasets in packages/congress_api/src/congress_api/retention/docspec.py and native_capacity.py) cannot invoke local lifecycle baseline compaction when SQLite revision counts grow across hourly polling cycles.

## Acceptance Criteria

- Expose Engine::compact_lifecycle via a CLI subcommand (compact-lifecycle) and loopback HTTP route (POST /retention/compact-lifecycle) in docspec-rs (src/main.rs, src/http.rs), preserving require_local() refusal on remote backends.
- Add compact_lifecycle to NativeDatasets (packages/congress_api/src/congress_api/retention/docspec.py) and surface revision-bloat / baseline-compaction readiness in read-only operator inspection (native_capacity.py) without running compaction automatically.
- Add CLI/HTTP and Python adapter tests verifying that compact_lifecycle preserves all protected ReleasePins, ExportPins, active reader grants, and incomplete operations while reducing stored SQLite revisions.


## Notes

**2026-10-20T23:53:21Z**

CS 300 Grade — Spec: A | Impl: N/A (Open). Created to address the CS 300 deduction on ct-lcbc / ct-a70m: expose local Engine::compact_lifecycle (src/engine/retention.rs:245-273) through CLI/HTTP and NativeDatasets read-only operator maintenance.

**2026-10-21T00:31:34Z**

Implemented: docspec-rs CLI CompactLifecycle { dataset } (src/main.rs), POST /datasets/{dataset}/lifecycle/compact (src/http.rs), NativeDatasets.compact_lifecycle, and news adapter delegation. HTTP route test asserts revisions_after <= revisions_before and a positive revision. cargo integration: 323 passed (rt). Runtime pin still needs re-qualification after the Rust delta.

**2026-10-21T00:58:53Z**

CS 300 Post-Review Fix -> Grade: A. Surfaced lifecycle_revision and lifecycle_compaction_available in inspect_operator_status (native_capacity.py:244-250,315-316) and added test_compact_lifecycle_delegates_to_dataset_lifecycle_route in tests/test_docspec_runtime.py:390-401.
