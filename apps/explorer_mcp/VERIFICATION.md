# Congress MCP verification — 2026-10-30

The MCP runs locally over stdio with DuckDB 2.0.0 and FastMCP 4.1.4 in its own
locked environment. It queries published Parquet files directly.

## Desktop packages — 0.4.0, local candidate

The `.mcpb` extension and Claude/OpenAI-compatible plugin ZIP are built locally.
Release downloads, a deployment of the new website buttons, and public vendor
directory listings have not been published for this version.

- 61 app tests pass, including first-use preparation, failure/retry, concurrent
  callers, cancellation during setup, reuse of a selected snapshot, and preservation
  of a damaged selection. The separate retained native producer-to-stdio integration
  also passes: 62 tests in total.
- Each built archive was unpacked outside the repository into a directory with
  spaces. The actual MCPB, OpenAI and Claude launch configurations all connected,
  listed six tools before downloading data, prepared the fixture on the first
  call, read a document row and reused the snapshot after restart with an invalid
  publication path. The wheel's existing clean-install check also passes.
- MCPB 2.1.2 validates the bundle manifest. Claude Code 2.1.314 validates the
  plugin and marketplace with `--strict`. The portable manifests validate against
  the official Agent Plugins 1.0.0 JSON schemas.
- A real Claude Code install into a temporary `CLAUDE_CONFIG_DIR` succeeded and
  `claude mcp list` reported `plugin:congress-explorer:congress` as **Connected**.
  Codex CLI 0.165.0 discovers the plugin using a command-line marketplace override.
  Existing user client configuration was not changed.
- Astro builds. Browser checks at 1200 px and 390 px found no horizontal overflow;
  both plugin copy buttons return the exact setup commands, and the manual client
  selector still works. Download URLs point to the planned 0.4.0 release and must
  not be deployed before those assets exist.

Desktop GUI installation in Claude Desktop/Cowork and ChatGPT is not yet manually
qualified. In particular, the host-managed uv install has schema and launch checks,
not a clean-machine GUI check. Linux/macOS archive checks are wired into the release
workflow; that new workflow has not yet run remotely. Windows remains unsupported.

## Local installation and website — 0.3.0

[Release 0.3.0](https://github.com/civictechdc/congressional-tech/releases/tag/congress-mcp-v0.3.0)
is published from `236114f3`. [Release CI](https://github.com/civictechdc/congressional-tech/actions/runs/41094647368)
passed the app suite, strict package checks, and fresh installs on Ubuntu 24.04
and macOS 14. An installation from the public GitHub wheel also passed the MCP
check against the prepared public release (16 tables, six tools).

The [setup page](https://civictechdc.github.io/congressional-tech/mcp/) is live.
[Pages deployment](https://github.com/civictechdc/congressional-tech/actions/runs/41095984681)
passed at `570ce355`, including the existing native archive browser checks,
saved-file sandbox checks and heap checks. Public readback returned HTTP 200 for
the MCP page, homepage and both explorers, with the new setup links present.
Deployment also required removing a deleted test from the inventory, correcting
an obsolete singular-count expectation and restoring wrapping for long archive
format labels. No publication checks were bypassed.

- 57 app tests passed, plus the retained native producer-to-stdio integration:
  58 total. The first native run used a missing fixture path; the targeted rerun
  used the retained `readiness-native` output and passed.
- The built wheel and source distribution pass strict Twine metadata checks.
  A fresh `uv tool install` outside the repository passed preparation, generated
  JSON/TOML configuration, MCP discovery and a document read. A separate installed
  wheel passed `check` against the prepared public release and exposed all 16 tables.
- Claude Code's real `mcp get` reports **Connected** with the generated settings
  in an isolated configuration directory. Codex CLI accepts the generated launch
  settings through a temporary command-line override. Existing user settings were
  not edited. Claude Desktop and Cursor setup UI have not been manually qualified.
- Astro builds the onboarding page. Playwright checks cover desktop/mobile layout,
  copy controls and client selection. The site-wide type check still reports the
  same 32 existing explorer errors; none come from the new page or copy component.
- PyPI and the MCP Registry are not published; they require account-side publisher setup.
  See [publishing](PUBLISHING.md). A prepared publishing workflow is not proof of
  an uploaded package or registry listing.

## Core runtime verification before 0.3.0

- **55 MCP tests passed locally**, including the actual native producer's phase 2
  output consumed through FastMCP stdio. All six tools, 16 table definitions,
  59 relationships and 10 SQL recipes are covered.
- [MCP CI passed on committed main](https://github.com/civictechdc/congressional-tech/actions/runs/41088300417):
  54 app tests pass; the one native integration test runs and passes in the
  separate producer-to-consumer job, alongside 62 producer/profile/retention tests.
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
