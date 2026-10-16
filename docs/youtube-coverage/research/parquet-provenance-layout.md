# Standard Parquet provenance lookup experiment

October 14, 2026. **No replacement qualified for deployment.** The most promising
candidate replaces three custom lookup files with two ordinary Parquet tables
and uses Hyparquet's existing scan API. It improves the ordinary-detail sample,
but does not complete the large-record stress benchmark under the same heap
limit as the current reader. Production remains on `d8a65f3`.

## Proposed simplification

The complete source and document Parquet tables remain unchanged. Replace
`observations.bin`, `observation-rows.bin`, and `observation-index.json` with:

| Table | Contents | Purpose |
|---|---|---|
| `observations.parquet` | One JSON logical-type value per unique observation, including every null field | Read the complete provenance without a custom compressed-block decoder |
| `observation_rows.parquet` | Each source's ordered list of observation row numbers, or null | Preserve shared evidence, duplicates, ordering, and null versus empty lists |

Both use standard Parquet page indexes. The reader caches their small footers,
fetches selected pages, and parses JSON only for selected values. Existing
Hyparquet 1.31.2 and hyparquet-compressors 1.1.2 suffice; no Wasm, Arrow, DuckDB,
or additional browser dependency is introduced. The
[Parquet JSON logical type](https://parquet.apache.org/docs/file-format/types/logicaltypes/)
and [Hyparquet scan API](https://github.com/hyparam/hyparquet/blob/master/src/scan.js)
are maintained upstream capabilities.

Deduplication remains necessary. Converting a real 8,192-source row group to
one full JSON list per source produced more than 2 GiB of strings. A narrow
native nested-Parquet scout also exhausted the 256 MiB JavaScript heap. Neither
result justifies increasing the memory budget or removing evidence.

## Method and decision rule

Use the full retained publication for catalog
`5272bb4b85ed4549b1fcc3008077bf6d`, generation
`5e8fd602b4c54322a8b8ddd8a5b350b3`, with its frozen recovery overlay. The tables
contain 4,500,218 unique observations and references for 1,672,092 sources.

Compare against the unchanged reader at `d8a65f3`. Run Node 26.9.0 with
`--max-old-space-size=256` and an HTTP 206 simulator that records actual file
range reads. Each candidate gets three fresh-process pairs; reverse arm order
in the middle pair. Open Becerra, Schondelmeyer, a recovered PDF, recovered HTML,
and the unfetched UN record. Compare complete returned entries, including
provenance, group data, recoveries, and saved-copy URLs.

Before measurement, require median elapsed time, CPU time, and peak resident
memory to stay within 5% of the baseline, comparable or smaller detail transfers,
complete value equality, bounded reads, and no additional runtime. Keep failed
variants and unchanged limits. Stress cases include five deterministic random
source rows and the five largest provenance lists. The largest has 12,147
observations. A production publication would also require every-value readback
against the source, mobile verification, and remote range testing.

## Results

Each row below has its own contemporaneous baseline; do not compare absolute
times across separately run experiments.

| Candidate | Median elapsed change | Median CPU change | Median peak RSS change | Decision |
|---|---:|---:|---:|---|
| Zstandard 9, 64 KiB pages, existing scalar reader | +8.4% | +3.4% | -0.6% | Fails elapsed-time limit |
| Brotli 4, 256 KiB pages, concurrent provenance/scalar reads | +28.4% | +30.8% | -1.7% | Fails time and large-record checks |
| Zstandard 9, 64 KiB pages, one scalar scan per source, sequential provenance | -12.4% | -5.0% | -2.8% | Ordinary sample passes; large-record check fails |

The last candidate uses `parquetScan` to plan the 347-field source read once,
then reads eight columns at a time. It avoids repeatedly constructing a
row-oriented plan while preserving bounded column decoding. Compression,
layout, and reader changes are evaluated together; these results do not assign
the improvement to one component.

| Last candidate, five-detail sequence | Current reader | Candidate |
|---|---:|---:|
| Median elapsed time | 3,143 ms | 2,754 ms |
| Median CPU time | 6,338 ms | 6,022 ms |
| Median peak resident memory | 580 MiB | 564 MiB |
| Data transferred | 37,927,303 bytes | 37,636,429 bytes |
| Range/file requests | 33 | 39 |
| Provenance lookup publication size | 79,345,639 bytes | 261,464,350 bytes |

All 15 complete entry pairs match for each candidate. The Brotli and scan
candidates also match the five random holdouts and the first large holdout.
Both then abort while the harness serializes the second large result to JSON
(source row 317724); the baseline completes all ten holdouts. The failed output
is retained as a zero-byte file with the fatal-error log. This is a benchmark
heap failure, **not a demonstrated mobile-browser crash**. It prevents claiming
equivalent memory behavior and does not qualify either candidate for release.

Wall times vary substantially with host load and garbage collection. These
local measurements exclude network latency and rendering. The candidate's six
extra requests make a delayed-network check necessary. That check, mobile
verification, and full-corpus publication readback were not performed after the
large-record gate failed. No selected sample establishes corpus-wide fidelity.
The heap limit is not a limit on total resident memory.

## Decision and remaining uncertainty

Keep the current deployed reader, complete provenance, and saved-copy links.
Do not change the publication format or automatic publisher based on this
experiment. The standard two-table layout is a plausible simplification, but
its 3.3-times-larger lookup storage and unqualified large-record memory behavior
remain costs, even where ordinary reads improve.

The next useful investigation is to separate the large-result JSON capture
cost from the application's actual Worker message path. If the application
also regresses, reduce simultaneous large-result materialization while keeping
the full evidence accessible. Repeat both arms under the same limits; retain
these failures. Do not deploy based only on the faster ordinary sample.

## Retained evidence

The predeclared experiment and amendments, conversion scripts, input manifests,
reader variants, raw timings and ranges, full returned records, independent
equality checks, native/JSON scout failures, and fatal-error logs are retained
in `.cache/parquet-provenance/`. The large generated Parquet files remain there.
A compressed evidence archive is also attached in this chat's artifact folder.
`summary.json` records every repeated run and the calculations above.

The recovery chat completed its separate publication and released the lock.
Its recovery-basis compatibility changes were preserved separately and are not
part of this experiment. No bucket, source catalog, recovery mapping, or live
viewer data was modified by this work. Measurements deliberately retain the
earlier frozen recovery overlay for equal inputs across all arms.
