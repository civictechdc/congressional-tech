# Committee Explorer data

The UI receives one `ExplorerReader` with `search`, `getRecord`, `getRelated` and
`getCoverage`. React components know nothing about Parquet, URLs or HTTP ranges.
`openPublicationReader` chooses the reader from the release manifest.

Production exports six logical tables:

| Table | Contents |
| --- | --- |
| `meetings.parquet` | Dates, committees, status, search fields and coverage states |
| `committees.parquet` | Committee names and Congress |
| `materials.parquet` | Documents and recordings, direct file links and meeting/witness IDs |
| `witnesses.parquet` | Meeting-specific names, roles, positions and organizations |
| `issues.parquet` | Known issues, explanations and recorded resolutions |
| `sources*.parquet` | Provider metadata and complete retained source payloads |

The current retained corpus needs two source files to stay below GitHub's 100 MB
file limit: seven Parquet files in total. A small `queries.json` supplies available
Congresses, counts and committee labels. `CURRENT.json` selects an immutable
release manifest. There are no record files, locator shards or inverse-reference
files in a Parquet release.

`parquet-source.js` uses Hyparquet, loaded only for Parquet releases. It reads
selected columns and row groups through HTTP byte ranges. Results retain their
physical row positions so opening a result can read that row directly. Searches
and charts never load source payloads. The source table's `payload` column holds
JSON because upstream providers have different schemas; the browse columns,
file links and meeting/witness associations are typed Parquet columns.

The publisher checks complete file hashes. The browser checks the manifest hash,
row counts and HTTP range lengths against an immutable release. It does **not**
claim to verify a whole-file hash from partial reads. Hosting must return `206`
and a valid `Content-Range`; a host that ignores ranges produces an explicit
error instead of silently downloading the full catalog.

Details show useful facts and direct file links. Empty optional values are
omitted. Source evidence expands inline on demand, including the raw payload and a
public-source link. Known issues include their selected and alternative values where recorded.
Issues on internal versions or checks lead to their visible document or meeting.
Legacy differences between collector placeholder edition labels are explicitly
dismissed in the browser tables; their original values remain inspectable.
Witness search includes recorded positions and organizations. Coverage choices
and compatible filters persist in shareable URLs and browser history.

Known issues and coverage
remain separate from empty fields: an unchecked source does not mean a missing
document. The UI does not expose internal editions, representations or association
objects as navigation steps.

Meeting details retain legislative subjects. Document details include their
explicit amendment, vote, bill and en bloc context; actions without a file remain
listed on the meeting. Documents and witnesses have separate counts and paging.
Related-file lookups use meeting/witness IDs, including files shared across
Congresses. Witness ownership requires an explicit source association.

Recording links are hidden before the scheduled start and for canceled or
postponed meetings. Date-only events stay hidden through that calendar day in
Washington. Elapsed schedules display as `Past`, preserving `source_status`;
the date alone does not establish that a meeting was held. Congress.gov event
pages are retained as source evidence, not counted as separate recordings.
Each recording uses one preferred player URL.

The exact source `documentType` is preserved as `document_type`, displayed and
searchable. Our normalized `category` remains separate; it never replaces that
source value. The native document label supplies a title when no name or description exists
(for example, `Witness Statement`). Truth-in-testimony forms are disclosures.
Business meetings have a distinct type and filter. When a generic `Meeting`
record explicitly says business meeting in its title, the classification records
that basis and keeps the original source type.

The old JSON reader remains for existing releases and the bounded design preview.
The current publisher CLI defaults to Parquet; Python callers can explicitly use
`format='json'` for compatibility. Model validation and historical issue/ID state
still run upstream. This change removes JSON packaging and graph navigation; it
does not replace acquisition or the normalized model with a new matching system.

Frontend changes deploy the existing published files. Data/source changes trigger
the exporter. To convert an existing local release without rebuilding records:

```sh
python -m committee_explorer.parquet --input path/to/old-release --output path/to/parquet-release
```

Run `npm run test:explorer` from `apps/site`. The tests build a small real Parquet
fixture with the Python exporter, then exercise range reads, filtering, detail
links, coverage, source retrieval, cancellation and bad HTTP responses. They use
the repo's `.venv` when present, or `EXPLORER_PYTHON` / `COMMITTEE_PYTHON`.
