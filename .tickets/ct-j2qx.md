---
id: ct-j2qx
status: closed
deps: []
links: []
created: 2026-11-11T19:07:43Z
type: bug
priority: 2
assignee: mikewolfd
---
# Watchdog FIFO admission lets one big queued job starve small ones

2026-11-11 18:31-19:07Z: OCR chunk-0089 (expect 12 GiB + headroom 6) queued first while about 14 GiB was free, so it could not start; congress-1's 1 GiB MODS read probe queued behind it and was refused for 36 min because admissible() subtracts the head waiter's expect_gb (scripts/archive_watchdog.py:106-114). Neither job ran until OCR was paused. Fix at the root: a waiter whose own need is met should not be blocked by a head waiter that cannot fit now (e.g. reserve the head only once it could fit, or let small jobs pass), keeping the no-overcommit guarantee; add a test with one big unfittable head and one small fittable job.


## Notes

**2026-11-11T19:42:30Z**

2026-11-11 19:42Z: the trigger was a stale --expect-gb: the OCR driver hard-coded 12 GiB while its chunks measure 6.6-7.3 GiB (runs/chunk-0084..0087.watchdog.json), so it could never be admitted at ~13.6 GiB free and, as head waiter, blocked every small job. Driver now passes 7.5 (FULL_DIR/EXPECT_GB overrides); admitted immediately. The policy question stands: a head waiter that cannot fit even with all measured free memory still blocks backfill (the docstring's 'smaller jobs may backfill beside' only holds when free > head + small + headroom). Options: reserve for the head only after it has waited N minutes, or let a fitting job pass when head + ramping exceeds free memory.

**2026-11-12T02:59:00Z**

Closed on `claude/ct-wave-1ab-safety`. Updated `admissible()` in `scripts/archive_watchdog.py`: an earlier queued waiter reserves its `expect_gb` only once measured free memory (or draining jobs admitted at/after it queued) covers its `expect_gb + headroom`, or once all pre-existing running jobs have finished and it has waited `RAMP_SECONDS` (120 s) for bypassing jobs to drain. An unfittable head with nothing to drain never blocks fitting smaller jobs, while large waiters cannot be starved indefinitely by a stream of small jobs. Deterministic unit tests added in `scripts/tests/test_archive_watchdog.py` (`test_the_oldest_waiter_is_reserved_when_fittable_and_does_not_starve_small_jobs_when_unfittable`, `test_bypassing_small_jobs_drain_so_a_large_waiter_is_eventually_admitted`).
