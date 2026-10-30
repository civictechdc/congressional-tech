# Local verification — 2026-10-30

## Current production acceptance

The MCP and native relationship metadata are merged to main. Public release
`0db23484fe86c7f5a5e50e44f078ec34e74e793873b26c4a15f0b9e9efa17b69`
publishes all 16 table definitions, 59 relationships and 10 SQL recipes. This
metadata-only update preserves every Parquet byte from the deployed phase 2
release. Fresh public preparation, native relationship checks, built-site checks
and the HTTPS saved-file check passed.

The current local MCP suite passes **55 tests**, including a newly produced
native phase 2 release consumed through real stdio. Recovery checks include
server SIGKILL during native spill, worker death, SIGKILL during preparation,
disk-full failures during payload and selection writes, reset/truncated
transfers, rollback, corrupt old objects and protection of live readers.
Disk-full errors are injected; the kill tests use real subprocesses and files.

CI results, full-data timing/RSS and acceptance limits are recorded in
[the production report](../../docs/measurements/congress-mcp-production-20261030.md).
The sections below retain earlier observations and their historical limits.

## Earlier implementation baseline

The greenfield MCP uses DuckDB 2.0.0 and FastMCP 4.1.4 in its independent locked
environment. No producer package, legacy catalog adapter, or persistent DuckDB
copy is imported or built.

- **36 tests passed at the earlier MCP baseline**, including real FastMCP stdio tool calls, phase 2 joins,
  native nested fields and precision, sharded row positions, duplicate sources,
  missing/empty tables, query restrictions and byte limits, worker timeout,
  cancellation, restart and spill cleanup, interrupted preparation, reuse, and
  dispatch through the repository test runner.
- `uv lock --check`, Python compilation and `git diff --check` passed.
- At this earlier baseline, CI was configured in `validate-congress-mcp.yml`; remote CI had not run.
- At that baseline, production Python source measured **792 lines**, compared
  with **2,907** in the earlier local MCP. This was a code-size observation, not
  a runtime speedup. The original task checkout later disappeared; the current
  checkout recovers the saved MCP work on current main. New discovery code changes
  that earlier line count.

## Earlier live verification: phase 2 deployed

Refreshed the local MCP cache and checked release
`a06e2a636d3c765f81be13712f496aa25a0dec50d7055ea8a1dbb18f0ebf1e25`
through an actual FastMCP stdio connection. All eight phase 2 tables are now
published and available without reader changes:

| Table | Published rows |
|---|---:|
| Meetings | 18,687 |
| Witness appearances | 56,066 |
| Recordings | 12,033 |
| Committees | 817 |
| Members | 12,770 |
| Roster entries | 2,973 |
| Bills | 11,832 |
| Nominations | 747 |

The archive still contains **367,008 documents**. Live checks passed for schema
inspection and browsing each entity table, individual entity lookup, associated
document queries, document summaries/sources/recoveries, and custom SQL. Real
bill-to-hearing-to-witness and witness-to-document joins returned populated
results; the latter also matched the entity document tool.

There are **18,140 titled and dated meetings**, **11,467 meetings with transcript
links**, and **1,357 recordings with saved tracks**. Document relationship fields
are populated for **196,050 documents linked to meetings**, **35,345 linked to
witnesses**, **23,399 linked to measures**, **154,058 linked to committees**, and
**26,721 linked to members**. These are published associations, not a claim of
complete congressional coverage.

No production code changes were needed for that deployment recheck. Its live
cache and `phase2-mcp-check.json` were lost with the original task checkout.
These are retained historical observations, not a fresh live check in this
reconstructed worktree.

## Earlier release: resource measurements

Prepared and queried release
`a64ff58ee289dfc7d7ab163dcdc78983a6e6b191d7ab0adf7260b0883332c485`
from the public archive. Retained metadata totals **61,687,498 bytes**; no document
body was downloaded.

| Measurement | Single local observation |
|---|---:|
| Initial preparation, elapsed | 5.17 s |
| Initial preparation, peak RSS | 75.8 MiB |
| Unchanged preparation in another process, elapsed | 0.44 s |
| Query worker startup and dataset info | 129 ms |
| Warm `testimony` title/filename search, five rows | 55 ms |
| Aggregate across documents | 12 ms |
| Query worker peak RSS over the sampled queries | 137 MiB |

These are macOS observations, not benchmarks against the old implementation.
The worker's RSS excludes the FastMCP parent. A 512 MB DuckDB memory setting does
not cap total process RSS. Tests instrument the unchanged prepare path: no
payload opening or Parquet footer reads occur after the manifest and local file
metadata establish that the selected release is unchanged.

Before phase 2 deployment, that earlier release returned **367,008 documents**,
**18 distinct non-null Congress values**, and **13,253 meetings with zero populated
titles**. Its seven missing entity tables are present in the newer release above.
The earlier timing and memory observations have not been remeasured for phase 2.

The earlier `.cache/congress-mcp-phase2-live` cache is no longer present in this
worktree. Preparing a live release again is separate from the local checks below.


## Native relationship metadata — local verification

The producer registry now describes **16 tables, 59 relationships and 10 bounded
DuckDB recipes**. `archive_schema` generates `docs/release-relationships.md` and
the existing publication writer adds release availability to `schema.json`.
The archive schema version stays 1; relationship metadata has its own version 1.

- **21 focused producer tests passed** through the repository production runner,
  including the real native phase 2 fixture, hand release and converted-catalog
  fixtures. Checks cover generated-doc drift, paths/types, unique target keys,
  null/duplicate identities, missing required nested targets, actual Parquet
  footer types, publication metadata and immutable manifest hashes.
- **44 MCP tests passed**, including real stdio relationship/recipe discovery,
  every SQL recipe, positive transcript participation versus document ownership,
  list multiplication, unavailable tables, future v1 entries, older releases
  without metadata, unsupported metadata versions, and response limits.
- A separate real stdio check consumed the new native phase 2 fixture release
  `f90bba47fadc2b0bae61f729c65e7ccfb3b221fa803e150222ec595822604571`.
  All six tools remained available; it inspected all 16 table identities, all
  59 relationships and executed all 10 recipes in DuckDB 2. The default discovery
  response was **18,397 bytes**, below the existing 128 KiB limit.
  The retained local report is `.cache/native-relationships/stdio-smoke.json`.

Commands used from the repository root:

```sh
DOCSPEC_JOB_CONFIG="$PWD/.cache/native-relationships/runtime.json" \
  .venv/bin/python scripts/dev.py test production-offline \
  --path packages/viewer_publication/tests/test_archive_schema.py \
  --path packages/viewer_publication/tests/test_archive_release.py \
  --path packages/viewer_publication/tests/test_phase2_model_entities.py \
  -- -q --basetemp=.cache/native-relationships/verified
apps/explorer_mcp/.venv/bin/python scripts/dev.py test explorer-mcp -- -q
.venv/bin/python -m viewer_publication.archive_schema --check
```

The metadata build reads small JSON definitions. Key/reference checks reuse the
native publication job's materialized relations and existing construction
checks; physical field validation reads output footers only. No full-corpus
replay, document-body read, extra Parquet row scan, remote CI run or deployment
was performed for this change. These checks establish local producer-to-consumer
behavior, not that the deployed release already contains the new metadata.
