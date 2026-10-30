# Congress MCP verification — 2026-10-30

The MCP runs locally over stdio with DuckDB 2.0.0 and FastMCP 4.1.4 in its own
locked environment. It queries published Parquet files directly.

## Current checks

- **55 MCP tests passed locally**, including the actual native producer's phase 2
  output consumed through FastMCP stdio. All six tools, 16 table definitions,
  59 relationships and 10 SQL recipes are covered.
- [MCP CI passed on committed main](https://github.com/civictechdc/congressional-tech/actions/runs/41087258770):
  54 app tests pass; the one native integration test runs and passes in the
  separate producer-to-consumer job, alongside 61 producer/profile/retention tests.
- Focused producer checks passed: 19 schema/release tests, 27 semantic-profile
  tests, the real phase 2 fixture, and 17 XML-recovery tests.
- The generated relationship reference, dependency lock, Python compilation and
  whitespace checks passed.
- Full public-release timing, total server RSS, publication checks, update and
  rollback results, and broader CI disposition are recorded in
  [the production report](../../docs/measurements/congress-mcp-production-20261030.md).

## Published data and recovery

Public release
`0db23484fe86c7f5a5e50e44f078ec34e74e793873b26c4a15f0b9e9efa17b69`
publishes native relationship metadata for all 16 tables. This metadata update
preserves every Parquet byte from the deployed phase 2 release. Fresh public
preparation, native relationship checks, built-site checks and the HTTPS saved-file
check passed. The complete stdio workload executed all ten published recipes.

Ten recovery tests cover server SIGKILL during real native spill, worker death,
SIGKILL during preparation, injected disk-full errors during payload and selection
writes, reset/truncated transfers, rollback, corrupt old objects and protection
of live readers. A separate full-release check exercised update and rollback
while two stdio servers continued answering from their pinned releases.

One initial production query timed out; focused reproductions and the complete
final workload passed with the unchanged deadline. Its cause remains unknown.
The measured RSS is a sampled warm-cache observation, not a process memory limit.
Published field coverage can remain incomplete: the current witness table has
no non-null `package_id`, so transcript participation cannot be recovered through
that field. An absent table, an empty table and an unknown value remain distinct.

## Reproduce native integration

Use the configured local native runtime and the two existing project runners:

```sh
DOCSPEC_JOB_CONFIG=/absolute/path/to/runtime.json \
  .venv/bin/python scripts/dev.py test production-offline \
  --path packages/viewer_publication/tests/test_phase2_model_entities.py::test_phase2_entities_meetings_witnesses_recordings_and_spicy_projections \
  -- --basetemp=/absolute/path/to/native-fixture
apps/explorer_mcp/.venv/bin/python scripts/dev.py test explorer-mcp \
  -- --native-fixture-root /absolute/path/to/native-fixture
.venv/bin/python -m viewer_publication.archive_schema --check
```

The production report includes the separate full-data measurement command.
