# Raw source document table publication

`capture-raw-sources.yml` runs the current Python parser against retained evidence
and publishes the document tables to R2. R2 stores the evidence and tables;
GitHub Actions performs the rebuild. Parser changes do not need another upstream
download batch before metadata can be published.

| Trigger | Operation |
| --- | --- |
| Relevant code pushed to `main` | Rebuild only |
| Manual dispatch, `mode=rebuild` (default) | Rebuild only |
| Manual dispatch, `mode=capture` | Capture missing sources, then rebuild |
| Every six hours | Capture missing sources, then rebuild |
| `Update committee data` completes on `main` | Capture missing sources, then rebuild |

The completion trigger also runs after an unsuccessful collection, preserving the
existing opportunity to process retained partial progress. It accepts only runs
from this repository. Push filters cover filename rules, source parsers, source
models, rebuild code, and this workflow. Generated tables, site changes,
`pipeline-data`, and documentation do not trigger a metadata rebuild.

## Run a rebuild

In GitHub Actions, select **Capture raw sources and rebuild document tables**,
choose **Run workflow**, select `main`, and leave `mode` set to `rebuild`.
The equivalent CLI command is:

```sh
gh workflow run capture-raw-sources.yml --ref main -f mode=rebuild
```

`limit` and `transport` apply only to capture mode. Rebuild mode calls
`raw-source-sync --rebuild-only` with the existing bucket, available seed files,
index worker count, and summary path. It skips Rust setup and native fetcher
tests, passes no Zyte token, and has no acquisition arguments. Unknown operations
fail before the command runs. The Python mode is responsible for leaving
`indexes/captures.parquet` and `indexes/download-state.parquet` untouched.
Capture mode calls the same command once and uses its shared rebuild after
acquisition; the workflow does not add a second rebuild.

The job allows four hours overall. Capture remains limited to 90 minutes, leaving
time for a full metadata rebuild and publication after collection.

## Revision, publication, and failure checks

The workflow checks out `github.sha` and validates that code before publishing.
For push and manual events, this is the triggering code revision, including on
reruns; scheduled and completion events use their default-branch event revision.
See GitHub's [event revision definitions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).
The separate `pipeline-data` checkout supplies the latest saved seeds.

All operations keep the existing `raw-source-mirror` concurrency group with
`cancel-in-progress: false`. Any future R2 writer must use that same group. The
workflow has read-only repository permissions and writes no Git commits, which
prevents its output from triggering another rebuild.

The Actions summary records the operation, trigger, code revision, seed revision
when available, job status, publication-step outcome, and the command's JSON
summary. The JSON is also retained as a workflow artifact. A missing summary
after a successful command fails the step. Setup or publication failures still
produce a status summary and explicitly leave publication unverified when no
command summary exists.

## Local validation

Install the workflow's Python dependencies, including `PyYAML>=6,<7`, then run:

```sh
python .github/scripts/offline-python.py -m pytest -q .github/tests/test_raw_source_workflow.py
```

These tests execute the actual workflow shell steps with a recording command in
a temporary directory. They check event selection, acquisition arguments,
invalid modes, command failures, missing summaries, success/failure reporting,
path filters, the shared writer lock, and the triggering revision. They also
parse the recorded arguments with the real Python CLI, so a missing
`--rebuild-only` implementation fails validation before publication. The tests
run in both the publication workflow and pull-request validation.

The publication workflow also runs the offline catalog, recovery, preservation,
source parser, filename rule, and capture tests. Local tests do not establish
hosted credentials, R2 publication, or a successful GitHub Actions run; those
require an authorized hosted run and examination of its summary and outputs.
