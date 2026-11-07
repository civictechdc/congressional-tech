# Original archive rows

`openArchive` exposes `readRows` through the existing archive reader. It uses the
selected release's public controls and original Parquet files. The generic local
viewer can join these results to its separately assembled local DDK catalog by
exact file location and SHA-256. This API creates no release or selection.

Import `openArchive`, `ArchiveRowsError`, `isArchiveDateValue` and
`isArchiveTimestampValue` from
`apps/site/src/components/explorer/reader/archive.ts`. The same module exports
`ArchiveReadRowsOptions`, `ArchiveRowsPage` and the raw value types.

```ts
const archive = await openArchive(pointerUrl, {
  fetcher,
  releaseId,
  mode: 'rows',
});
const page = await archive.readRows('meetings.parquet', {
  offset: 0,
  limit: 100,
  maxBytes: 16 * 1024 * 1024,
  signal,
});
```

The filename must exactly name a Parquet asset in the original manifest. A
sharded file is addressed by its physical name, such as
`sources-00001.parquet`. Raw mode returns after metadata admission and skips the
browsing reader's complete list decode. It offers catalog discovery and raw
pages; query and presentation methods are absent. The normal browsing reader
also exposes `readRows`.

The result contains:

| Field | Meaning |
| --- | --- |
| `releaseId` | Verified original release identity |
| `file` | Original name, verified SHA-256, byte size, row count and source row range |
| `schema` | Original Parquet schema, including logical types and timestamp units |
| `rows` | Original columns in physical order, with no joins, renaming or added position columns |
| `rowPositions` | Aligned `{row, fileRow}` coordinates; `row` includes a shard's source offset |
| `offset`, `totalRows`, `nextOffset` | Requested file offset, observed file row count and next offset, or `null` at the end |

Source offsets derive from shard names and row counts bound by the release hash.
The declared ranges must agree. Returned identity, schema and binary values do
not alias internal cache objects. Altering a returned object cannot change a
later read's claimed identity.

Values retain `bigint`, floating-point values, strings, booleans, binary
`Uint8Array` values, lists and structs. Parquet null is explicit `null`, including
nested nulls; an empty list stays `[]`. Dates use `{type:'date', days:number}`.
Timestamps use `{type:'timestamp', unit:'ms'|'us'|'ns', value:bigint}`. Their integer
values retain the original epoch units; timezone interpretation remains in the
schema. No conversion to JavaScript `Date` loses fractional precision.

Use the exported temporal type guards rather than inspecting public object
fields. Owner-created temporal values have a private marker; ordinary source
structs with identical field names do not pass the guards. Structured cloning
does not preserve that marker. A transport must encode values with the guards
before cloning, or interpret them through the original schema. The source schema
also remains necessary to distinguish nested business structs after transport.

The pinned decoder cannot preserve every Parquet shape. The API explicitly
refuses decimals, maps, JSON, variants, geometry and other unsupported
annotations, logical-only DATE/LIST annotations that this decoder does not
implement, contradictory annotations, unsupported repeated shapes and unsafe
`__proto__` or dotted field names. These refusals precede column decoding. Disclosed field names
and physical types must match; authored field order may differ from physical
order. The native accepted evidence remains the owner of required data checks.

Rows default to 100 and are capped at 1,000 per call. `maxBytes` defaults to
16 MiB and cannot exceed the archive's configured heap budget. The first read
downloads and hashes the entire compressed file through `withVerifiedBytes`;
later pages reuse the existing bounded byte cache. There are no authenticated
partial-file hashes in this release format. Initial file admission reserves a
conservative `file size × 16` allowance, so the default budget admits files of at
most 1 MiB. The file and its parsed metadata must also fit the configured cache.
A caller can choose a larger admitted budget; this fixture does not establish
production-scale file acceptance.

Before decoding, the reader accounts for every intersecting row group, compressed
copies, uncompressed bytes, physical value counts, nesting, temporal objects and
returned-value copies. It then checks returned-page accounting. These estimates
and byte limits are not a hard JavaScript process-memory ceiling. Binary cells
and binary footer statistics are detached from larger backing buffers. Cached
file closures do not retain evicted bytes. Callers own the lifetime and aggregate
memory of returned pages.

Concurrent first reads share one verification. Canceling one waiter preserves
its reason and does not cancel another waiter. The shared verification retains
its resource reservation until it settles or reaches its existing 30-second
deadline. Decoder cancellation is cooperative at reads and event-loop yields;
it does not preempt synchronous decoder instructions.

`ArchiveRowsError.code` distinguishes `INVALID_PAGE`, `UNAVAILABLE`,
`UNSUPPORTED_TYPE`, `SCHEMA_MISMATCH` and `BUDGET_EXCEEDED`. Transport, digest,
release-change and cancellation errors retain their existing outcomes. An
observed zero-row file returns an empty page with schema and identity; an absent
file returns `UNAVAILABLE`.

Focused checks live in `apps/site/scripts/archive-rows.test.mjs`, run through
`npm --prefix apps/site run test:archive-rows` with
`ARCHIVE_ENTITY_FIXTURE_FILES` naming an accepted rich inventory. Small independent
decoder fixtures and their generator exercise exact values, wrapper collisions,
last pages, unused row groups, schema/digest refusal, nested allocation, footer
ownership and cancellation. They make no native producer qualification claim.
