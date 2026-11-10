---
id: ct-fskn
status: open
deps: []
links: [ct-9lxf]
created: 2026-11-09T23:58:27Z
type: bug
priority: 2
assignee: mikewolfd
tags: [hosted, archive, ci]
---
# Hosted weekly archive maintenance is red every Sunday: the runner has no disk budget for 'maintenance'

archive-jobs.yml runs the maintenance job on schedule (cron 17 7 * * 0). Scheduled run 42489124804 (2026-11-08T14:18Z, main 6531d60c) stopped in 'Run raw checks, retained receipt evidence and catalog maintenance' with: Disk budget unavailable for maintenance: .cache/archive-release/disk-budgets.json. scripts/archive_disk.py job_admission reads ARCHIVE_DISK_BUDGETS or <root>/.cache/archive-release/disk-budgets.json; that file is kept outside Git on the Mac (docs/archive-disk-lifetimes.md) and the hosted runner has none, and no budget record names the 'maintenance' operation. So the job refuses before any work on every schedule. The four earlier workflow_dispatch runs on 2026-11-04 also failed (causes not read). ct-9lxf (closed) covers the local Mac budget file only.

## Acceptance Criteria

Either the schedule is removed until a maintenance binding is active, or the hosted job is given a measured maintenance budget (a checked-in hosted budget file or ARCHIVE_DISK_BUDGETS) and one scheduled or dispatched maintenance run finishes green. The choice and its reason are recorded here.


## Notes

**2026-11-10T00:32:21Z**

2026-11-10: schedule trigger removed from archive-jobs.yml (workflow_dispatch stays) so the job stops failing every Sunday. Still to do before turning it back on, from the read-only architect review (.cache/archive-release/investigations/nightly-20261109T224443-base-normalized-memory/architect-review-20261110.md): a committed hosted budget that names 'maintenance'; fetch-depth: 0 for the ancestry check; current table names in model/jobs/maintenance.json (it lists two superseded tables and omits three, unverified here). Cost of no maintenance: readings sits at 1,907 files and 1,294 snapshots against a 256-file threshold (reviewer's count, unverified here). All five runs of this workflow have failed; maintenance itself was refused locally too.
