---
id: cefr-qajr
status: in_progress
deps: []
links: []
created: 2026-10-27T14:08:31Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, raw]
---
# B5: confirm body existence by key before reusing indexed metadata

## Acceptance Criteria

A digest found in the old index cannot skip a missing raw body write; synchronous and asynchronous capture share only confirmed per-run deduplication; new receipts/index carry actual stored-byte digest; focused contracts pass.

