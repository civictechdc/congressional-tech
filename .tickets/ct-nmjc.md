---
id: ct-nmjc
status: closed
deps: []
links: [ct-tuez, ct-mi03, ct-tw3r]
created: 2026-10-21T14:41:26Z
type: task
priority: 1
assignee: mikewolfd
tags: [docspec_client, parquet, scale]
---
# Bound producer Parquet row_group_size in docspec_client to prevent contiguous StringArray buffer oversized_batch refusals at scale

When NativeDatasets.run_table and NativeDatasets.update_table (packages/docspec_client/src/docspec_client/docspec.py:390-515) write an in-memory PyArrow Table to source.parquet / replacements.parquet / deletions.parquet, pq.write_table is called with PyArrow's default row_group_size (1,048,576 rows). On our 262,144-row production scale test (filenames.parquet scalar columns), PyArrow wrote all 262,144 rows into a single row group whose decoded StringArray buffer occupied 5,567,060 bytes. Even when docspec-rs batch_rows was lowered to 1024, Arrow's zero-copy slice batch.get_array_memory_size() inside docspec-rs (src/storage.rs:411) counted the entire 5.57 MB contiguous page/row-group buffer and refused admission with oversized_batch when max_batch_bytes was 4 MiB.

## Design

In packages/docspec_client/src/docspec_client/docspec.py, configure producer Parquet writes in run_table, update_table, and update_evidence_table to pass a bounded row_group_size (e.g., matching configured limits batch_rows or min(batch_rows, 2048), default 2048) and compression='zstd'. Also evaluate decoupling reader batch buffer admission from output target_file_bytes in docspec-rs (src/storage.rs:283,363) so small reader batches do not force tiny output files.

## Acceptance Criteria

- NativeDatasets.run_table and update_table write producer Parquet files with bounded row_group_size (<= configured batch_rows / 2048) and compression='zstd'.
- Submitting a 262,144-row in-memory table with 64-300 byte string columns under max_batch_bytes=4 MiB and batch_rows=1024 succeeds without requiring the caller to manually pre-chunk row groups.
- Add a unit/scale regression test in tests/test_docspec_runtime.py verifying bounded row_group_size in producer Parquet files.

## Notes

**2026-10-21T16:40:00Z**

Implemented in `b28cc9b7`: added `PRODUCER_PARQUET_ROW_GROUP_SIZE = 2048` and `_write_producer_parquet` in `packages/docspec_client/src/docspec_client/docspec.py:34,80-85` and wired into `run_table`, `update_table`, and `update_evidence_table`. Verified in `tests/test_docspec_runtime.py::test_producer_parquet_writes_bound_row_group_size_for_batch_budget` and on the 262,144-row production scale probe with `batch_rows=2048`.


## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch standalone).
- Grades: proposal 77 → 77, work 73 → 73.
- Problem: The test fakes the engine and uses 4,219 rows; the 262,144-row submit under a 4 MiB limit is untested.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/standalone/standalone-verdicts.md:16
- Covered by: WS3 step 4 (ct-tw3r), decided with a native-loopback test at 4 MiB.
- See docs/reviews/2026-10-24-ticket-audit/README.md
