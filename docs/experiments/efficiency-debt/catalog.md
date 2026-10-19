# Retain the current publication Catalog

The bounded experiment does **not justify a second production reader or a packed-membership refactor**. Packing the two positional Python structures removes 4,926,720 estimated bytes, but the measured constructor highwater changes by only 3,424,256 bytes (1.4%). The actual fixture publication peak changes by 11,436,032 bytes (3.2%), while its wall time increases slightly. These are local fixture observations, not full-catalog savings. Production code remains unchanged.

## Inputs, boundaries and comparison

Baseline is merged `3757f55ed33ea390895c20a2007cb08eb39ce519`. The [executable experiment](catalog_measure.py) imports the unchanged reader for the baseline and transforms exactly two initialization statements in memory for the candidate: `entry_ids` becomes an unsigned integer array, and `members` becomes offsets plus packed row IDs with list-valued access. No production source file is rewritten.

The declaration precedes execution: at most 32,768 document groups, sampled RSS at most 2 GiB, a 600-second deadline per child, and at most 1 GiB owned output. Four initial arm processes separate construction profiling from complete publication; four additional fresh constructor processes provide three samples per arm. Process RSS is sampled every 50 ms. A sampling ceiling is not a guarantee about instantaneous native allocation.

The surviving local historical pair is catalog `7f0b0aa7b53e4205b050ac260d0bc6a7`, generation `ee9bbad71e4648ffbcacb63ccb8bebe2`, with 1,235,122 documents and 1,672,092 filename rows. Streaming SHA-256/size verification matches its retained selector before reading; hashes retained after fixture construction match again. This is explicitly older than the complete-success current catalog below.

Thirty-one evenly spaced document row groups, including the short final group, select 30,898 real document groups. All sources belonging to those groups are retained, including their preferred sources. Eight synthetic groups add API-only, video-only, mixed document/API/video, null, failed-response, Unicode and multi-source cases. The closed fixture has **30,906 documents and 41,030 sources**.

The fixture preserves `LIST_COLUMNS` values and schema metadata from the selected historical rows. Large nested `source_occurrences` are replaced with typed nulls. The real publisher still executes its observation/details verification paths, but this is **not original nested-observation fidelity or full-catalog qualification**. Custom fixture review identities use the real validator/binder with the production review descriptor explicitly excluded. Five reviews bind; body, member-list and missing-document changes withdraw three.

The complete publisher produces identical bytes and sizes for all **269 payload files**, including the 256 stable-ID shards, navigation, flags, browse, details, observations and review binding. Every manifest value also matches after removing only `published_at`. Both arms close their original Parquet readers; neither builds search text indexes. Focused existing viewer/review tests pass: **52 passed**.

## Observed costs

| Cost | Current | Packed experiment |
| --- | ---: | ---: |
| Constructor seconds, median of three fresh processes | 0.2090 | 0.1584 |
| Process highwater through constructor, median bytes | 249,692,160 | 246,267,904 |
| Python `entry_ids`, estimated bytes | 1,216,432 | 164,236 |
| Python `members`, estimated bytes | 4,162,480 | 287,956 |
| Complete fixture publication seconds, one process | 5.4058 | 5.4796 |
| Publication highwater RSS bytes | 361,119,744 | 349,683,712 |
| Publication output bytes | 14,624,718 | 14,624,718 |

Highwater includes interpreter/import/native state; it is not an incremental live-object measurement. Constructor timing varies among fresh processes, so the median does not establish an overall speed improvement. Publication has one arm each and no latency qualification. The candidate adds an extra membership pass, offset storage and transient list slices. There is no disk/output saving.

## Required state and lifetime

`Catalog._initialize` owns these allocations until its Catalog reference is released. `close()` closes both readers and clears complete-row-group cache state; it does not itself drop the Arrow tables, maps or memberships. Python/native allocators may retain freed memory beyond object lifetime.

