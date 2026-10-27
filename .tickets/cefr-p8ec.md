---
id: cefr-p8ec
status: in_progress
deps: []
links: []
created: 2026-10-27T13:54:32Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B2: file-based raw fetcher, archive expander and receipt writer

## Acceptance Criteria

Explicit scope and pacing policies; bounded file-backed transfers; typed receipts after bodies; archive refusal facts; focused contract suite passes.


## Notes

**2026-10-27T14:08:16Z**

Core components implemented through be8605b0; required contracts landed first. Focused B2 group: 114 passed, 1 duplicate-member fixture warning. No live jobs/credentials/network writes. Independent code and architecture review pending with raw parent; leave ticket open. Evidence docs/measurements/engine-first-20261027/b2/README.md and scratch codex-raw/b2-plan/cxb_b2_group.log.
