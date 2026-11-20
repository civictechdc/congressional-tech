---
id: ct-3kdg
status: closed
deps: []
links: []
created: 2026-11-18T20:27:36Z
type: task
priority: 3
assignee: mikewolfd
tags: [tooling]
---
# Archive watchdog: confirm killed processes are really gone

Commit d0ff5fb0 on archive/2026-11-18/codex/ddk-congress-replacement-20261106 added a post-kill check (process_rss group_members) and a failure report when cleanup cannot be confirmed; scripts/archive_watchdog.py on main has diverged since (2c401ef3) without it. Port the check onto the current watchdog. Review: .cache/archive-release/reviews/branch-value-20261118/b-ct-ddk/REPORT.md.

## Acceptance Criteria

After the watchdog kills a job, it verifies no member of the process group survives and reports when it cannot.


## Notes

**2026-11-20T17:29:15Z**

2026-11-20: Ported post-kill process-group survival verification (d0ff5fb0) onto scripts/archive_watchdog.py and scripts/measure/process_rss.py so lingering child processes in the owned process group are detected and reported (commit 0e554d3f). Verified in scripts/tests/test_archive_watchdog.py, scripts/tests/test_process_rss.py, and CI run 44776340037.
