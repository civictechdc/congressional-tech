---
id: ct-vnkf
status: closed
deps: []
links: []
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, ci, jobs, maintenance, track3]
---
# T3.2: Bind active CI job specs (.github/archive-jobs.json & model/jobs/*.pending.json)

Implement the CLI entry points for backfill and maintenance (wiring packages/congress_api/src/congress_api/retention/raw_verifier.py, packages/viewer_publication/src/viewer_publication/archive_maintenance.py, and packages/congress_api/src/congress_api/lake/maintenance.py), replace model/jobs/publish.pending.json, model/jobs/backfill.pending.json, and model/jobs/maintenance.pending.json with active job specs, and update .github/archive-jobs.json.

## Acceptance Criteria

model/jobs/publish.json, backfill.json, and maintenance.json replace the *.pending.json files, .github/archive-jobs.json points to active specs, and CLI entry points pass tests.

