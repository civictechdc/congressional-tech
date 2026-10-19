# Catalog and remote-write efficiency

Two focused changes remove unnecessary retained data and remote journal work while preserving publication output and recovery behavior.

| Change | Measured result | Limit |
| --- | --- | --- |
| Catalog preparation | Retained source Arrow data falls from 20,405,570 to 11,455,564 bytes: 8.95 MB less, or 43.9%. Unused browse columns are dropped before copying sorted rows. | Total process peak and publication speed did not demonstrably improve. Other tables, indexes and native allocations still dominate. |
| Remote journal | The six-worker fixture removes 109 journal PUT/full-readback pairs: PUTs 821 to 712; GETs 833 to 724; HEADs remain 270. | Parallel completion order affects the count. One timing sample does not establish production speed. |

Catalog preparation retains only the columns it needs. Interactive use restores the full column set through one locked promotion method. The journal keeps one pending verification fact and includes it in the next durable event; every payload still waits for its durable intent and receives complete readback. Completion and failure events flush the final fact. Original conditions and explicit crash recovery remain in place.

Each measured arm preserves all 269 payload files and the compared manifest/recovery values. Catalog baseline/final tests passed 60/64 checks; remote baseline/final tests passed 74/87. The combined affected checks passed **139 tests in 43.30 seconds**. These are local fixtures and focused tests; no full-catalog, live publication or hosted performance qualification was repeated. CI was not used as a merge gate.

The changes follow evolutionary refactoring: one column-lifetime owner and one journal-sequence owner, with no new reader mode, general batching framework or duplicated publication path. Detailed measurements and behavior checks are in [catalog](catalog.md) and [remote writes](remote.md). Raw evidence remains in the primary checkout under `output/efficiency-round-two-20261019/`.
