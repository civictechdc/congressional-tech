# Congress Explorer MCP

A local FastMCP server for the current Congressional Document Archive and its
phase 2 entities. It reads one immutable release: every Parquet table, every
published column, and native nested lists/structs. DuckDB **2.0.0** and FastMCP
**4.1.4** are pinned in this app's own `uv.lock`.

This is a replacement implementation. It has no pre-v6/v6 readers, separate
committee catalog, legacy parser imports, review overlays, copied DuckDB database,
or custom SQL language. The producer owns data assembly and SpicyRegs imports;
the MCP queries the published result. It stays a separate Congress server.

## Run locally

From the repository root, on macOS or Linux:

```sh
uv sync --locked --project apps/explorer_mcp
uv run --locked --project apps/explorer_mcp congress-explorer-mcp prepare
uv run --locked --project apps/explorer_mcp congress-explorer-mcp serve
```

`prepare` defaults to the public archive pointer and stores metadata under
`~/.cache/congress-explorer-mcp`. `serve` uses stdio and makes no network requests.
Use `--data-dir /absolute/path` on each command to select another directory.
`inspect` prints the selected release and published table counts.

For a retained or test release:

```sh
uv run --locked --project apps/explorer_mcp congress-explorer-mcp prepare \
  --publication /absolute/path/to/manifest.json \
  --archive-origin https://congressional-data.spicygov.ai \
  --data-dir /absolute/path/to/mcp-data
```

`--publication` accepts the current pointer or a direct release manifest, as a URL
or local path. Remote publications supply the body archive origin automatically.
For local inputs, omit `--archive-origin` if body URLs are unknown; the server
returns null saved URLs instead of guessing.

Configure an MCP client with absolute paths:

```json
{
  "mcpServers": {
    "congress": {
      "command": "/absolute/path/to/repo/apps/explorer_mcp/.venv/bin/congress-explorer-mcp",
      "args": ["serve", "--data-dir", "/absolute/path/to/mcp-data"]
    }
  }
}
```

The independent environment is deliberate: producer packages still pin DuckDB
below 2. The MCP imports none of those packages. Do not install it into the
producer's environment.

## Six tools

| Tool | Purpose |
|---|---|
| `get_dataset_info` | Available tables, coverage and published relationship/recipe IDs. Pass `table` for columns, identity and incoming/outgoing IDs; `relationship` for join meaning; `recipe` for bounded SQL examples. Also accepts `table: "schema"`, `"capture_scope"`, and `"capture_profile"`. |
| `search_documents` | Title/filename search and exact Congress, kind, format, committee, meeting, bill/nomination, member or witness filters. |
| `get_document` | A document's summary, paged source links, or paged recoveries. |
| `search_entities` | Search the eight phase 2 entity tables with text and exact scalar filters. |
| `get_entity` | One entity by its published key, or its directly associated documents. |
| `query_sql` | One read-only DuckDB `SELECT`, including `WITH` and FROM-first SQL, with optional `?` parameters. All published tables are available. |

Except for `get_dataset_info`, arguments are inside a `query` object. For example:

```json
{"query":{"measure_key":"119-hr-1","limit":10}}
```

Document results include a `reference` containing `release_id` and `link_key`.
Pass those fields to `get_document`, adding `section: "sources"` or
`section: "recoveries"` when needed. Page cursors belong to the same release,
filters and page size. A running server stays on its selected release; run
`prepare` and restart it to adopt a newer one.

Entity keys:

| Table | Key |
|---|---|
| `meetings` | `event_id` |
| `witnesses` | `witness_key` (an appearance, not a deduplicated person) |
| `recordings` | `video_key` |
| `committees` | `system_code` |
| `members` | `bioguide_id` |
| `bills` | `bill_id`, e.g. `119-hr-1` |
| `nominations` | `nomination_id`, e.g. `119-pn-730-2` |
| `rosters` | Compound fields; use `search_entities` or SQL |

File URLs follow the recorded body hash and exact suffix. Summaries include
alternate formats; recordings include saved caption/transcript track URLs.
Recovery records retain `kind` and `identity_note`: a substitute or related file
is not necessarily the requested original. Fetch and read the files with the
agent's own tools. The MCP searches metadata and does not download, extract, OCR,
or search document bodies.

Hidden documents are excluded from ordinary searches and entity document pages.
An exact document reference still resolves and exposes its review explanation.
SQL exposes all rows, including hidden rows; add a filter when needed.

## Query relationships directly

Start with `get_dataset_info`. For releases publishing native relationship
metadata, call it with `{"table":"witnesses"}`, then
`{"relationship":"witness_submitted_documents"}` or
`{"recipe":"witness_transcripts"}`. Use one selector at a time. The response
explains keys, result grain, parameters and missing required tables. Recipes do
not run until the caller submits their SQL to `query_sql`.

The producer owns this metadata in `schema.json`; the MCP has no separate join
registry. New definitions within the supported metadata version appear without
MCP changes. Older releases report that relationships were not published, and
unknown versions report unsupported metadata while table and SQL access remain
available. The complete producer reference is generated at
[`docs/release-relationships.md`](../../docs/release-relationships.md).

