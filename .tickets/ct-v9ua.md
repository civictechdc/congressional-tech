---
id: ct-v9ua
status: closed
deps: []
links: [ct-63hg, ct-snzi]
created: 2026-10-22T18:42:15Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-4t6s
tags: [parquet, r2, raw-archive, captures, state, deduplication]
---
# Deduplicate Raw Capture Archive (state.parquet & captures.parquet): drop 100%-derivable body_key & redundant stored_sha256, and type sha256 as FixedSizeBinary(32) (~184 MB compressed saved)

Empirical raw-data and physical metadata audit of adoption-inputs/state.parquet (1,298,420 rows, 97.04 MB compressed / 371.01 MB uncompressed) and captures.parquet (3,909,134 rows, 282.90 MB compressed / 1.16 GB uncompressed) revealed:
1. 100.0000% of non-null body_key values in both tables (1,272,318 / 1,272,318 in state.parquet; 2,867,269 / 2,867,269 in captures.parquet) match the exact template f'bodies/sha256/{sha256[:2]}/{sha256}.gz'.
2. In state.parquet, body_key (40.84 MB compressed, 42.08% of file) + sha256 (38.85 MB compressed, 40.03% of file) consume 79.69 MB out of 97.04 MB (82.11% of the entire file!), storing the exact same 64-byte ASCII hex digest twice in every row.
3. In captures.parquet, body_key (71.49 MB compressed, 25.27%) + stored_sha256 (67.62 MB, 23.90%) + sha256 (67.54 MB, 23.87%) consume 206.65 MB out of 282.90 MB (73.04% of the entire file!), storing the same 64-byte hex digest 3 times per row (and stored_sha256 is always either NULL or equal to sha256).
4. Storing sha256 as 64-byte ASCII hex strings instead of FixedSizeBinary(32) (pa.binary(32)) doubles the uncompressed size and caused the 64-byte Parquet statistics truncation collision (ct-tuez).
5. status is typed as int64 (8B) for HTTP status codes (int16, 2B), fetched_at is an ISO-8601 string (42.87 MB compressed in captures.parquet) instead of timestamp(us, tz='UTC'), and row groups are 1,048,576 rows (only 2 row groups in state.parquet, 4 in captures.parquet).

## Design

1. In packages/congress_api/src/congress_api/retention/raw_archive.py (CAPTURE_ARROW_SCHEMA, STATE_ARROW_SCHEMA) and raw_storage.py, derive body_key on read via physical_body_object_key(sha256) (or a lightweight projection helper) instead of storing the 84-byte string column on disk.
2. Replace stored_sha256 (string) in captures.parquet with is_stored: pa.bool_().
3. Convert sha256 to pa.binary(32) (FixedSizeBinary(32)) with transparent hex conversion at the Python record boundary, status to pa.int16(), and fetched_at to pa.timestamp('us', tz='UTC').
4. Set row group size on captures.parquet and state.parquet to 65,536-131,072 rows for finer row-group pruning.

## Acceptance Criteria

1. state.parquet compressed size drops by ~42% (~41 MB saved) and captures.parquet compressed size drops by ~50% (~143 MB saved), saving ~184 MB compressed / ~815 MB uncompressed across the two files.
2. physical_body_object_key(sha256) / read helpers reconstruct body_key losslessly for all downstream consumers.
3. All raw_archive and raw_storage tests pass.


## Audit 2026-10-24

- Verdict: PARTIAL (batch syem).
- Grades: proposal 72 → 72, work 50 → 50.
- Problem: Data-integrity bug: gz captures appended since Oct 22 record a wrong stored-object digest, which corpus_recovery trusts (transfer.py:125,136).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:114
- Status: Closed as superseded by the simplification plan (P3, done in `54a68ac7`, ct-snzi): the capture schema carries `stored_sha256` and leaves it null when unknown; rows written Oct 22-24 are checked and repaired in place by ct-63hg. The size saving is not carried.
- See docs/reviews/2026-10-24-ticket-audit/README.md
