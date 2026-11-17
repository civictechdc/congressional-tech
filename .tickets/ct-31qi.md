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

