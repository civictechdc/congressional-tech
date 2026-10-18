---
id: ct-x7vx
status: in_progress
deps: [ct-zb9y]
links: [ct-8uwj]
created: 2026-10-18T20:54:36Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, qualification-pending]
---
# Observe deployed unchanged-publication job cost

The early read-only check is implemented and locally verified in ct-zb9y. Complete hosted-job time and downloads still require observing that revision after an authorized deployment. Local fixture timings and telemetry wiring are not that evidence.

## Acceptance Criteria

After an authorized deployment, retain an ordinary unchanged-run job-cost and preflight receipt. Confirm the deployed revision, zero table reads and publication writes, skipped full workspace setup, elapsed job-step time, and received bytes with their stated measurement limits. Compare with a compatible prior job; report runner/setup differences. Do not dispatch, retry, or deploy solely from this ticket.


## Notes

**2026-10-18T21:20:33Z**

The original rebuild and automatic downstream publisher completed at remote revision 24137dd and passed live verification. That publisher does not contain this remediation, so its runtime does not qualify this ticket. Leave open until the new implementation is separately deployed and an ordinary unchanged run can be observed.

**2026-10-18T21:24:34Z**

The current goal explicitly requests testing, review, squash and merge through all remaining tickets. Original rebuild and live verification are complete. Preparing the reviewed implementation for a squash PR, then hosted checks and merge; observe ordinary scheduled publication afterward. Raw-source pushes select validation only. No manual dispatch, automatic retry, resource change, or source acquisition. Before/after qualification remains open until real receipts pass.
