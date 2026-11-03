---
id: ct-r8jd
status: open
deps: []
links: [ct-deg8, ct-wsu7]
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
