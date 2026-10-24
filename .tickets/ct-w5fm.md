---
id: ct-w5fm
status: open
deps: []
links: []
created: 2026-10-24T18:46:38Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-98sm
tags: [audit-20261024, efficiency]
---
# Move the raw state and body index onto engine datasets

Efficiency pass E1, confirmed by five batches. Every save rewrites whole raw index leaves: O(S+B) per run, about 1.3 GB, about 512 new datasets and about 770 route PUTs, with nothing reclaimed (raw_storage.py:943-997,1143-1256; partition_routing.py). The routing pages index rebuildable tables; receipts are the provenance. Engine-first (decision 6). Plan open question 7 is answered yes.

## Acceptance Criteria

1. Send only changed rows through the engine's keyed update_table(..., merge=STATE_MERGE_SPEC), the path schema-evolved leaves already use (raw_storage.py:1197-1221), for every leaf. Log leaves touched and rows rewritten per run.
2. Prototype the layout and measure copy-on-write cost by layout (depends on the engine layout-measurement ticket), so rows that change together share files.
3. Migrate, staged, to one engine dataset per kind, checked against the old leaves, with old and new reads equal.
4. Delete partition_routing.py, raw_state_routes.py, the Python merge (specs.py:476-692, _merge_states) and raw_changes.py.
5. R-check 1-3 pass at every step.


## Notes

**2026-10-24T18:47:54Z**

Engine prerequisites (spicy-stack): ss-k1f0, ss-1uh5, ss-n68e, ss-eyhn. Related: ct-63hg (repair wrong stored_sha256 rows in place first).
