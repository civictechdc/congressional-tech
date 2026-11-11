---
id: ct-psb5
status: closed
deps: []
links: [ct-01kq, ct-752r]
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

**2026-11-10T19:00:28Z**

2026-11-10: fix built on claude/dx-watchdog-signal (c30094a5 failing tests, 20a71bef the fix, 1ce8d360 an exact test of the bound) and independently reviewed by a reader of the signal handling in both interpreters: no must-fix, ship from all three views. Cause as proven: the hung process's native stack matches a reproduction in which the old handler raises while subprocess holds a child's wait lock, taken with acquire(False) outside a try (CPython 3.12 subprocess.py:1983 and :2032; 3.15 :2180 and :2336); it does not prove which site, how many signals, or the rate, which stays unexplained. The hung process was killed at 18:27:45Z. A second round is being made from the review: the stop reason names the signal also when a group signal kills the in-flight ps or vm_stat (today the report would say IndexError); the three signals tested, not only TERM; the wait between passes wakes promptly on a recorded signal (time.sleep resumes after a handler that returns, so the stop began up to an interval later than before and a report could be lost more often where the watchdog itself is killed 2 s after the TERM); timeouts on the two untimed helper calls; a bounded test teardown. Still open by design: a signal after watch() returns and before the report is written can lose the report; admission is unchanged. Follow-up for the backfill loop and one shared recorder: ct-752r.

**2026-11-11T14:28:17Z**

validated 2026-11-11, closing: W11 is on main (13c9833e in 0abb3ab5). Code read on origin/main: archive_watchdog.py installs a recording handler for TERM, INT and HUP (line 254) and the loop reports 'Interrupted: watchdog received signal N' (line 252); commits 4c78f49d (handler records and returns), b4228ff9 (wait taken in 0.05 s slices), 779174ca (a pass that fails after a signal still reports it), a308fca7 (ps and vm_stat get 5 s). Lanes green with the driver's own start path on a loaded machine: TERM stopped everything in 0.39 s with exit 99 (decisions-overnight 22:41Z); review in refactor/review-watchdog-signal. Left by design and named elsewhere: a signal after watch() returns can still lose the report, and the backfill loop's own signal recorder, both on ct-752r.
