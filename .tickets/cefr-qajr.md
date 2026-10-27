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


## Notes

**2026-10-27T14:10:07Z**

Contract commit 0e411a74 reproduces original bug (3 failed,1 passed). Implementation adds shared per-run confirmed hash set independent of persisted index metadata. Focused project runner test_body_existence_by_key.py, test_raw_source_sync.py, test_body_store_contract.py, test_surviving_raw_ratchets.py: 88 passed in13.06s. Includes new receipt and old-index stored digest comparison against actual compressed bytes. Legacy collision readbacks remain in legacy path; new BodyStore path untouched. Pending independent review.
