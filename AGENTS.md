# Ticket search

Run `./scripts/tk-search sync` to refresh the local ticket index, then
`./scripts/tk-search search "describe the issue" --limit 5` for hybrid keyword
and semantic search. MiniLM runs locally on CPU. The index covers this checkout's
`.tickets/*.md`, including closed tickets; refresh it after ticket edits.

For repeated queries, `./scripts/tk-search search --stdin --limit 5` reads one
query per line and emits one JSON array per query while reusing the loaded model.
Use `--json` for a single machine-readable result, `--status open` to filter,
or `--mode fts` for keyword-only search without loading the encoder. Exact ticket
IDs bypass ranking.

Use `tk` for ticket edits, status and dependencies, and `rg` for literal lookup.
Inspect the cited passage before treating a ranked match as evidence; semantic
search can return unrelated candidates. Keep generated indexes and model weights
out of Git. See [ticket-search usage](scripts/ticket-search/README.md) for index
location, multi-repository roots and verification.

# Test execution & local runtime

Run `uv sync --frozen` in every checkout or worktree, then run Python suites
through its own `.venv/bin/python scripts/dev.py test <lane>`. Every pytest
session (and `doctor`) refuses another checkout's interpreter or packages, even
through `PYTHONPATH`. A `--path`, `-k` or shard run ends with a `partial` or
`shard` line; call a branch tested only from a `(full lane): exit 0` line or
all shards.

Native lake/model tests require `DOCSPEC_JOB_CONFIG` naming a **local-only**
runtime for the engine this checkout pins in `model/docspec-runtime-pin.json`;
`doctor` and pytest refuse any other engine. Write one with
`.venv/bin/python scripts/dev.py write-local-runtime --limits
.github/docspec-local-limits.json --out .cache/local-runtime/runtime.json`. It
names the pinned binary in the shared store
`<main checkout>/.cache/docspec-runtime/<platform>/<sha256>/docspec`; add a new
engine there once with `--binary <docspec>`, which refuses bytes the pin does
not name. Store entries are read-only and never replaced, so never copy a new
build over a configured path. The helper never writes `remote` or `credentials`
(a pipeline `runtime.json` with those keys fails `doctor` and
`validate_catalog_authority`).

For `apps/site` browser checks (`npm --prefix apps/site run contract:archive`),
`npm --prefix apps/site ci` installs the exact `playwright` that
`apps/site/package.json` pins; install its browser with
`node apps/site/node_modules/playwright/cli.js install --only-shell chromium`.

# Byte-hashed parser pins

Several producers compute `parser_version` by hashing their own source bytes:

- `captures.py` (`packages/congress_api/tests/test_captures_version.py` pins `APPROVED_MAPPING`)
- `readings.py` (`document_links.py`, `pdf_tools.py`, `qualification.py`, `html.py`)
- `filename_readings.py` (`document_cover.py`)
- `meeting_records.py` and `appearance_records.py` (`house_xml`, `congress_gov`, `senate_page`, `mods`)

Never reformat or touch byte-hashed parser files unless intentionally changing
extraction semantics. When a parser change is intentional, update
`model/jobs/publish-model.json` (`parser_versions`), recompute the `model_spec`
`sha256` and `size` in `model/jobs/publish.json`, and update any pinned test hash.

# Archive ETL & DataFusion SQL

- **Candidate SHA semi-join pushdown:** Never `GROUP BY` or `DISTINCT` over
  `captures` or `readings` in `model/sql/*.sql` or `archive_model.py` before
  joining to a smaller candidate set. Expression keys (`encode(c.sha256, 'hex')`)
  and outer joins block DataFusion predicate pushdown and exhaust the per-stream
  `GroupedHashAggregateStream` memory cap (`109.6 MB`) on the `4.15M`-row
  `captures` table. Always join a `candidate_*_shas` CTE inside the
  pre-aggregation scan.
- **Single pinned version per `(body_sha, parser)`:** Historical `readings`
  tables can retain older `parser_version` rows alongside current rows. Filter
  to the single pinned `parser_version` per `parser` before re-stamping or
  joining so duplicate `(body_sha, parser, parser_version)` keys do not fail at
  final export ordering.
- **Predicate-scoped selective backfill:** When a parser change only affects
  records matching an exact input predicate (e.g., receipts with `prior_attempts`
  or non-stored envelopes, or URLs matching a date-overlap regex), reuse
  unaffected partitions/rows, recompute only matching candidates, and validate
  the combined output with `capture_backfill_guard.validate_generation` and all
  6 model invariant suites (`invariants`, `model_invariants`,
  `url_state_invariants`, `profile_completeness`, `entity_profile_completeness`,
  `relationship_invariants`).
- **Capture guard scope:** `capture_backfill_guard.py` checks final public rows
  and supplied per-receipt counts. It does not parse receipts, so envelope and
  nested `error` handling live only in `captures.py`, and the guard cannot see a
  wrong value that is still in-domain.
- **Reference-key parity:** Keep House select/task-force committee code
  normalization (`hs*` → `hl*`/`ht*`) in `meeting_records.py` and
  `model/sql/meeting-records-resolved.sql` aligned with `committees.parquet`
  (`missing_committee_keys = 0`).
