---
id: ct-3szv
status: open
deps: []
links: []
created: 2026-11-04T02:46:36Z
type: bug
priority: 2
assignee: mikewolfd
tags: [archive, maintenance, ci]
---
# Maintenance job: produce its raw-verification inputs and make its dry run read-only

Found 2026-11-03 while measuring maintenance for ct-r8jd. (1) model/jobs/maintenance.json reads raw_verification inputs at output/archive-maintenance-inputs/ (captures.parquet, receipt-inventory.json, verification-inventory.json); nothing in the repo or the workflow produces them, so the job refuses both locally and hosted. (2) archive_maintenance --plan only echoes the spec; it never lists the release keys it would delete. (3) execute(spec, execute=False) still runs apply_staged when verification is valid, so a dry run writes to the body store. No local R2 credentials were available to run it either.

## Acceptance Criteria

A hosted maintenance run builds its raw-verification inputs from the pinned archive_r1b captures and the bucket's receipt and verification inventories; --plan lists delete_keys and kept releases without writing; a dry run performs no writes. One real run is measured under the watchdog and its peak sets rss_gb in .github/archive-jobs.json (closes ct-r8jd).

