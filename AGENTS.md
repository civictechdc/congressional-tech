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

Run heavy local work (engine runs, full lanes, cargo builds, multi-GB scans)
under `python3 scripts/archive_watchdog.py --rss-gb <kill limit> --expect-gb
<measured peak> --start-available-gb 6 --interval 0.2 -- <command>`. It starts
the job once measured free memory covers the expected peak beside other jobs
still ramping, stops it at the kill limit, stops only the youngest job below
4 GiB machine memory, and takes the job down if the watchdog itself is killed.
Its stderr and `--report` give the peak to pass as `--expect-gb` next time.

Data another agent or a later run reads (frozen inputs, run outputs,
measurements) lives under `<main checkout>/.cache/archive-release/`, never only
in a worktree or `/private/tmp`, which a prune or a reboot deletes. Remove a
worktree with `.venv/bin/python scripts/dev.py prune-worktree <path>
[--execute]`, not `git worktree remove`: it refuses while the tree holds
uncommitted work, ignored data other than rebuildable environments, or a
process working in it.

For `apps/site` browser checks (`npm --prefix apps/site run contract:archive`),
`npm --prefix apps/site ci` installs the exact `playwright` that
`apps/site/package.json` pins; install its browser with
`node apps/site/node_modules/playwright/cli.js install --only-shell chromium`.

# Raw checks

A raw check (`raw_*.py` or `*_raw_check.py` anywhere under `scripts/measure/`) judges a rule's
output from the raw record with its own reading. It must not import the
producer, parser or model package, nor read model SQL or a registry
(`scripts/measure/tests/test_raw_check_independence.py` enforces that much). It
must also not restate the rule in its own words, which no test can see: judge
from raw facts the rule does not use, or by a different measure; compare both
directions; name every record not read; and before trusting a pass, plant one
wrong value the rule would produce and show the check flags it. A reviewer
other than the rule's author confirms the planted case.

# Byte-hashed parser pins

Several producers compute `parser_version` by hashing their own source bytes:

- `captures.py` (`packages/congress_api/tests/test_captures_version.py` pins `APPROVED_MAPPING`)
- `packages/congress_api/src/congress_api/lake/filenames/__init__.py` (`parser_version` hashes the `house_naming` package)
- `meeting_records.py` and `appearance_records.py` (`house_xml`, `congress_gov`, `senate_page`, `mods`)

Never reformat or touch byte-hashed parser files unless intentionally changing
extraction semantics. When a parser change is intentional, update
`model/jobs/publish-model.json` (`parser_versions`), recompute the `model_spec`
`sha256` and `size` in `model/jobs/publish.json`, and update any pinned test hash.

Readings use declared versions in `congress_api.lake.reading_versions`.
`doctor` and CI warn when source, dependency, tool, or policy evidence changes.
Review the drift using a bounded sample and record the maintainer's equivalence
decision or deliberate version bump. Keep qualified compatibility entries
until a retained-table comparison preserves selected rows, active refusals,
and pending work. See [reading version changes](docs/development.md#reading-version-changes).

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
- **Reference-key parity:** `normalize_house_committee_code` in
  `meeting_records.py` is the single owner of House select/task-force committee
  code normalization (`hs*` → `hl*`/`ht*`); r1b-f removed the SQL copy of the
  select-committee rule (ct-p3ff). Don't re-add one.
  The gate is `missing_committee_keys = 0` against `committees.parquet`.
- **A CTE runs once per reference:** the pinned DataFusion re-plans every CTE
  and view reference and ignores `AS MATERIALIZED`, so a CTE read inside other
  CTEs runs once per path (`single_meeting_components` ran 8 times in
  `document_witness_keys`). Compute anything read more than once, directly or
  through nesting, in its own model step; only steps materialize.
- **No grouped `count(DISTINCT <string>)` over many groups:** each group holds
  its own distinct set, about 14 KB allocated, so 127,659 groups cost about
  6 GiB. Group by `(group, key)` first, then `count(key)` (not `count(*)`,
  which counts a NULL key) and `bool_or`/`min` over the per-key rows.
- **Joins build on the left:** with no statistics the engine builds the hash
  table from the left input, and `IN`/`EXISTS`/`NOT EXISTS` build on the outer
  query. Put the small side first (`RIGHT SEMI`/`RIGHT ANTI` where needed).
  Measurements and the ranked follow-ups: ct-6v77 and
  `.cache/archive-release/investigations/model-step-theory-20261104.md`.
