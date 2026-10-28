---
id: cefs-6vp4
status: closed
deps: []
links: []
created: 2026-10-28T08:14:21Z
type: task
priority: 2
assignee: site
tags: [engine-first, F5, site]
---
# Keep site acceptance consumers independent of the F0 converter

Redirect surviving reader/gate/job-metadata fixtures to the reviewed archive_fixture API and retain the exact legacy meeting-key SQL used only by E4/F0 before the converter cut. No release/model behavior change or legacy deletion.

## Acceptance Criteria

Three surviving test imports use archive_fixture; E4 no longer imports archive_release; existing focused cases pass; owner-agreed helper has one implementation and unchanged SQL.


## Notes

**2026-10-28T10:15:11Z**

Completed direct stable archive_fixture imports for reader/gate/job-metadata and direct archive_format.legacy_meeting_keys import/use in E4. The helper is the exact owner-reviewed implementation, with no rule/path/code copy. Normal-merged integration39c1d982;83 focused parity/reader/gate/job-metadata checks PASS115.04s on pinned b2 (shared-machine overlap, not a throughput measurement). No converter deletion or legacy live-job change.
