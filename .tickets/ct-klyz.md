---
id: ct-klyz
status: open
deps: []
links: [cef-96wc]
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, ops, b14, cutover, track5]
---
# T5.1 (B14): Run B14 meeting fetchers live once and remove legacy weekly meeting job from update-data.yml

Per docs/plans/phase-2-annex-20261028.md §4.1: execute the B14 meeting fetchers live once, then remove the legacy weekly meeting inventory job from .github/workflows/update-data.yml and drop capture's weekly inventory seeds.

## Acceptance Criteria

B14 meeting fetchers have completed a live run, the weekly meeting inventory job is removed from update-data.yml, and weekly inventory seeds are dropped.

