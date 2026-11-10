---
id: ct-01kq
status: in_progress
deps: []
links: [ct-64t4]
created: 2026-11-10T15:46:33Z
type: task
priority: 2
assignee: mikewolfd
tags: [watchdog, memory, observability]
---
# Real memory per statement from the watchdog timeline and the step log

From the docspec-rs feedback root-cause analysis (cause D, pipeline half). The engine's pool figures are a ledger, not memory: build c03c43da's real peak (10.28 GiB physical) came during the export of member_votes.parquet while the pool showed 2.81 GiB. The watchdog timeline and the step log already hold what is needed; they lack a shared clock and a join. Change: each timeline sample carries the wall-clock epoch; scripts/measure/step_memory.py joins a step log with a timeline and prints peak footprint per statement and the --expect-gb to use. Branch claude/dx-step-memory. Links ct-64t4, ct-6p6d.

## Acceptance Criteria

The script reproduces the report's figures on build c03c43da (run peak 10.28 GiB during the member_votes.parquet export at 2.81 GiB pool); a timeline without epoch needs an explicit offset; no reader of timeline files breaks; lane and independent review done.

