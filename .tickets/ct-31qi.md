---
id: ct-31qi
status: in_progress
deps: []
links: []
created: 2026-11-17T18:18:49Z
type: task
priority: 1
assignee: mikewolfd
tags: [hosted, publish, ci]
---
# Keep the built candidate between hosted runs and resume at the gates

Root cause 2 of .cache/archive-release/investigations/etl-rca-20261117/RCA.md. Hosted runners keep nothing, so a gate stop answered by a cause record repeats a 22-minute, 10 GiB model build of an identical candidate. On 2026-11-17 ten builds produced five distinct candidates. The controller already has a resume path (completed-model checkpoint); nothing carries the candidate between runs.

## Acceptance Criteria

A hosted publish that stops after its build, re-run with the same inputs, reaches the gates without rebuilding the model, and a run whose inputs changed rebuilds. Proven by tests and by one real stopped-then-resumed run.

## Notes

**2026-11-17**

Merged as pull request 192 (ad2e2efe): the publish job restores the newest kept candidate from the Actions cache (about 178 MiB), resumes it when its files are intact and its inputs and selected release are this run's, and otherwise deletes it and builds fresh. Tests cover resume, changed inputs, changed definitions, damaged files and a candidate that is already live.

Kept open for the second half of the acceptance: one real stopped-then-resumed run. On the next night the gates stop, after the cause record is merged and main has validated it, the re-run's log should say "Resuming the kept candidate" and its publisher step should take minutes, not about 25. If it says "Building fresh; kept candidate discarded: ...", the reason names what differed; record it here.

Every normal night now passes through this code too (yesterday's candidate is restored, found to be another night's, deleted, and a fresh build runs), so the first scheduled night after the merge is its first production check.
