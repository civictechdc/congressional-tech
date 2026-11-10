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


## Notes

**2026-11-10T17:12:34Z**

2026-11-10 correction and more evidence: the hung watchdog (PID 40836) has TWO defunct children, never reaped (the first note said none; pgrep does not list them): 40844, the owned-group leader, and 40849, a helper started in the same second (refactor/watchdog-hang/wh_children_40836.txt). With the native stack (module code, a bound-method call, a lock acquire) that places the block at subprocess.run's 'with Popen' exit calling wait() for a helper ps (scripts/measure/process_rss.py:18 or :34, both with timeout=5), blocked on that Popen's own wait lock (subprocess.py:2050 in CPython 3.12.13). What left the lock held is NOT proven. The only leak found so far by two readers is the check right after acquire(False) at subprocess.py:2032 (and :1983), a window of a few bytecodes, which an independent reviewer judged too small to explain one hang in a few hundred signals. Leads for the fix's builder: the watchdog under test sits in pytest's process group and was orphaned, so the signal that hung it may have been a group signal at an arbitrary moment, or a second signal during cleanup. Also: the existing test (scripts/tests/test_archive_watchdog.py:172-175) does not kill its watchdog when it fails, which is how this one survived. The coordinator checked that this process has no entry in the shared registry, so it delays nobody. Fix approved on its own branch claude/dx-watchdog-signal, test first, with a reviewer who reads the signal handling specifically; brief: refactor/briefs/watchdog-signal.md.
