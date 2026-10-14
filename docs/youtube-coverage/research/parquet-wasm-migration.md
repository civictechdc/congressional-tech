# Direct Parquet provenance

October 14, 2026. Catalog `5272bb4b85ed4549b1fcc3008077bf6d`.

The filename viewer now reads nested provenance directly from `filenames.parquet`
with Parquet-Wasm 0.9.0 and Apache Arrow 21.2.0. Hyparquet 1.31.2 still handles
filters and ordinary metadata. This removes a separate provenance encoding and
its writer/reader. It is a maintenance and publication simplification, with a
measured cost in detail-read time and memory.

Future publications omit `observations.bin`, `observation-rows.bin`, and
`observation-index.json`. Those three files occupy 79,345,639 bytes in the
comparison snapshot. The values already exist in Parquet; they are not removed.
Old immutable releases remain readable and retained. This change does not reclaim
their existing R2 storage or force a raw catalog rebuild.

## Behavior and validation

The reader accepts both existing version 2 manifests and version 3 manifests
without the three files. The compatible reader deploys before the publisher
changes. The next changed catalog automatically uses version 3; an unchanged
catalog is not republished solely to remove duplicate files.

The new module loads only when opening a detail. It decodes `source_occurrences`
for the selected row and converts Arrow values to plain JavaScript. Complete
records, original field order, nulls, repeated observations, Unicode, and nested
lists are preserved. Filters, group membership, recovery selection, and saved-copy
links keep their existing paths.

The existing transport validates HTTP 206, exact Content-Range, and byte lengths,
supports cancellation, and bounds its compressed-byte cache. The adapter reads
the needed compressed column ranges and metadata before calling Wasm, then
provides those bytes through the library's Blob interface. This avoids passing
network rejections into the pinned library's asynchronous reader, which traps
on failed I/O. Adjacent cached footer ranges are combined to prevent duplicate
metadata downloads. The adapter does not allocate a Blob the size of the file.
[ParquetFile API](https://kylebarron.dev/parquet-wasm/classes/esm_parquet_wasm.ParquetFile.html).

Verification:

- 82 JavaScript tests and 18 Python publication/recovery tests pass, including
  complete fixture equality, malformed ranges, cancellation, and recovery after
  a mid-read network failure. Generated types match; Astro reports no diagnostics.
- Five complete real entries match the previous reader in each of three runs:
  Becerra, Schondelmeyer, recovered PDF, recovered HTML, and the unfetched UN link.
  This compares the whole returned entry, including provenance and recovery data.
- A real remote Becerra read returns 347 fields and nine observations through
  seven Parquet requests, all HTTP 206, and no custom provenance-file requests.
- The production build renders committee/hearing provenance and saved-copy
  links at a 390-pixel viewport. This checks responsive browser behavior, not
  physical-phone memory limits.

## Measured tradeoff

Three fresh Node 26.9.0 processes per arm used the same local publication and
verified recovery overlay, with a 256 MiB V8 heap limit. Each opened the five
entries in the order below. Timings include local reads and decoding; they exclude
network transfer, rendering, and reader-module import before the timer. Wasm
initialization occurs during the first new detail read. V8's heap limit does not
limit total process memory or Wasm memory. Machine load and operating-system
caches were uncontrolled; these are observed ranges, not population percentiles.

| Detail | Previous reader | New hybrid reader |
|---|---:|---:|
| Becerra, first detail | 686–824 ms | 799–840 ms |
| Schondelmeyer | 127–224 ms | 234–247 ms |
| Recovered PDF | 210–346 ms | 411–455 ms |
| Recovered HTML | 229–269 ms | 313–329 ms |
| Unfetched UN link | 128–231 ms | 230–258 ms |
| Peak resident memory across sequence | 567–581 MiB | 677–692 MiB |

The first detail reads 31,674,894 data bytes versus 30,271,453 previously, including
navigation and document metadata. The Wasm asset adds 5,254,540 bytes uncompressed
(1,666,200 bytes when locally gzipped), loaded lazily. These asset sizes are not
measured deployed wire traffic. The remote sample took 7.32 seconds, without a
paired network baseline; it establishes operation, not a speed improvement.

A rejected variant sent every detail column through Wasm. It was faster locally
(504–551 ms for the first detail), but read 42,338,682 data bytes and reached
727–766 MiB peak resident memory. Restricting Wasm to nested provenance reduces
that cost. The adopted change still uses more memory than the previous custom
format; it should not be described as a mobile performance optimization.

## Evidence and reproduction

[`parquet-wasm-migration-results.json`](parquet-wasm-migration-results.json)
contains all final timings, byte counts, process memory samples, and 15 equality
results with canonical entry hashes. The predeclared decision and narrowed
intervention are recorded in `.cache/parquet-wasm-migration/experiment.md`.
That directory also retains the previous reader frozen at `4fe4cac`, the probe,
complete compared entries, HTTP range trace, test/build logs, and rejected
full-record results. A copy is preserved outside the worktree in this chat's
artifact directory.

The probe uses `.cache/duckdb-viewer-probe/common.mjs`, its frozen publication and
recovery selector, and the retained `.cache/full-provenance/viewer/` data. Run from
the repository root after restoring those same inputs:

```sh
node --max-old-space-size=256 .cache/parquet-wasm-migration/compare.mjs baseline 1
node --max-old-space-size=256 .cache/parquet-wasm-migration/compare.mjs wasm 1
```

Repeat with run numbers 2 and 3, compare every complete entry, and preserve the
outputs before changing either reader or snapshot. Automated fixture checks run
through `npm run test:explorer --workspace apps/site` and the publication workflow.
