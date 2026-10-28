---
id: cefs-1hte
status: in_progress
deps: []
links: []
created: 2026-10-28T16:55:13Z
type: task
priority: 2
assignee: mikewolfd
---
# Prepare G06 old publisher closure removal

Lead-delegated old v6 publisher, CLI, attempt and verify closure; preserve shared client and raw journal APIs. Replacement archive_publish_job. No merge.


## Notes

**2026-10-28T16:59:04Z**

Lead 165227 delegated this old publisher closure. Remove obsolete v6 entry points, attempt/plan/CLI/resume/verify and dead status/preflight tools; keep client, constants, raw continuation/local/reconciliation and generic inventory tests. 65 focused kept client/journal/inventory/wrapper tests pass in 36.12s; explorer 82 pass and Astro 29 pages in 2.27s. G12 and G13 paired cuts follow before final lane; root review requested after green group.
