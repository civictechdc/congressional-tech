---
id: ct-dzlf
status: closed
deps: []
links: [ct-2ukk, ct-adu0]
created: 2026-10-24T18:15:53Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-98sm
---
# WS1: remove test/production divergence (Python half)

75 `PYTEST_CURRENT_TEST` sites in 24 modules make production run code tests never see (audit hotspot 1; raw risk 4; the ct-2ukk commits `48137619`, `6c5712c1`, `017eb2cc`, `a8ddaa8f`, `93a63e1d`, `e4b3216b`, `f5e8fe1b`).

First move: add a characterization test for `iter_states_for` with more than 512 URLs, asserting the exact rows and `STATE_ORDER` ordering. Then delete `raw_storage.py:655-672` (reads the Oct 20 local `state.parquet` when its row count matches and swallows errors), and in the same series the other two row-count substitutions: `source_capture_inputs.py:61-74` (a cache stands in for receipts) and `catalog_raw_updates.py:155-183` (local adoption inputs).

The 51 incremental-only sites go with WS7, which deletes the Python incremental layer. The engine half (60 Rust sites and the deferred-commit revert) is in the docspec-rs epic.

## Acceptance Criteria

- The `iter_states_for` characterization test lands before any deletion.
- A ratchet test counts `PYTEST_CURRENT_TEST` in `packages/*/src`, fails if the count rises, and its limit is lowered in every PR until it reaches 0.
- In `partition_routing.py`, batched upload is the only path and is tested, including the final flush at `:200-202`.
- The 21 rebuild-path sites are settled from Step 0's B1/B2 comparison: a contract test and one behavior where output differs; an explicit parameter set by both tests and production where only speed differs.
- R-check 1-3 pass. The app's engine pin stays at `c949c67` until the engine half lands.


## Notes

**2026-10-24T18:21:03Z**

Engine half (60 Rust sites, deferred-commit revert, integration run without test-util): spicy-stack ss-pdv0.

**2026-10-24T18:47:53Z**

Efficiency pass: child ct-eb71 (Table.nbytes instead of byte-count round trips). Keep the engine's generic verified local read (build.rs:356-372).

**2026-10-30T17:36:12Z**

Completed across cefr-cjqb (d3093739), G01 (703a5920), G02 (df1bed37), G03 (c25ee9bb), and 3014737a: all 75 PYTEST_CURRENT_TEST sites across packages/*/src have been eliminated (0 remaining), raw_storage.py, partition_routing.py, source_capture_inputs.py, and catalog_raw_updates.py have been deleted, and test_zero_pytest_current_test_sites_across_all_packages in packages/congress_api/tests/test_surviving_raw_ratchets.py enforces 0 sites across packages/*/src (3 passed).
