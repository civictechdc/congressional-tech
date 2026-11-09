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

