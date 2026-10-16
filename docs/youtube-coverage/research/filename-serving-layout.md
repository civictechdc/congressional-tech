# Smaller reads for the filename viewer

The viewer now reads a compact detail table and loads technical evidence on demand. The complete source and document exports remain unchanged. The native provenance Parquet experiment failed its speed gate, so the bounded observation lookup remains in use.

## What changed

| File | Purpose | Rows | Columns | Bytes |
| --- | --- | ---: | ---: | ---: |
| `filenames.parquet` | Complete source records, including original observations and conflicting values | 1,672,092 | 347 | 357,659,672 |
| `documents.parquet` | Complete grouped document export | 1,235,122 | 350 | 376,760,579 |
| `browse.parquet` | Sorted list, filters, saved-response status, and document classification | 1,235,122 | 20 | 18,403,424 |
| `details.parquet` | Ordinary detail facts, useful filename readings, and fallback provenance | 1,672,092 | 46 | 136,248,156 |

The browse table replaces the previous browse table, document summaries, and document-row permutation. This saves 9,349,160 bytes (33.7%) across those files. It removes unused list columns and includes the classification basis needed by the detail view.

The new detail table stores HTTP status as `uint16`, response usability/completeness as booleans, and fetch times as UTC millisecond timestamps. Invalid or conflicting facts remain in `fact_alternatives`; they do not silently become a single fact. Sparse filename readings use `list<struct<field:string, values:list<string>>>`. The original archival values remain available through complete metadata and the source export.

This serving copy increases the complete publication by approximately 126.9 MB after the browse savings. Its purpose is to avoid reading hundreds of sparse archival columns during ordinary viewing. It is not a claim that the entire publication became smaller.

Provenance is paged in groups of 20 observations. Ordinary details request the fields needed to explain the source trail. Additional source pages, technical fields, individual observation bodies, and full copied JSON load only when requested. Long flat evidence lists also render 20 values at a time. Original URLs, saved copies, recovery mappings, grouped saved-response filtering, and old immutable catalog links remain supported.

Advanced observation search scans each unique observation once and maps matches back to source groups. Compressed reads are batched into 4 MiB windows; decoding remains bounded to one observation block. This avoids decoding huge nested source row groups, but a complete evidence search is still an expensive full-corpus operation.

## Measured result

Source catalog: `5272bb4b85ed4549b1fcc3008077bf6d`. Source generation: `5e8fd602b4c54322a8b8ddd8a5b350b3`. Baseline reader: `d8a65f3`. The experiment held the source catalog and recovery overlay constant and used three fresh Node processes per arm with a 256 MiB JavaScript heap limit and local HTTP 206 responses. The middle pair reversed order.

These measurements cover the same five-detail sequence, not page loading, a physical phone, or production network latency. RSS measures total process memory, which can exceed the JavaScript heap limit.

| Median across three runs | Previous reader | New reader | Change |
| --- | ---: | ---: | ---: |
| Five-detail sequence | 1,472.7 ms | 497.3 ms | 66.2% faster |
| Peak process RSS | 588.1 MB | 431.3 MB | 26.7% lower |
| Detail bytes read | 37.93 MB | 21.06 MB | 44.5% fewer |
| Requests | 33 | 38 | 5 additional requests |

An earlier single diagnostic pair with 40 ms added to each request took 2,607 ms versus 2,001 ms. This illustrates that extra requests reduce the gain under latency; it is not a production latency estimate.

A full-corpus evidence search with no matches completed in 31.2 seconds, transferred 97.3 MB in 28 requests, and peaked at 526.3 MB RSS. Batching reduced this candidate's earlier 4,873 requests and 52.7 seconds. Evidence search remains a separate performance limitation; ordinary details do not perform that scan.

## Native provenance Parquet decision

The candidate stored one native Parquet row per unique observation and one ordered `list<uint32>` of observation IDs per source. It preserved null observations, empty lists, ordering, repeats, and all original fields. Full readback checked 4,500,218 observation rows and 1,672,092 membership rows.

The predeclared gate allowed one layout adjustment. That adjustment used 65,536-row groups, 32 KiB pages and page indexes, Zstandard level 19, and delta-encoded memberships. The two files totaled 66,778,424 bytes, 15.8% below the existing observation lookup. However, against the same contemporaneous detail table:

| Median across three runs | Bounded lookup | Native Parquet |
| --- | ---: | ---: |
| Five-detail sequence | 518.7 ms | 619.8 ms |
| Peak RSS | 437.3 MB | 459.2 MB |
| Detail bytes | 22.05 MB | 24.63 MB |
| Requests | 38 | 162 |

Native Parquet was 19.5% slower, exceeding the 5% regression limit. It is not part of the deployed reader or publisher. The final serving table subsequently dropped an unused document ID; the final-reader measurements above include that improvement. The native experiment and its failed gate are retained as evidence, rather than maintained as a second production path.

## Verification and publication

- All 15 complete metadata cases exactly match the previous reader: five ordinary cases, five deterministic random cases, and all five largest provenance collections. All ten large/random detail cases finish within the heap limit.
- Publication verifies every emitted detail value and schema by readback. Full source/document exports and observation reconstruction retain their existing complete fidelity checks.
- 39 JavaScript tests and 33 Python tests pass. They cover lazy reads and DOM creation, paging, full JSON copying, retry, conflicting facts, null/empty observations, group filtering, recovery mappings, and publication validation. The Astro production build passes.
- At a 390 × 844 browser viewport, the hearing → UN article → file trail and recovered saved-copy action remain visible. A 12,147-observation record creates no technical field DOM before expansion; expansion renders 20 observation headers with no observation bodies until opened. Paging shows observations 21–40. No horizontal overflow was observed. This is browser viewport verification, not a physical-device memory measurement.
- Viewer manifest and publisher version 5 force regeneration even when the source catalog is unchanged. Scheduled and source-completion publication use the same builder. R2 uploads remain immutable, include current accepted recoveries, verify public range reads, and update the selector conditionally after validation.

An interrupted archival readback during deployment left the previous snapshot selected, as intended. The publisher now uses boto3's managed download with partial-transfer retries, followed by the same complete file-size and SHA-256 checks. This replaces the single long streaming response without adding a separate retry implementation. Interrupted-download and corrupted-content tests both confirm that a partial publication cannot become current.

## Released result

Implementation commit: `c138a4c`. Publication readback fix: `7b762b9`. The live release is `76599d6453264ba8bd593777c58a3bd7`, with viewer schema and publisher version 5. All 266 objects (1,041,476,760 bytes) passed readback and public-access checks before selection.

Live verification confirmed the four intended Parquet files, the expected detail-table hash, exact preservation of all 5,542 recovery mappings, the House hearing → UN article → file trail, and HTTP 200 for both ordinary and recovered saved-copy links. The 12,147-observation record returned observations 21–40 correctly. The mobile source trail loaded without horizontal overflow or eager technical DOM.

The [Pages deployment](https://github.com/civictechdc/congressional-tech/actions/runs/38657269352) succeeded. The [automatic publisher](https://github.com/civictechdc/congressional-tech/actions/runs/38657269461) passed its 33 checks and correctly reported the selected catalog unchanged after this publication. Future source changes use the same version-5 builder.

Benchmark scripts, frozen readers, logs, summaries, and mobile screenshots are retained with this chat under `serving-layout/`. Generated candidate data remains in the worktree cache. The final detail table SHA-256 is `61f522951d9ddacea51d43339b95c10afe463b6c1947bac3d5fc9cec7cc1b4b5`.
