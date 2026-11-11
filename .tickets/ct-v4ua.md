---
id: ct-v4ua
status: closed
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
- archive_model_job.check_inputs reads each pinned local input once (hard-linked aliases once between them) with file_identity and compares it with its pin by check_identity, the pair model_arguments already uses. It names every missing, unreadable (with the reason) or changed file with its spec field (a spicy-regs table by name, after the spicy-regs input itself). model_arguments refuses an input the check's result lacks, so the check and the build cannot drift apart over which fields are inputs.
- --from-candidate checks the bound spec before it writes the build folder, so a refused run can be run again as it is.
- --plan runs it and reports the files and bytes checked.
- --execute runs preflight (fresh output and scratch, then the inputs) before it derives a ledger, builds a runtime or holds anything, and hands the result to model_arguments as verified_files, so each file is still read once. execute() runs preflight itself for other callers (archive_selective, tests).
- docs/development.md now plans (fetch, bind, check) before the watched execute.

Measured on the real candidate (release-20261110b/candidate-rebuilt) from a checkout without fetched spicy-regs tables: plan exits 2 in 5.5 s (149 MiB), naming all 14 tables, after checking the 55 pinned files that were present (409 MB); with every input fetched, the plan reads 69 files, 496.5 MB (W17 review). Before the change, the same plan exited 0. Two plants are caught: the check skipped (3 tests fail) and a second hash pass at execute (1 test fails).

## Acceptance Criteria

--plan and the start of --execute refuse a spec with any missing or changed pinned input in seconds, naming each one; execution reads each file once. Tests seen failing first, plus the two plants. The lane set on the branch is green (the manager schedules it), then merged.


## Notes

**2026-11-11T14:28:17Z**

validated 2026-11-11, closing: on main via a39f3cad (merge 97ff5611 of the W5+W17 stack; stacked lanes green on 31b5a6b2 per decisions-overnight 14:12Z). Code on origin/main: archive_model_job.check_inputs (line 203) and preflight (line 248) run before execute; model_arguments takes verified_files so each file is read once; failing tests first in c4d114c6 and 4f787d9f. The focused file test_archive_model_job.py takes over 3 minutes here, so I did not rerun it; the lane result stands.
