# Refactoring implementation and verification

Implemented locally on 2026-09-30 against starting commit `8641571`. The scope is
Phases 0, 3, 1, 4, 2 and 6 of [the plan](REFACTORING_PLAN.md), with Phase 5's
previously approved replacement recorded below. Phases 7–8 remain explicitly
deferred. This records local code and test evidence, not a GitHub Actions run,
publication, or historical data refresh.

## Requirements and evidence

| Phase / requirement | Implementation | Verification |
| --- | --- | --- |
| 0: twelve scripts, flags, default artifacts, complete CI map | [Compatibility reference](../../docs/congress-api-contracts.md#commands-and-artifacts) documents all scripts, four update jobs and publication; distinguishes required paths from shared-package defaults | `test_congress_api_boundaries.py`; all twelve installed commands compared to baseline `--help`, byte-identical |
| 0: parser/schema/capture registry and upgrade checklist | [Version registry](../../docs/congress-api-contracts.md#parser-schema-and-capture-versions), including inline caption/HTTP versions | AST registry gate enumerates every owner; source-model tests remain in full suite |
| 0: layered identity and digest compatibility | [Identity policy](../../docs/congress-api-contracts.md#adapter-identity-policy) and [ADR](../../docs/adr/adapter-digest-versioning.md) | Digest/key characterization, GPO exact-file reuse, House published-ID reuse and Explorer tests |
| 3: committee entrypoint and placeholder | `committee_metadata.parse_args_and_run` wraps retained `main`; script name/arguments preserved; package-root demo removed | `test_committee_metadata.py`, wrapper test, installed `congress-committees --help`; wheel entrypoint check |
| 1: HTTP policy and import hygiene | [One README matrix](README.md#http-policy), linked module docstring; transcripts import the gateway directly; [fork decision](../../docs/adr/congress-api-http-fork.md) | `test_http_policy.py` checks legacy JSON/XML, five-vs-three retries, safe errors, caption pooling/retries, direct transcriber HTTP and urllib bytes; response-metadata/Zyte/caption suites |
| 4: acquisition ownership and parameter injection | `inventory.acquisition` owns witness capture, `probe_day` and `probe_days`, each with defaulted `get=`; main orchestrates; completeness calls acquisition; old witness/caption acquisition entries delegate | `test_inventory_acquisition.py`, existing witness/source/caption tests; boundary gate excludes direct HTTP from other inventory modules |
| 4: offline behavior, fidelity and deterministic persistence | [Offline matrix](../../docs/congress-api-contracts.md#offline-behavior), library docstrings and meeting-state docs; parser entry points unchanged | Offline end-to-end join uses real parsed PDF/MODS; repeated CSV/state bytes match; missing witness source preserves prior outputs; partial probe failures remain retryable |
| 2: independent replays, protection and receipt shapes | [Protection matrix](../../docs/congress-api-contracts.md#replay-protection-matrix) linked from each existing replay module; no shared engine/helper or receipt schema added | All three fidelity suites; baseline/current sample replay comparisons produce identical receipts and gzip state; GPO CSV/evidence bytes also identical; all three module CLIs pass help |
| 5: filename ownership and optional Parquet dependency | Superseded by the user's approved complete move to [house-naming](../house-naming/README.md). No `congress_api.filenames` file/package collision or facade remains; `house-naming[corpus]` owns PyArrow | Full `tests/test_filename_*.py` consumer tests pass. This refactor adds no duplicate parser, shim, or dependency to congress-api |
| 6a: production retention outside legacy | `retention.rejected_pages`; both production collectors import it directly; old import remains available | Append/raw-value/atomic-replace tests; same function under old import; production boundary gate |
| 6b: isolate TinyDB exploration and preserve callers | `legacy/fetch`, `legacy/analyze`, shared `legacy/committee*.py`, legacy converter; compatibility module aliases preserve shared caches; both console names unchanged | Old/new module identity checks; fresh-process old/new module help; installed scripts and wheel include new owners and aliases; original source-model tests |
| 6: operator docs and CI exclusion | Root/package/devcontainer docs lead with production mirror; setup includes local model dependencies; [legacy decision](../../docs/adr/tinydb-explore-sunset.md) keeps optional commands without removal date | Workflow exclusion gate, shell syntax validation; no workflow acquisition or publication behavior changed |

## Executed checks

```bash
.venv/bin/python -m pytest tests packages/committee_meeting/tests -q
# 969 passed, 31 subtests passed

.venv/bin/python -m compileall -q packages/congress_api/src/congress_api
bash -n .devcontainer/post-create.sh
uv pip install --offline --no-deps --no-build-isolation \
  --python .venv/bin/python -e packages/congress_api
```

The baseline was 942 tests plus 31 subtests. The refactor adds 27 tests and
updates acquisition tests to pass their HTTP collaborator directly. Retained
PDF/MODS/source fixtures and existing adapter/Explorer tests remain independent
of the moved functions.

All twelve installed console commands return the same help text as the baseline.
`python -m congress_api.{house,senate,gpo}.replay --help` and the old/new fetch and
analyze module commands work. A locally built wheel includes acquisition,
retention, quarantined implementations, compatibility aliases and updated script
entrypoints. The container setup script was syntax-checked, not run as a container
build; no container configuration changed.

Replay comparison uses one retained real fixture per driver with a fixed replay
time. House and Senate state/receipts are equal before/after; GPO receipts, CSV
bytes and evidence gzip bytes are equal. The broader source-fidelity suites
exercise protected live observations, changed-source rejection and identity
reuse. These samples are not a new full historical corpus qualification.

An AST comparison against `8641571` confirms no changes to the witness parser
functions, HTTP/API function bodies, state serialization, adapter common
functions or replay functions. Rejected-page implementation bytes are unchanged
at their new owner path. Raw input capture, storage formats and parser versions
are preserved.

Local execution receipts live in `.cache/congress-api-refactor/`: baseline/final
pytest logs, before/after CLI help, replay comparison script/results and wheel
build output. They are local evidence, not required runtime data.

## Deliberate limits

* No collector/parser tree shuffle, HTTP protocol/container, unified CLI,
  generic scraper, shared replay engine or extra package was introduced.
* Witness MODS/PDF acquisition stays with inventory, as the plan's default.
  Optional witness-grammar and match-scoring extractions were unnecessary.
* The filename move predates this refactor and is governed by the later explicit
  migration decision. Independent concurrent house-naming changes are outside
  this implementation's diff.
* The known dictionary-shaped event bug in legacy analysis remains separate
  bugfix work, as the plan requires. No legacy behavior repair is claimed.
* Nothing here refetches source data, pushes commits or deploys the site.
