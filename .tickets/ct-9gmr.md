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
# Run selective backfill and release through the existing archive jobs

publish_v21 was built with ad hoc /private/tmp/publish_v* scripts outside the guarded controller. Owner decision 2026-11-01: extend the checked-in jobs rather than add a CLI, and make no further live publishes from scratch scripts. Parser-version selection moved to a separate ticket.

## Design

1. Reuse archive_backfill_job.py, capture_backfill.py and archive_controller.py resume.
2. Add predicate-scoped recomputation for captures (receipt predicate plus capture_backfill_guard.validate_generation), filename_readings (URL predicate) and D4 (meeting_records and appearance_records).
3. Use a gitignored .cache/archive-release/ workspace.
4. Coordinate replay planning with ct-pocg; do not build a second metadata replay path.

## Acceptance Criteria

- A narrow parser fix runs through a checked-in job spec with no scratch script.
- Unaffected rows are reused, and the combined output passes the guard and all model invariant suites.
- Resume works after an interrupted run, with unit tests in packages/viewer_publication/tests/.