| State | Fixture size | Required consumers and lifetime |
| --- | ---: | --- |
| Projected filename Arrow table | 20,405,570 Arrow bytes | Group membership, source IDs, saved-response flags, facets, API/video grouping and review member comparisons; retained throughout preparation |
| Projected document Arrow table | 15,291,936 Arrow bytes | Preferred source, filename sort, document flags/body binding and final browse rows; browse `take` can coexist with it |
| Arrow sort order | 247,248 Arrow bytes | Navigation, review positions and browse sort through publication |
| Source-ID map | 6,418,270 estimated Python bytes | Preferred-source construction and all 256 published ID shards; cannot simply be deleted as optional viewer state |
| Document-ID map | 5,071,778 estimated Python bytes | Stable review binding and general viewer identity resolution; retained after loading |
| Memberships / source-to-document positions | 4,162,480 / 1,216,432 estimated bytes | Mixed API/video classification, counts, flags, navigation and exact review member multiset; retained through preparation |
| Document-entry set | 2,905,308 estimated bytes | Ordinary/capture/API/video scope flags and info counts; retained through preparation |
| Preferred-source list | 1,142,704 estimated bytes | Navigation and browse/detail preference; retained through preparation |
| Entry positions / saved-response flags | 123,704 / 30,963 estimated bytes | Review binding/group navigation and any-member retained flags |
| API/video source descriptions and entry sets | 154,083 estimated bytes combined | Descriptions serve the interactive viewer; group classification remains necessary for published flags/info |
| Search text / complete-row cache | 64 / 128 empty-container bytes | Already skipped/empty for publication; lazy viewer state is not responsible for the observed load cost |
| Facets/info | 9,922 estimated bytes | Manifest info preserves advertised facets/counts, including optional review state |

Python estimates deduplicate recursively within each named root, including the packed arrays. Objects shared across roots may be counted more than once; **do not add these categories into a total heap budget**. Arrow logical bytes are also distinct from decoder buffers, Parquet metadata and allocator residency.

The publisher (`apps/site/scripts/publish-filename-viewer.py`) constructs `Catalog(search_indexes=False)`, then retains it during archive copy, filename repack, observation/details verification, navigation, review binding, browse and IDs. Observation SQLite counts, Arrow decode batches, writer staging and browse temporary arrays overlap that lifetime. This experiment does not attribute their complete native working state. The identity CLI (`apps/site/scripts/filename_review_binding.py`) also uses `search_indexes=False`; its `bind` compares sorted full source-ID member lists and the exact document body key. General viewer search/detail methods additionally use lazy search text and per-source API/video descriptions.

A narrower reader would still need the two grouping identities, current facets, preferred sources, saved flags, API/video-only versus mixed-group rules, stable ID shard values, exact review multiset/body semantics and resource ownership. The measured membership representation alone leaves the main Arrow/map allocations intact. A substantially different index needs its own decision and value-parity evidence; this result does not authorize one.

## Historical evidence, failures and limits

The accepted complete current-catalog local run is retained in the tracked [qualification receipt](../publication-remediation/evidence/current-catalog-qualification-20261018.json) and [report](../publication-remediation/current-catalog-qualification-20261018.md): 5,085,020,160 bytes highwater during loading and 7,310,491,648 overall. Those values are historical, with a different catalog and frozen publisher revision; they are not the baseline arm above.

The earlier `c8dda5d` complete local trial failed on a 376,238,952-byte Python/JSON estimate exceeding its 134,217,728-byte single-row admission limit. I read its retained failure receipt before an external cleanup removed the whole historical rollout directory. Its failure is not reclassified as success or recreated from memory. The tracked successful receipt remains; neither full qualification was repeated.

New failed bounded attempts remain separately retained: the first found that removed input directory; the second discovered the projected fixture needed typed-null `source_occurrences`; the third discovered the fixture reviews must not use the production descriptor. The final successful run reuses the corrected immutable fixture. No source documents, remote data, classifiers, publication writes, hosted jobs or held-out evaluation were run.

[Compact measured evidence](catalog-evidence.json) pins the baseline/experiment sources, exact historical input/fixture hashes, all raw JSON receipts, limits, failures, per-root estimates and complete output parity. Raw ignored evidence is under primary `output/efficiency-debt-20261019/catalog/`, with accepted arm receipts in `run-3757f55d/` and its immutable fixture in `run-3757f55c/fixture/`. The declaration, receipts and experiment source are preserved in Git for independent review. The ticket remains in progress until that review accepts this retain-current decision.
