---
id: ct-b1jj
status: open
deps: []
links: []
created: 2026-11-13T15:25:44Z
type: bug
priority: 2
assignee: mikewolfd
tags: [publish, ci, disk]
---
# Hosted archive publish refuses before work: no disk budget on the runner

2026-11-13 run 43448096066 (archive-jobs.yml operation=publish, workflow_dispatch on main) stopped in under a second at disk admission: 'Disk budget unavailable for publish-fresh: <checkout>/.cache/archive-release/disk-budgets.json'. That file is the Mac's measured, untracked budget file, so a hosted checkout never has one; every hosted publish refuses the same way. Even with a file, the Mac budget (publish-fresh: 10 GiB peak plus the 15 GiB DISK_FLOOR in scripts/archive_disk.py, about 25 GiB free needed) exceeds the standard ubuntu-24.04 runner's free disk (about 14 GiB guaranteed). Memory is not the blocker (Mac peak about 10-11 GiB RSS, runner has 16 GiB). Context: the hosted publish is a manual fallback (owner decision 2026-11-04); it was wanted on 2026-11-13 because the OCR recovery held the Mac nightly lock.

## Acceptance Criteria

Either (a) a committed hosted budget for publish-fresh/publish-resume measured on a runner whose free disk covers peak plus a floor chosen for throwaway runners (freed toolcache or a larger runner), read by the hosted job; or (b) an owner decision that the hosted publish stays unsupported, with archive-jobs.yml publish removed or labelled so. A hosted dispatch then either publishes or refuses for a named reason other than a missing budget.

