---
id: ct-r60e
status: closed
deps: []
links: [ct-gfv8, ct-mi03, ct-ur2y, ct-nloa, ct-xu1o, ct-8ax6, ct-pgxn, ct-ur7v, ct-qkvr]
created: 2026-10-21T14:41:26Z
type: task
priority: 2
assignee: mikewolfd
tags: [news_lake, docspec, maintenance, iceberg]
---
# Trigger threshold-based compact_lifecycle maintenance after multi-poll native Updates in news_lake and local workspaces

Empirical probing on docspec-rs 96e3826 (probe_docspec_scale.py Probe 5) demonstrated that 16 sequential keyed Updates on an 8,192-row dataset accumulate 185 lifecycle Parquet files (457 rows, 1,600,284 metadata bytes), degrading per-update latency from 0.7097s (Update #1) to 2.0034s (Update #16, 2.82x slower). Calling NativeDatasets.compact_lifecycle took 0.0488s (48.8 ms), collapsed 185 -> 1 lifecycle file and 1,600,284 -> 335,062 metadata bytes (-79.1%), and immediately restored Update #17 latency to 0.6777s (2.96x speedup). While ct-gfv8 exposed compact_lifecycle on NativeDatasets and DocSpecClient, no production caller invokes it automatically or on a revision threshold.

## Design

In packages/news_lake/src/news_lake/storage/docspec_backend.py (DocSpecLake / DocSpecNewsViews) and local operator maintenance (packages/congress_api/src/congress_api/retention/native_capacity.py), check lifecycle revision / file growth after completed batch commits or view materializations on local workspaces (remote is None) and invoke compact_lifecycle(dataset) when superseded revisions exceed a configurable threshold (e.g., >= 16 revisions since last baseline compaction), preserving all active/sealed ReleasePins and ExportPins.

## Acceptance Criteria

- DocSpecLake / DocSpecNewsViews supports automatic or threshold-triggered compact_lifecycle on local workspaces after a release is sealed.
-Protected ReleasePins, ExportPins, and active reader grants remain intact across compaction.
- Add a multi-poll regression test verifying that lifecycle file count and metadata bytes remain bounded across >= 16 sequential polls.

## Notes

**2026-10-21T16:40:00Z**

Implemented in `b28cc9b7`: added `DEFAULT_LIFECYCLE_COMPACT_INTERVAL = 16`, `_mutation_counts`, and automatic/manual `compact_lifecycle()` on `DocSpecLake` (`packages/news_lake/src/news_lake/storage/docspec_backend.py:312-384`) and `DocSpecNewsViews` (`:574-625`). Verified in `packages/news_lake/tests/test_docspec_backend.py::test_threshold_lifecycle_compaction_triggers_after_multi_poll_updates`.

**2026-10-21T17:18:00Z**

Realistic-scale qualification (`ct-pgxn`, 1,080 hourly polls, `output/news-poll-scale-20261021/summary.md`) identified three follow-up requirements beyond revision-count `compact_lifecycle`:
1. `spicy-stack` `ss-1txq` (closed): Fold superseded `result/*` and `succession/*` records into `SuccessionCheckpoint` so `SnapshotRows` does not retain $O(\text{polls})$ operation records across `compact_lifecycle`.
2. `spicy-stack` `ss-g9sn` (open): Physically unlink expired `warehouse/<dataset>/lifecycle/{data,metadata}` files (`~1,000 MiB` at 1,080 polls) and superseded checkpointed `objects/<dataset>/<attempt>/` release/manifest files (`~1,035 MiB`, $O(\text{polls}^2)$) during `compact_lifecycle`.
3. `ct-8ax6` (open): Bound per-poll small-file fragmentation (`1,080` ~95 KiB files/table at 45d; `8,760`/year) via batch coalescing or threshold native table compaction (`Engine::compact`) so the single live head `ReleasePin` does not accumulate `~5.8 KiB/poll` of `ObjectRef` metadata (`6.28 MiB` at poll 1,079; `~51 MiB` > `32 MiB` `max_metadata_bytes` at `T2 = 8,760`).

