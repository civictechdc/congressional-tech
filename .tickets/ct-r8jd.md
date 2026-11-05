---
id: ct-r8jd
status: closed
deps: [ct-3szv]
links: [ct-deg8, ct-wsu7, ct-6v77]
created: 2026-11-02T00:40:43Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [memory, jobs, phase2]
---
# Add a runaway memory limit to native archive jobs

Owner decision 2026-11-01: measure model memory, with a high limit for runaways rather than a tight target. Engine pool settings do not bound process RSS (ct-deg8): one expression reached 20.4 GiB at a 1 GiB pool, and an out-of-memory crash on 2026-11-01 took down a 48 GB machine. The local guard is .cache/rounds/guard.py, which is not checked in.

## Acceptance Criteria

Every native archive job runs under one checked-in RSS watchdog with a configured high limit; a runaway stops the job with a named failure instead of harming the machine; peak RSS is recorded per run. The hosted runner limit is set from a measured full run.


## Notes

**2026-11-02T04:01:45Z**

Code on worktree-agent-a5550c04138214670 @ b3c4aa3c (808b2bfc). Review: merge, stay open. Before wiring: job outlives SIGTERM and a missing --report parent; reuse monitor_command cleanup. Wiring and the hosted limit need a measured full run.

**2026-11-02T14:46:34Z**

2026-11-02 (lead): red-e2: the watchdog gives no TERM grace period (process_rss.py:103-113 kills the leader on the first TERM, so KILL follows immediately). Fix: the leader ignores TERM.

**2026-11-02T18:44:42Z**

2026-11-02 causes dry run: the model's measured 14-17.5 GiB peak (before fix 1 and the engine spill fix) doesn't fit the ubuntu-24.04 hosted runner (16 GB RAM), and the model materializes about 38 GB with spills up to 53.4 GB (profile_completeness capture_dup, being fixed upstream by engine-spill) against runner disk. A daily publish spec can't pass gate 5 until ct-ud0b's daily producer records exist. This release runs on the Mac (owner decision), so it isn't blocked; nightly hosted publishing is. Owner decision on runner capacity (larger hosted runner vs self-hosted vs further cuts) once fix 1 and the spill fix are measured.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.

**2026-11-04T02:21:36Z**

Reopened 2026-11-03 (post-release acceptance test): .github/archive-jobs.json has no rss_gb, so hosted jobs refuse at --check-binding. Owner decision 2026-11-03: publish 14, backfill 12 from this release's measured peaks (model 9.385, backfill 8.358, publish 4.114 GiB RSS; watchdog reports under .cache/archive-release/r1b-run/candidate-8addb2dc/after-video/final-run-pinned/); maintenance stays unset (refusing) until a real maintenance run is measured.

**2026-11-04T02:22:01Z**

2026-11-03: rss_gb set in .github/archive-jobs.json: publish 14, backfill 12 (both admit at --check-binding); maintenance has none and refuses by design. .github/tests/test_archive_workflows.py 18 passed. Stays open until a maintenance run is measured and bound.

**2026-11-04T02:46:36Z**

2026-11-03: owner chose plan-then-real-run, but maintenance cannot run as specified (ct-3szv): its raw-verification inputs are never produced, --plan lists no deletions, and the dry run applies staged results. No local R2 credentials in this environment either. Blocked on ct-3szv.

**2026-11-04T12:46:09Z**

Owner decision 2026-11-04: hosted runner capacity is moot: the nightly runs on the Mac. Bind the Mac's memory and spill limits from the model measurement (investigation running 2026-11-04).

**2026-11-04T16:12:39Z**

2026-11-04: publish (14 GiB) and backfill (12 GiB) run under the checked-in watchdog via .github/scripts/run-archive-job.py, peak recorded per run. Eight full model builds at 0140912e peak 11.30-12.23 GiB (worst margin 1.77 GiB; .cache/archive-release/investigations/model-memory-20261104.md). Still open: maintenance has no rss_gb in .github/archive-jobs.json, and the document_witness_keys fix (branch witness-agg) should lower the peak to about 10.2 GiB.

**2026-11-04T16:39:47Z**

2026-11-04: document_witness_keys fix 2d76d689 lowers full-build peak to 8.59-9.39 GiB (margin >= 4.6 GiB under the 14 GiB publish limit).

**2026-11-05T12:02:36Z**

2026-11-05 Codex continuation: maintenance completed as a full read-only audit plus maintained staged-apply and retention execution, without repeating307,033 completed body reads. Native audit peak5.989 GiB; apply/retention peak0.169 GiB. Configured maintenance rss_gb10 in .github/archive-jobs.json (7240b36d); --check-binding passed.10 GiB is a deliberate runaway allowance, not a measured hosted peak. All three operations now have limits. Final integration qualification pending. See ct-3szv and durable full-readonly/completed-maintenance watchdog reports.

**2026-11-05T13:09:52Z**

Qualified source 7f9ebddd2cb632f97bc0214ffd44beaf72b0a5a6: all three production-offline shards passed (11,497 passed; 37 unchanged legacy skips; 3 existing expected failures), native-loopback full lane passed (10 tests, zero skips), and storage-loopback full lane passed (1 test). Evidence: .cache/archive-release/handoffs/cursor-resume-20261105/qualification-7f9ebddd2cb6/combined-results.json. Maintenance now has a 10 GiB runaway limit based on its 5.989 GiB measured native audit peak; publish remains 14 GiB and backfill 12 GiB. All three bindings pass. The November 4 owner decision uses the Mac nightly, so no hosted capacity result is claimed. Closing after the completed real maintenance measurement and binding.
