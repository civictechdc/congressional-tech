# Explorer data sources

The production React UI receives an `ExplorerReader`. The bounded design preview
receives an `ExplorerDataSource`. Both return normalized records; the UI does
not know which files, encoding or service supplied them. The interfaces are in
`data-source.d.ts`, with dependency-free browser implementations in
`data-source.js`. The working design preview uses this code directly.

```text
page startup chooses source and decoder
                  ↓
ExplorerDataSource.load({ signal })
                  ↓
ExplorerSnapshot { schemaVersion, records, sources, publication? }
                  ↓
record views, selectors, charts, source inspector
```

- `createCatalogSource({ url, decode?, fetcher? })` loads one bounded catalog.
  JSON is its default decoder. The preview's startup passes this source to
  `mountExplorer({ source })`; its renderer contains no network or decoding code.
- `createPublicationSource({ pointerUrl, decoders?, fetcher? })` follows `CURRENT`
  to the release manifest and discovers the complete catalog by role/schema.
  It selects the decoder by `media_type`, verifies both manifest and data hashes,
  and checks the decoded schema and record count. It never guesses file suffixes.
- An in-memory object implementing `load` supplies deterministic test data.
  HTTP failures stay failures; they never become an empty or complete collection.
- `openPublicationReader` opens one immutable release for real archive browsing.
  Its `search`, `getRelated`, `getRecord`, `getRecords` and `getCoverage` methods use
  published query pages and hashed locator shards to fetch only requested data.
  The reader verifies every artifact and caches eight completed files. Queries
  stay on one release even if `CURRENT` changes; open a new reader to refresh.
- `getQueryInfo` supplies available Congresses, record kinds and committee labels.
  Search defaults to the latest Congress, filters before pagination, and returns
  at most 100 rows. `congress: 'all'` is an explicit archive-wide query. At most
  four query pages transfer concurrently; two ordinary query sets are cached.
- Filtered coverage counts the published evidence state of each matching meeting
  entry. It uses the same filters as search and does not repeat the Python rules
  that decide a meeting's evidence state. Committee group counts overlap for
  jointly convened meetings.
- Browser artifacts use explicit gzip JSON media types and the native browser
  decompression API. The complete Catalog and legacy meeting index stay outside
  the deployed browser distribution.

To change to Parquet, supply a decoder that maps the published columns into the
same domain records, or supply a different `ExplorerDataSource` if querying must
happen in a worker or on a server. Keep stable string IDs, date precision,
unknown values, evidence and relationship meanings intact. Decode Parquet
integers/bytes/nested columns at this boundary, not inside chart components.
Load a Parquet/WASM library only in the selected adapter. No such dependency is
included today; the tests exercise decoder substitution with a stub.

The first full retained-data check used a 9.6 MB meeting index. Production queries
replace that transfer with compressed pages scoped by record kind and Congress.
See the
[execution receipt](../../../../../packages/committee_meeting/INTEGRATION_EXECUTION.md)
for the pinned release and remaining limits.

The `load` method is intentionally for a bounded complete snapshot. The public
explorer uses an `ExplorerReader`, which provides paginated search and
partitioned details. Keep storage paths,
SQL, Arrow tables and Parquet row groups outside UI props. The byte decoder can
use the supplied `schemaName`/`schemaVersion` to reconstruct each normalized
artifact. Do not create a global service container or a format flag in every
component.

`committee_meeting` owns full domain validation and the schema version. The
frontend checks compatibility and basic identity/collection structure before
rendering; it does not duplicate the Python graph validator. The interface uses
the TypeScript domain union in `catalog.generated.d.ts`, generated directly from
the Python schema. Run `npm run generate:explorer-types` from `apps/site` after
model changes; `npm run check:explorer-types` detects drift. Set
`COMMITTEE_PYTHON` if the model's dependencies use a different interpreter.

The existing YouTube dashboard uses the same pattern with its separate
`CoverageReportSource` in `../dashboard/report-source.ts`. `Dashboard` chooses
the CSV adapter inside the hydrated island; `CoverageDashboard` receives the
source as a prop and renders normalized `ReportRow` values. Its video population
and Event ID definition remain separate from meeting coverage.

Run the data-boundary and chart checks from `apps/site`:

```sh
npm run test:explorer
```
