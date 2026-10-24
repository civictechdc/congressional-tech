---
id: ct-tw3r
status: open
deps: []
links: [ct-oxg6, ct-6rnk, ct-4fcl, ct-ugqq, ct-0odd, ct-3faj, ct-m9td, ct-q968, ct-xq1y, ct-nmjc, ct-0n0y, ct-snzi]
created: 2026-10-24T18:15:53Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-98sm
---
# WS3: custody client - delete fallbacks, then one owner

`docspec_client` has three copies of stage-submit-retain (`run_table`, `update_table`, `update_evidence_table`, 390 lines) and fallbacks that change what a request means: a 415 falls back to Parquet, "unknown field" strips `partition_by` or `merge`, `operation_conflict` rewrites row groups, substring-matched retries, and raw-path `TypeError` retries that turn LATEST_OR_BACKFILL into key replacement (audit hotspots 4 and 5).

First move: tests that fail today. `_request` is called exactly once for every unknown-outcome error; an unknown field surfaces as a failure; `update_evidence_table` has a custody test; a schema-evolved raw-state update sends `merge`; a native-loopback test feeds real engine refusal bodies through `cleanup_safe`, including a post-admission `invalid_json`; the red `test_read_arrow_pin_and_header_verification` is fixed.

Then: delete every fallback; collapse the three copies into one owner (stage, submit once, keep the input unless refused); set `pre_admission` at the engine's admission point (an engine change that ships with the docspec-rs pin bump) and delete `models.py:27-56`; keep at most one byte-targeted row-group mode; refuse IPC for raw writers; keep one binary resolver (an explicit binary whose digest matches, outside tests).

## Acceptance Criteria

- The failing tests above land first.
- After the fallbacks go, every unknown-outcome error keeps the producer input and is sent once.
- The row-group mode is decided with a native-loopback test of a large table at `max_batch_bytes=4 MiB`.
- Only an explicit, digest-checked binary resolves outside tests; test-only resolution lives in conftest.
- R-check 1-3 pass, plus the custody tests.


## Notes

**2026-10-24T18:21:03Z**

Step 3's engine change (pre_admission set at the admission point) ships with the single docspec-rs pin bump tracked in spicy-stack ss-oxg1.

**2026-10-24T18:47:53Z**

Efficiency pass: child ct-5v1y (declare blake3, delete the fallback). Also hash producer files while writing them instead of re-reading (client.py:403-412, E9).
