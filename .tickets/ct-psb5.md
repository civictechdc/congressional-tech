---
id: ct-psb5
status: open
deps: []
links: [ct-01kq]
created: 2026-11-10T17:00:45Z
type: bug
priority: 1
assignee: mikewolfd
tags: [watchdog, nightly, reliability]
---
# A watchdog sent TERM can hang forever with its job gone

Found 2026-11-10 during the docspec-rs feedback refactor (not in any brief). An archive_watchdog.py process started at 15:54:21Z by the existing test scripts/tests/test_archive_watchdog.py::test_sigterm_to_the_watchdog_stops_the_job (run from the worktree wt/dx-step-memory) was still alive more than an hour later: orphaned (parent 1), no children, one thread, blocked in a lock acquire called from a method; its job was gone and it never wrote its report. Evidence: .cache/archive-release/investigations/docspec-feedback-20261110/refactor/watchdog-hang/ (wh_sample_40836.txt native stack, wh_ps_40836.txt, wh_lsof_40836.txt). The test and the code path it runs are the same on origin/main; the worktree's only change to the watchdog adds fields to a timeline line. Cause NOT proven. Leading hypothesis: the handler _interrupted (scripts/archive_watchdog.py:63) raises Interrupted at whatever bytecode the main thread has reached; CPython's subprocess.Popen takes its wait lock with acquire(False) outside a try (in poll and in wait with a timeout), so an exception raised just after the acquire leaves the lock held, and a later blocking wait on the same Popen never returns. Not explained yet: which blocking acquire it is stuck in, since stop_owned only calls wait(timeout=5). Why it matters: watch() never returns, so main never reaches registry.drop and the process keeps any --hold-fd descriptor: a hung watchdog stays registered as a running job and keeps the lock it was handed, so later heavy jobs can be refused or made to wait. The trigger is a TERM, INT or HUP to the watchdog, which is how jobs are stopped. How often: seen once in an afternoon of repeated test runs; rate unknown.

## Acceptance Criteria

The hang is reproduced on purpose (a test that delivers the signal at the vulnerable point, or a stress test with a measured rate) and the test fails before the fix. The handler no longer raises into arbitrary code: it records the signal and the loop acts on it at a safe point within one interval. After a TERM, INT or HUP at any moment the watchdog stops its job, writes its report with the signal named, leaves the registry and exits with its usual code within a stated bound. The existing watchdog tests pass; one full lane or all six shards. Because the nightly runs under this guard, the change goes in by itself with the coordinator's agreement.

