# Read-only pipeline status

Use a GitHub workflow run ID to combine its terminal state with the existing raw
source heartbeat. This command does not write status, retry work, resume a run,
acquire source documents or publish anything.

```bash
.venv/bin/python scripts/publication/pipeline_status.py --run RUN_ID
.venv/bin/python scripts/publication/pipeline_status.py --run RUN_ID --json
```

The live command uses `gh api` for the GitHub run and reads the existing public
`status/raw-source-sync.json` object. GitHub requests have a 20-second timeout;
heartbeat requests have a 10-second timeout and a 2 MiB JSON limit. The existing
GitHub CLI login supplies repository access. `--repo owner/name` overrides the
repository; `--progress URL_OR_PATH` selects another existing heartbeat.

The result shows the run state, attempt, code revision, heartbeat freshness,
current stage, stage counts, cumulative counters and elapsed time. Run, attempt
and revision must match before heartbeat data is attributed to the run. An expired
running heartbeat cannot override a terminal GitHub result. Counts describe one
stage; no total percentage or estimated finish time is invented.

For offline inspection, supply saved evidence:

```bash
.venv/bin/python scripts/publication/pipeline_status.py --run RUN_ID \
  --github-json saved-github-run.json --progress saved-progress.json \
  --previous-progress earlier-progress.json --json
```

`--github-json` expects the GitHub REST workflow-run object (`id`, `run_attempt`,
`head_sha`, `status`, `conclusion`). `--previous-progress` enables comparisons of
cumulative counters, elapsed time and the completed count within an unchanged
stage. Without that earlier snapshot, the result explicitly says monotonicity
was not checked. The command creates no snapshot store or background monitor.

Add `--continuation PATH/continuation.json` to inspect accepted phase receipts.
A receipt must bind the same run, attempt and revision. Older local recovery
receipts lack those identities; they are reported as unbound, with no attribution
to the requested GitHub run. Accepted output counts are **recorded acceptance**;
status inspection does not rehash potentially large prepared outputs.

A bound viewer publication journal is checked against its preparation digest and
its local event chain. Its completed event can report a recorded publisher
result. Current public readback remains **not checked**: a successful process,
accepted preparation or historical publication result does not prove that the
public selection still matches. The next action identifies the evidence to
inspect; it never authorizes or performs a resume.

`tests/test_pipeline_status.py` covers expired/wrong-run heartbeats, revision and
attempt mismatches, decreasing counters, stage transitions, failed children with
accepted preparation, successful children without public readback, unbound
receipts, damaged journals and offline inspection with no network or writes.
The initial focused macOS regression run passed all 16 cases.
