---
id: ct-v4ua
status: in_progress
deps: []
links: []
created: 2026-11-11T12:02:23Z
type: bug
priority: 2
assignee: mikewolfd
tags: [model, harness, inputs]
---
# A model-only build found its unfetched input files only after the watchdog admitted it

2026-11-11: congress-1's model-only build waited 24 minutes in the watchdog's admission and then stopped at its first missing file. Its spec bound spicy-regs tables that were never fetched, and archive_model_job checked a pinned file only when execution held it (model_arguments), which is after admission.

Fix on branch claude/dx-plan-verifies-inputs (from origin/main ac087407):
- archive_model_job.check_inputs reads each pinned local input once with file_identity and compares it with its pin by check_identity, the pair model_arguments already uses. It names every missing or changed file with its spec field (a spicy-regs table by name, after the spicy-regs input itself).
- --plan runs it and reports the files and bytes checked.
- --execute runs preflight (fresh output and scratch, then the inputs) before it derives a ledger, builds a runtime or holds anything, and hands the result to model_arguments as verified_files, so each file is still read once. execute() runs preflight itself for other callers (archive_selective, tests).
- docs/development.md now plans (fetch, bind, check) before the watched execute.

Measured on the real candidate (release-20261110b/candidate-rebuilt) from a checkout without fetched spicy-regs tables: plan exits 2 in 5.5 s (149 MiB), naming all 14 tables, after checking the other 55 pinned files (409 MB). Before the change, the same plan exited 0. Two plants are caught: the check skipped (3 tests fail) and a second hash pass at execute (1 test fails).

## Acceptance Criteria

--plan and the start of --execute refuse a spec with any missing or changed pinned input in seconds, naming each one; execution reads each file once. Tests seen failing first, plus the two plants. The lane set on the branch is green (the manager schedules it), then merged.

