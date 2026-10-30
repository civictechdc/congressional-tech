---
id: ct-vnkf
status: open
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


## Notes

**2026-10-30T19:28:54Z**

Reopened per Greybeard parity audit: (1) model/jobs/maintenance.json omits raw_verification and lake_maintenance configuration sections; (2) .github/workflows/raw-source-tables.md:10,44 references viewer_publication.archive_maintenance_job instead of viewer_publication.archive_maintenance; (3) apps/site/FILENAME-VIEWER.md:25 states /dashboard/ redirects to /archive/ whereas /dashboard/ coexists for coverage/issues views.
