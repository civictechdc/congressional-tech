# Filename detail performance correction

October 14, 2026. Restore the bounded provenance lookup and remove Parquet-Wasm
and Apache Arrow from the viewer. The migration in `8f2507f` and `e6c2875` made
details slower and increased memory. Removing three publication files did not
justify that user-facing regression.

## Cause and correction

Each nested detail read created a new `ParquetFile`, reparsing the wide source
file's 10.7 MB footer alongside the metadata already held by Hyparquet. A separate
stage trace measured 92–188 ms opening the file, 15–66 ms decoding the selected
nested data, and 2–19 ms converting Arrow results. The first Wasm initialization
added 58 ms in that diagnostic run. These figures diagnose the component; they
are not browser load times. The `ParquetFile` creation/read lifecycle is described
in the [upstream API](https://kylebarron.dev/parquet-wasm/classes/esm_parquet_wasm.ParquetFile.html).

The Becerra provenance read fetched a 1,747,363-byte nested column range. The
compact lookup needs 32,899 bytes of compressed blocks, plus a 311,023-byte index
on first use. The migration also introduced an additional Wasm runtime and
temporary metadata/Arrow representations. The full comparison measured the
resulting memory increase; it did not attribute every allocation to a component.

Restore the existing bounded reader, its publisher, and its fidelity tests.
Remove the extra runtime, adapter, and Wasm/Arrow dependencies. The 5,254,540-byte
Wasm asset and separate Arrow reader bundle disappear from the production build.
The ordinary Parquet reader, group filters, provenance rendering, recovery
selection, and saved-copy URLs retain their behavior.

The three lookup files remain intentional performance indexes over the complete
Parquet data. For this snapshot they cost 79,345,639 bytes of publication storage.
That storage buys cheaper detail reads. The publisher reconstructs and compares
every observation against Parquet, preserving nulls, duplicates, ordering,
Unicode, and source associations. No archive objects or source evidence are
deleted.

## Paired measurements

Compare frozen deployed `e6c2875` with the corrected reader, using the same
immutable catalog `5272bb4b85ed4549b1fcc3008077bf6d`, recovery overlay, local
byte-range transport, Node 26.9.0, and 256 MiB V8 heap limit. Three fresh-process
pairs opened Becerra, Schondelmeyer, a recovered PDF, recovered HTML, and the
unfetched UN link in that order. Reverse arm order in the middle pair. The
stage-instrumented run is diagnostic only and excluded from this comparison.

| Measure | Regressed reader | Corrected reader |
|---|---:|---:|
| Five-detail sequence, run 1 | 5,579 ms | 5,181 ms |
| Five-detail sequence, run 2 | 6,851 ms | 4,674 ms |
| Five-detail sequence, run 3 | 8,696 ms | 4,477 ms |
| Median sequence time | 6,851 ms | 4,674 ms |
| Peak resident memory across runs | 672–693 MiB | 556–579 MiB |
| First-detail data bytes | 31,674,894 | 30,271,453 |

The median sequence is 32% faster and median peak memory falls about 123 MiB.
All three complete sequences improve. Individual wall times are noisy: recovered
HTML has a slightly higher median in the corrected arm and overlapping ranges.
Do not claim every interaction is faster or extrapolate a phone memory budget.
Machine load and operating-system caches were uncontrolled. These local times
exclude network transfer and rendering; first-detail bytes include navigation
and ordinary metadata, and exclude script assets. V8's heap limit does not limit
Wasm memory or total process memory.

## Fidelity and deployment checks

- All 15 complete entry comparisons match, including every original field,
  provenance, group data, accepted recovery, and saved-copy URL.
- 82 JavaScript and 28 Python tests pass, including lossless provenance
  publication, invalid ranges, cancellation, Unicode, nulls, duplicates,
  group-based saved filters, and recovered saved-copy selection.
- Real R2 reads cover Becerra, the recovered PDF, and the unfetched UN record:
  17 range responses, all HTTP 206. Mobile layout checks cover the same cases.
- Before rollout, the live selected manifest is version 2 and contains all
  lookup files. Both migration-era publisher runs reported `unchanged`; no
  version-3 publication was selected. Existing snapshots need no rebuild.
- Future automatic publications retain the lookup files. The publication
  workflow now runs the restored fidelity tests as well as the broader
  publication/recovery checks added during the migration.

## Retained evidence

The predeclared experiment, frozen regressed reader, comparison harness, three
raw runs per arm, 15 complete entry pairs, decoder stage trace, HTTP responses,
saved-copy checks, and test/build logs are in
`.cache/filename-performance-regression/`, copied to this chat's artifact folder.
The harness reuses `.cache/duckdb-viewer-probe/common.mjs` and its frozen selectors,
with `.cache/full-provenance/viewer/` as the retained data. The previous migration
report and its measurements remain as historical evidence.
