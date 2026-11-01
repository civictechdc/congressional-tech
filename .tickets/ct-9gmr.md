---
id: ct-9gmr
status: open
deps: []
links: [ct-77zb, cef-96wc, ct-1mbc, ct-kw9b, ct-pocg]
created: 2026-11-01T17:43:18Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [etl, backfill, viewer-publication, phase2]
---
# Add checked-in predicate-scoped backfill CLI, compatible parser_versions priority selection, and Step-0 readings key-uniqueness preflight

Replace ad-hoc /private/tmp/publish_v* backfill scripts with a checked-in backfill/release CLI and allow multi-version parser_versions priority selection so narrow parser fixes do not require re-stamping unchanged rows.

## Design

1. In packages/viewer_publication/src/viewer_publication/{archive_model_job.py,archive_model.py,archive_publish_job.py} and model/sql/*.sql, allow parser_versions in publish-model.json to accept either a single hash or an ordered list of compatible hashes per parser, selecting 1 row per natural key ((body_sha, parser) for readings, url for filename_readings, record_sha_hex for D4) by declared version priority.
2. Add a Step-0 preflight check in archive_model.py (build_prepared_release) asserting COUNT(*) == COUNT(DISTINCT (body_sha, parser)) on selected readings in <1s before executing the 180-step SQL DAG.
3. Add a checked-in CLI (packages/viewer_publication/src/viewer_publication/archive_backfill.py) using a gitignored .cache/archive-release/ workspace that supports predicate-scoped selective recomputation for captures (receipt predicate + capture_backfill_guard.validate_generation), filename_readings (URL regex predicate), and D4 (meeting_records/appearance_records with R2 candidate body prefetching), plus completed-model.json resume and remote R2 Iceberg table sync.

## Acceptance Criteria

- A narrow parser fix can append only recomputed rows with the new parser_version without re-stamping unchanged rows.
- Duplicate (body_sha, parser) rows in readings are deterministically deduplicated by declared parser_version priority or rejected at Step 0 in <1s rather than failing at final export ordering.
- Predicate-scoped selective backfill and release resume run via a checked-in CLI command backed by .cache/ with unit test coverage in packages/viewer_publication/tests/.

