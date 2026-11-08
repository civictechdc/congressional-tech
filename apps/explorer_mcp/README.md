# Congress Explorer MCP

<!-- mcp-name: io.github.civictechdc/congress-explorer -->

Explore congressional hearings, witnesses, bills, members, recordings, and related
documents from your AI assistant. Free and open source. No data API key required.
Start with the [setup guide](https://civictechdc.github.io/congressional-tech/mcp/).

Version 0.6.4 improves unfiltered ballot paging while preserving vote dates,
row ordering and saved cursors. It can use the current archive selection.
To refresh your local selection, run `congress-explorer-mcp prepare`.

A FastMCP server for the current Congressional Document Archive and its
phase 2 entities. It reads one immutable release: every Parquet table, every
published column, and native nested lists/structs. DuckDB **2.0.0** and FastMCP
**4.1.4** are pinned in this app's own `uv.lock`.

This is a replacement implementation. It has no pre-v6/v6 readers, separate
committee catalog, legacy parser imports, review overlays, copied DuckDB database,
or custom SQL language. The producer owns data assembly and SpicyRegs imports;
the MCP queries the published result. It stays a separate Congress server.

## Quick setup

For browser clients, the [Cloudflare deployment](cloudflare/README.md) exposes
the same tools at an HTTPS `/mcp` endpoint. It runs the existing Python and
DuckDB server in Cloudflare Containers behind a Worker; clients need no local
Python, Node.js, or desktop installation.

### ChatGPT web

Use **Congress Explorer Web** (`congress-explorer-web`) for the hosted connection:

```text
https://congress-explorer-mcp.mdeeb.workers.dev/mcp
```

In [ChatGPT Plugins](https://chatgpt.com/plugins), choose **Add custom MCP server**,
enter this URL, select **No authentication**, and create and install the plugin.
The [web plugin source](web/README.md) also packages the research skill for
supported plugin import and submission workflows. Download
[congress-explorer-web-0.6.4.plugin.zip](https://github.com/civictechdc/congressional-tech/releases/download/congress-mcp-v0.6.4/congress-explorer-web-0.6.4.plugin.zip)
for those workflows; connecting the URL directly adds the research tools.

The current plugin format does not define a browser/desktop transport selector.
We supply separate packages: `congress-explorer-web` uses the hosted endpoint;
`congress-explorer` uses local stdio on desktop. Select the matching plugin for
the session. A repository marketplace entry does not register a browser account's
connection. See the [OpenAI packaging guide](https://developers.openai.com/plugins/build/plugins#bundled-mcp-servers-and-lifecycle-hooks).

For desktop clients on macOS or Linux, the server is available as a Claude Desktop extension and a plugin compatible
with Claude Code/Cowork and ChatGPT/Codex desktop. The first tool call downloads
the public snapshot and its text index when published. Tool discovery does not download data; later sessions
reuse the selected release. Document bodies are fetched separately when requested.

### Claude Desktop chat

Download [congress-explorer-0.6.4.mcpb](https://github.com/civictechdc/congressional-tech/releases/download/congress-mcp-v0.6.4/congress-explorer-0.6.4.mcpb),
open it with Claude Desktop, and click **Install**. Use a current Claude Desktop
with support for MCPB 0.4's uv runtime; the host manages Python and dependencies.
Alternatively, select the file in Settings → Desktop app → Extensions → Advanced
settings → Install Extension. Ask your first congressional question to prepare data.

### Claude Code and Cowork

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) on the host,
then use a current Claude Code (2.1.275 or later):

```sh
claude plugin install congress-explorer --marketplace civictechdc/congressional-tech
```

Inside Claude Code, the equivalent is
`/plugin install congress-explorer --marketplace civictechdc/congressional-tech`.
In Cowork desktop, open Customize → Plugins and upload
[congress-explorer-0.6.4.plugin.zip](https://github.com/civictechdc/congressional-tech/releases/download/congress-mcp-v0.6.4/congress-explorer-0.6.4.plugin.zip).
Start a local task and run `/congress-explorer:explore-congress`.
The plugin's local server runs in Claude Code and Cowork desktop; Claude chat uses
the separate `.mcpb` extension above. Organization policies may restrict installation.

### ChatGPT and Codex desktop

Install uv and the Codex CLI, then:

```sh
codex plugin marketplace add civictechdc/congressional-tech --ref congress-mcp-v0.6.4 --sparse .agents/plugins --sparse apps/explorer_mcp
codex plugin add congress-explorer@congressional-tech
```

Open a local conversation in the desktop app and select Congress Explorer. The
website's **Explore Congress in Codex** button opens a prepared question; it does
not send it automatically. This is a repository marketplace distribution, not an
approved public OpenAI directory listing. A public listing for a local MCP server
requires separate partner approval.

The desktop source plugin root is this directory. `plugin.json` and `mcp.json` describe
the portable OpenAI package; `.claude-plugin/plugin.json` and `.mcp.json` describe
the Claude package. Both run `uvx` with `congressional-explorer-mcp==0.6.4` from
PyPI. The Claude extension uses a tiny Python launcher with the same pinned
PyPI dependency. Neither archive contains a copy of the server source.
`scripts/build_desktop.py` generates the client-specific metadata from `server.json`;
do not edit the generated manifests by hand. It also generates the independent
web plugin under `web/` and emits `congress-explorer-web-VERSION.plugin.zip`.
The web package contains one remote MCP connection and copies of the shared
research skill and assets; generation checks keep these copies identical.

### Install the research skill with npx

With Node.js 22.20 or later, run this from the project where you want the skill:

```sh
npx skills add civictechdc/congressional-tech --skill explore-congress
```

Choose your agent, or append `--agent claude-code` or `--agent codex`. Add `--global`
to make the skill available across projects. Then ask your agent to use
`explore-congress` for a congressional question or to help connect Congress Explorer.

This installs the skill's instructions. It does **not** install or register the
MCP server. The full plugin already includes the same skill; no separate skill
install is needed. The skill links to the client setup guide if the server is
missing. The Skills CLI discovers it through our existing Claude marketplace
manifest. See the [Skills CLI documentation](https://github.com/vercel-labs/skills/blob/main/docs/commands.md#skills-add).

The GitHub shorthand reads the default branch. To try a checkout before merging,
run `npx skills add . --skill explore-congress` at the repository root.

## Manual install (macOS or Linux)

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```sh
uv tool install --python 3.12 congressional-explorer-mcp==0.6.4
congress-explorer-mcp prepare
congress-explorer-mcp check
```

If the command is not on your shell's PATH, run `uv tool update-shell` and open
a new terminal. `check` should report `"status": "ok"` and the declared package tools. It launches
the installed server and exercises discovery, document and batch reads, compact entities,
legislative detail, hearing discovery, named queries and SQL diagnostics through MCP.
Its report labels coverage unavailable on older snapshots. Python 3.12
is managed by uv. Windows is not supported yet.

Print configuration for your client:

```sh
congress-explorer-mcp config --client claude-desktop
congress-explorer-mcp config --client codex
congress-explorer-mcp config --client cursor
congress-explorer-mcp config --client claude-code
```

Choose one. These commands print settings with absolute paths and never edit the
client's configuration. Merge the output into the appropriate settings, preserving
other servers, then restart the client connection:

| Client | Configuration |
|---|---|
| Claude Desktop | Settings → Developer → Edit Config; merge into `mcpServers` |
| Codex | Add or replace `[mcp_servers.congress]` in `~/.codex/config.toml` |
| Cursor | Merge into `mcpServers` in `~/.cursor/mcp.json` |
| Claude Code | Save JSON to a file and pass `--mcp-config /absolute/path/to/file.json` when starting Claude Code |

The client starts `serve` for you. There is no port to open or terminal to keep
running. Ask: “Use Congress Explorer to find documents related to H.R. 1 in the
119th Congress.” Your assistant needs its own tools to fetch and read linked files.

Run `prepare` again and restart the client connection to refresh data. Software
updates are separate: install the desired PyPI version with `uv tool install
--upgrade --python 3.12 congressional-explorer-mcp==VERSION` and restart the client.
Update the plugin or extension to adopt its new pinned version. Preparation downloads
every asset named by the selected release, including its searchable text index.
Check the immutable release manifest for current download bytes; the Python runtime,
dependencies, extracted-text cache and query scratch require additional disk space.

Queries run locally, but your AI client may send prompts and tool results to its
model provider. Coverage varies by source and Congress. This is a bounded published
collection, not a complete record of every congressional activity.

## Run from source

From the repository root, on macOS or Linux:

```sh
uv sync --locked --project apps/explorer_mcp
uv run --locked --project apps/explorer_mcp congress-explorer-mcp prepare
uv run --locked --project apps/explorer_mcp congress-explorer-mcp serve
```

`prepare` defaults to the public archive pointer and stores release assets under
`~/.cache/congress-explorer-mcp`. Plain `serve` uses stdio and keeps its selected
release. Reading an original document body can fetch its verified archived bytes;
corpus text search reads the prepared index locally.
Plugins, the desktop extension and the registry launch add `serve --prepare-if-missing`: it starts MCP immediately
and prepares data on the first tool call only when no selection exists. A selected
snapshot is never refreshed or replaced automatically, including if it is damaged.
Use `--data-dir /absolute/path` on each command or `CONGRESS_MCP_DATA_DIR` to select
another directory. Desktop extensions, plugins and manual installs share the
default directory when they run under the same account on the same host.
`inspect` prints the selected release and published table counts.

This checkout also supports stateless Streamable HTTP:

```sh
uv run --locked --project apps/explorer_mcp congress-explorer-mcp serve \
  --transport http --host 127.0.0.1 --port 8080
```

Connect to `http://127.0.0.1:8080/mcp`. The default transport remains stdio.
Streamable HTTP is available starting with version 0.6.0.

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

## Tools

| Tool | Purpose |
|---|---|
| `get_overview` | Compact capabilities, table names, limits and discovery selectors. |
| `get_dataset_status` | Selected release, publication time, latest known publisher updates, observed date bounds and coverage gaps. Unavailable dates stay null. |
| `get_dataset_info` | Available tables, coverage and published relationship/recipe IDs. Pass `table` for columns, identity and incoming/outgoing IDs; `relationship` for join meaning; `recipe` for bounded SQL examples. Also accepts `table: "schema"`, `"capture_scope"`, and `"capture_profile"`. |
| `search_documents` | Title/filename search and exact Congress, kind, format, committee, meeting, bill/nomination, member or witness filters. |
| `get_document` | A document's summary, paged source links, paged recoveries, or verified extracted body text and snippet search (`section: "text"`). |
| `get_documents` | Up to ten document requests in input order with independent errors and paging; shares the single-document verification path and an aggregate response/work budget. |
| `search_text` | Search document, testimony and caption passages in the selected release when it includes a retained text index. Check `get_dataset_status` for availability. In a release without an index, use `get_document` to search within a selected document or `get_transcript` to read a hearing’s transcript or captions. |
| `search_entities` | Search the eight phase 2 entity tables with text and exact scalar filters. |
| `get_entity` | One entity by its published key, with full detail, scalar summary or selected fields; also pages its directly associated documents. |
| `query_sql` | One read-only DuckDB `SELECT`, including `WITH` and FROM-first SQL, with optional `?` parameters. All published tables are available. |
| `get_transcript` | Discover a hearing's official, committee and caption sources, then read bounded pages or timestamped cues by source reference. |
| `get_hearing_bundle` | A hearing dossier with current witnesses, testimony, transcript sources, captions, recording associations and coverage. |
| `resolve_citation` | Reopen an exact retained passage at its PDF/text page or caption cue, preserving release, body and reading identity. |
| `get_bill_actions`, `get_roll_calls`, `get_member_ballots` | Chronological actions, recorded votes and individual ballots with distinct provenance and coverage. |
| `get_activity` | Dated legislative events with supported chamber, committee and subject filters; date bounds are inclusive `since`, exclusive `until`. |
| `run_research_query` | Recent bills, pending nominations, committee hearings and legislation by subject through published recipes. |

`get_overview` and `get_dataset_status` take no arguments. `get_dataset_info`,
`get_transcript` and `get_hearing_bundle` take selectors directly; `resolve_citation`
takes a returned `citation`. Other tools take a `query` object. For example:

```json
{"query":{"measure_key":"119-hr-1","limit":10}}
```

Document results include a `reference` containing `release_id` and `link_key`.
Pass those fields to `get_document`, adding `section: "sources"` or
`section: "recoveries"` when needed. Page cursors belong to the same release,
filters and page size. A running server stays on its selected release; run
`prepare` and restart it to adopt a newer one.

For release qualification, pass `check --probe-plan plan.json --require-research`.
The plan names a retained `event_id`, a release-bound `document_reference`, and a
`search_text` phrase. The check requires real caption, page and search citation
round trips. Use the same plan with `cloudflare/smoke.py`, `check_distribution.py`
and `check_desktop.py` to compare the shipped paths against one release.

`search_documents` keeps archive order by default. Set `sort: "recent"` or
`"oldest"` for chronological lookup. Where the release publishes
`document_date_status`, these modes include accepted dates by default;
`include_suspect: true` and `include_undated: true` explicitly include the other
rows. Literal dates and their published qualification remain visible. Older
releases retain chronological access to literal dates and report that date
qualification is unavailable.

For compact entities, pass `mode: "summary"` or `fields: ["title", "floor_votes"]`.
The published primary key and release identity are always retained. Requested
fields keep their exact values, including nulls and evidence references.
`get_dataset_info(table=...)` lists available fields and the scalar summary
fields. Read omitted fields with `mode: "detail"`, an explicit field list, or SQL
list slicing when a full record exceeds the response cap. Calls without these
options preserve full detail and existing document paging.

For a batch, pass `{"query":{"items":[REFERENCE,{...REFERENCE,"section":"text"}]}}`.
Each result has `status: "ok"`, `"error"`, or `"deferred"`. Successful values
match `get_document`; `next_query` continues a page or retries a deferred item.
The batch runs sequentially with one request deadline, at most 64 MiB of declared
archived body bytes, and a 128 KiB aggregate response. Unknown body sizes reserve
the full body budget. Each extracted body also keeps the existing decompressed
size limit. Continue deferred items individually or in a smaller batch.

Publication time is recorded at the publisher's conditional release selection
and observed once during preparation. It differs from source-update dates,
document dates and archive captures. A pinned immutable manifest can retain that
date only when the current public pointer identifies the same release; unavailable
metadata stays null. Tool calls read the retained observation and do not fetch a
mutable pointer.

Entity keys come from the selected release's `schema.json`: every file whose
`identity` is a published-identifier primary key (`get_dataset_info` returns
them as `entity_keys`, and absent ones as `missing_entities`). Document links are
the schema's `list.<column>[]` relationships to that key. In the current release:

| Table | Key |
|---|---|
| `meetings` | `event_id` |
| `witnesses` | `witness_key` (an appearance, not a deduplicated person) |
| `recordings`, `videos` | `video_key` |
| `committees` | `system_code` |
| `members` | `bioguide_id` |
| `bills` | `bill_id`, e.g. `119-hr-1` |
| `nominations` | `nomination_id`, e.g. `119-pn-730-2` |
| `channels` | `handle` |
| `recording_matches` | `match_id` |
| `committee_records` | `record_key` |
| `rosters`, `meeting_coverage`, `url_variants` | Compound fields; use `search_entities` or SQL |

A release whose schema states no identity has no entity keys; use `query_sql`.
`upstream_relations` in `get_dataset_info` name SpicyRegs detail tables (bill
actions, cosponsors, member ballots, ...) with their pinned generation; the MCP
does not read them. `search_documents` rows carry `document_date_source`
(filename, content or meeting) beside `document_date`, and `date_kind` beside
`first_captured`; none of these is a page-update date.

Entity IDs and integer entity filters accept integers or base-10 integer strings.
Leading zeros and surrounding whitespace normalize to the same value, including
when continuing a page. Decimal spellings, scientific notation, booleans and
out-of-range values return validation errors. Text identifiers stay exact;
boolean filters take `true` or `false`. General `query_sql` parameters retain
DuckDB's normal SQL behavior.

File URLs follow the recorded body hash and exact suffix. Summaries include
alternate formats; recordings include saved caption/transcript track URLs.
Recovery records retain `kind` and `identity_note`: a substitute or related file
is not necessarily the requested original. Pass `section: "text"` to `get_document`
(with optional `page`, `offset`, `max_chars`, or `query`) to fetch, verify against
`saved_body` SHA-256, and read or search extracted text from saved PDF, HTML, XML,
and text bodies while keeping the DuckDB query worker air-gapped. The server does
not perform OCR on image-only PDFs or cross-corpus full-text indexing.

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
[`docs/release-relationships.md`](https://github.com/civictechdc/congressional-tech/blob/main/docs/release-relationships.md).

These examples use the defined phase 2 fields and require those tables in the
selected release.

For hearing transcripts linked through meeting subjects, discover the
`bill_hearing_transcripts` recipe when the selected release publishes it. It
returns each visible transcript once, with the distinct supporting meeting IDs.
It can find transcripts whose direct `measure_keys` are empty. The
`bill_documents` recipe and `search_documents`'s `measure_key` filter match direct
document annotations only. Existing releases need updated publication metadata
before they advertise the new recipe.

Documents directly annotated with a bill, including their saved file identifiers:

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
over stdio in the independent MCP environment. See [verification](https://github.com/civictechdc/congressional-tech/blob/main/apps/explorer_mcp/VERIFICATION.md)
and [production measurements](https://github.com/civictechdc/congressional-tech/blob/main/docs/measurements/congress-mcp-production-20261030.md).

Published data availability is separate from reader support. Absent tables are
reported as unavailable; an empty table means zero published rows; nulls remain
unknown. The server cannot supply phase 2 fields before producers publish them.
The current model is defined by [the data model](https://github.com/civictechdc/congressional-tech/blob/main/docs/engine-first-data-model.md)
and [the phase 2 annex](https://github.com/civictechdc/congressional-tech/blob/main/docs/plans/phase-2-annex-20261028.md).
