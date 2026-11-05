---
id: ct-3szv
status: closed
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


## Notes

**2026-11-05T12:02:36Z**

2026-11-05 Codex continuation: completed the exact 190a6b2a read-only corpus audit (307,033 body checks; zero missing/mismatch/content/digest-conflict errors; 6,980.3 s; peak RSS 5.989 GiB). Applied its retained SHA-checked 378,070,387-byte verification records through maintained raw_verify --apply-staged, then executed a refreshed retention-only plan under the local nightly lock and exact mutation boundary: 74 unreferenced derived objects / 289,848,254 bytes removed; current e4538f00, previous448651e7 and external c94bfedc retained; final plan zero deletes. Apply/retention47 s, peak0.169 GiB. No capture rows or raw bodies deleted or rewritten;33 digest repair candidates remain evidence only. Evidence: .cache/archive-release/investigations/ct-3szv-maintenance/{full-readonly.json,full-readonly-watchdog.json,completed-maintenance-result.json,completed-maintenance-watchdog.json,retention-after-plan.json}. Integration final full lanes pending; prior focused implementation checks254passed. Actual hosted run not claimed.

**2026-11-05T13:09:52Z**

Qualified source 7f9ebddd2cb632f97bc0214ffd44beaf72b0a5a6: all three production-offline shards passed (11,497 passed; 37 unchanged legacy skips; 3 existing expected failures), native-loopback full lane passed (10 tests, zero skips), and storage-loopback full lane passed (1 test). Evidence: .cache/archive-release/handoffs/cursor-resume-20261105/qualification-7f9ebddd2cb6/combined-results.json. The real maintenance audit and staged application/retention operation are complete, as recorded above. No hosted execution is claimed: the November 4 owner decision uses the Mac nightly. Dry-run, staged-apply and input-discovery checks are included in qualified code. Closing the maintenance implementation and measured-run work.
