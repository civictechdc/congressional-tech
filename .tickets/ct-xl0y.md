---
id: ct-xl0y
status: in_progress
deps: []
links: []
created: 2026-10-20T18:35:20Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, rust, efficiency]
---
# Remove avoidable work inside DocSpec native Update

The current Update measurement is a baseline, not a verdict on native capability. Trace source scans, changed-file writes, temporary key tables, lifecycle commits and application selection coupling. Fix measured avoidable native work without weakening retained changes, concurrency or stale-base guards.

## Acceptance Criteria

Controlled before/after native fixture with equivalent exact changes/old pins/recovery guarantees. Local gates and independent Rust review. Explicitly distinguish a safe engine fix from any separate prepare/select API change. Preserve pinned production binary and state.


## Notes

**2026-10-20T18:47:14Z**

CS300 review distinguishes a constant saved catalog registration from algorithmic work: current replace_keys probes every source file and executes prepared-key scans F+C times (F files,C changed files). Measure file-count growth and DataFusion scan bytes before deciding whether a further native change is justified. Unchanged-file reuse does not mean zero scans.
