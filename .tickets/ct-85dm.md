---
id: ct-85dm
status: closed
deps: []
links: []
created: 2026-11-09T21:56:16Z
type: bug
priority: 1
assignee: mikewolfd
tags: [nightly, video]
---
# Nightly refuses at unsettled_video_records: the scheduled daily does not read new YouTube cache bodies

Nightly 20261109T195731 built the model, then refused to publish: explorer_invariants.unsettled_video_records = 52 (archive_model.py:1318). The weekly update-data.yml refresh replaces all 52 YouTube cache files on pipeline-data; B15 saves them to raw; the model selects the newest body per cache path; but the scheduled daily has not named video_records since 05b2122a (2026-11-05, 'Keep scheduled video refresh opt-in'), so nothing reads the new bodies. Every nightly fails this gate until they are read, and again after each Sunday refresh.

Owner decision 2026-11-09 (questions tool): read videos nightly. Name video_records in model/jobs/publish-daily.json again and recompute the daily pin in model/jobs/publish.json. backfill.json stays as it is: the decision covers the scheduled run only, and test_archive_maintenance.py keeps recording-byte acquisition a separate opt-in scope.

Evidence: <main checkout>/.cache/archive-release/investigations/nightly-20261109T195731-unsettled-video-records.md and investigations/nightly-video-read-20261109/ (the shipped producer's row builder parses the 52 Nov 8 git blobs: 67,406 videos, 14 s, about 1 GB; the full stage has not run on raw-store bodies). Independent review: investigations/nightly-video-read-20261109/review/findings.txt (ship, no blockers).

Expected next stop: gate 1 (release causes). videos.parquet is compared by video_key and its groups are not in release_gate.AUTOMATIC_GROUPS, so a nightly whose video rows differ from the live release refuses until a reviewed cause record exists. That is the owner's difference-list review, and it will recur after each Sunday refresh unless video additions get an automatic cause.

## Acceptance Criteria

The shipped daily names every capture-record table the shipped model reads, and a test fails when it does not. A nightly passes unsettled_video_records = 0 with a daily producer record for video_records.


## Notes

**2026-11-10T05:38:12Z**

2026-11-10: acceptance met. The nightly build at e65aef7e completed the model and its release-key invariants with the daily's video_records read, and release 619db5f9e08e was published at 05:34:59Z (run .cache/archive-release/nightly/20261110T043915.510596Z and the resume 20261110T053213.525969Z-resume). The test that the shipped daily names every capture-record table landed with 83be9f32.
