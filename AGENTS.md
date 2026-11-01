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

Run Python suites through `.venv/bin/python scripts/dev.py test <lane>` (or pass
`--path <file_or_node>` for targeted runs). The `production-offline` lane and
any direct `.venv/bin/pytest` run over native lake/model tests require
`DOCSPEC_JOB_CONFIG` pointing to a pinned **local-only** runtime JSON (`binary`,
`binary_sha256`, `source_revision`, `platform`, `build_features`, `limits`,
`workspace`) with **no** `remote` or `credentials` keys. Passing a pipeline
`runtime.json` that includes `remote` or `credentials` fails `doctor` and raises
`validate_catalog_authority` errors in local Iceberg tests.

For `apps/site` browser contract checks (`npm --prefix apps/site run contract:archive`),
set `VIEWER_BENCHMARK_MODULES` to a `node_modules` directory whose `playwright-core`
matches the installed `.cache/ms-playwright/chromium_headless_shell-*` revision.

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
- **Producer/guard & reference-key parity:** Keep `captures.py` and
  `capture_backfill_guard.py` aligned on receipt envelope and nested `error`
  object handling, and keep House select/task-force committee code normalization
  (`hs*` → `hl*`/`ht*`) in `meeting_records.py` and
  `model/sql/meeting-records-resolved.sql` aligned with `committees.parquet`
  (`missing_committee_keys = 0`).