These examples use the defined phase 2 fields and require those tables in the
selected release.

Documents about a bill, including their saved file identifiers:

```sql
SELECT filename, title, hex(link_key) AS link_key,
       hex(saved_body) AS body, saved_suffix
FROM documents
WHERE list_contains(measure_keys, ?) AND NOT coalesce(hidden, false)
ORDER BY list_row
```

Hearings about a measure and their witnesses:

```sql
SELECT m.event_id, m.title, m.meeting_date, w.witness_key,
       w.name, w.position, w.organization
FROM meetings m
LEFT JOIN witnesses w ON w.event_id = m.event_id
WHERE list_contains(m.subject_keys, ?)
ORDER BY m.event_id, w.panel_order, w.display_order, w.witness_key
```

Transcript documents and recordings for a meeting:

```sql
SELECT m.event_id, t.package_id, d.filename, hex(d.link_key) AS link_key
FROM meetings m, UNNEST(m.transcripts) AS u(t)
LEFT JOIN documents d ON d.list_row = t.list_row
WHERE m.event_id = ?
```

```sql
SELECT video_key, tracks
FROM recordings
WHERE list_contains(event_ids, ?)
```

Member terms, votes, amendments, CBO estimates, committee history and cross-system
IDs remain native nested fields. SQL can unnest, filter, join or aggregate them.
New Parquet tables appear automatically without an MCP release. Entity convenience
tools cover the named phase 2 tables; use SQL for any additional tables.

`list` and `detail` gain a virtual, zero-based `list_row`. Detail shards use their
declared row offsets; sources and recoveries retain their physical `list_row` and
`ordinal`. `documents` joins list and detail without copying them. The raw `links`,
`urls`, URL state/variants and every other published table remain queryable.

SQL returns actual column types, bounded rows, and a `truncated` flag. BLOB values
use DuckDB's JSON escaping; use `hex()`/`unhex()` for portable keys. Fractional
numbers return as strings to preserve precision; integers, booleans, nulls, lists
and objects retain their JSON types. Alias duplicate columns explicitly.

## Cost and lifetime

Preparation streams each changed file once, checking SHA-256 during the transfer.
It verifies Parquet footer counts without scanning all rows, then atomically
selects the completed release. An unchanged preparation reads the pointer/manifest
and checks local file metadata; it does not recopy, rehash or decode retained data.
A failed attempt keeps the prior selection and reuses completed downloads on retry.
The cache is app-owned; do not edit its immutable objects or `selection.json`.

Serving creates views over those exact files. There is no persistent DuckDB copy
or Python table cache. One query worker uses two DuckDB threads, a 512 MB engine
memory limit, 512 MB spill limit, and a default 10-second execution deadline.
`serve --query-timeout` can change the deadline up to 120 seconds. Up to four
queries can wait behind the active one. Cancellation or timeout stops and reaps
the worker and removes its spill directory; the next request starts a new worker.
The engine memory limit is **not** a process RSS limit.

Responses are capped at 128 KiB, browse pages at 100 rows, SQL results at 200 rows
and 128 columns. A single oversized row produces an actionable error; select fewer
fields or slice nested lists. Reads are limited to selected metadata files. Network
access, writes, extension autoloading, persistent secrets and configuration changes
are disabled in the query runtime.

Completed objects remain reusable and may still be in use by an older running
server. Preparation therefore does not delete old objects. To retire a cache,
stop every server using that data directory, remove that directory, then prepare
again. The next preparation removes its interrupted download and selection files
after acquiring the exclusive prepare lock. It keeps completed objects for live
readers and rollback. If the server is killed, its worker detects parent death,
interrupts DuckDB, closes the connection and removes its own spill directory.
An unexpectedly killed worker produces a retryable error; the next call starts
a new worker.

To roll back, prepare the previous immutable release manifest and restart the
server. Existing servers remain on their selected release. If a cached object is
corrupt, preparation refuses it and preserves the current selection; prepare into
a fresh data directory to recover, then retire the old cache after its readers stop.

## Check it

```sh
apps/explorer_mcp/.venv/bin/python scripts/dev.py test explorer-mcp -- -q
```

The root runner dispatches to the app's locked environment. Tests cover the
canonical archive fixture, phase 2 entity shapes, raw SQL and relationships,
shards, duplicates, missing versus empty data, failure/reuse, SQL restrictions,
byte limits, subprocess cancellation and real stdio MCP calls. The dedicated CI
workflow also builds the native phase 2 fixture and consumes its actual output
over stdio in the independent MCP environment. See [verification](VERIFICATION.md)
and [production measurements](../../docs/measurements/congress-mcp-production-20261030.md).

Published data availability is separate from reader support. Absent tables are
reported as unavailable; an empty table means zero published rows; nulls remain
unknown. The server cannot supply phase 2 fields before producers publish them.
The current model is defined by [the data model](../../docs/engine-first-data-model.md)
and [the phase 2 annex](../../docs/plans/phase-2-annex-20261028.md).
