---
id: ct-q4e2
status: closed
deps: []
links: [ct-4jms, ct-0mqc]
created: 2026-11-08T18:04:36Z
type: feature
priority: 1
assignee: mikewolfd
tags: [capture, meetings, freshness]
---
# Discover new hearings during scheduled capture

The public archive has no Congress.gov meeting update after 2026-10-30. Scheduled capture (capture-archive.yml) starts from the release's URL state plus in-run discovery, with no meeting seed list (raw-source-tables.md documents none), and the 45k never-tried legacy URLs sort ahead of rechecks, so new hearings are never discovered. The 2026-11-08 supervised 2,000-request run attempted 0 Congress.gov committee-meeting URLs. Options: (a) pass the Congress.gov committee-meeting list endpoints (per chamber, current Congress) and the committee hearing-listing pages as reviewed cutoff URLs each run (they now run first, 4a632e11), and confirm discovery enqueues new event URLs from them; (b) schedule the B14 meeting fetchers (house-/senate-meeting-records) so they write receipts the nightly daily step ingests. Done when a scheduled run captures at least one meeting dated after the previous release and the nightly publishes it.


## Notes

**2026-11-08T19:07:47Z**

2026-11-08: owner chose 'fix the existing code and run it'. The existing B14 fetcher is congress_api.cli.fetch_meetings (Congress.gov committee-meeting list API per chamber with fromDateTime, then detail records, through the common receipt writer under congress/meetings); nothing ran it after ct-klyz. Fixed its House and Senate page families to ones publish-daily ingests (f3493790, merged b95ae619; test proves it). Applied from clean main b95ae619, window since 2026-10-25, Congress 119: 43 receipts (31 stored, 9 unchanged) under receipts/congress/meetings/2026-11-08/; 13 new event IDs dated after Oct 30 (House 118861, 119588, 119590, 119592, 119593; Senate 338800–338807) plus 27 updates. They reach the archive when the nightly gets past readings pending (being fixed). Next: schedule it in the nightly (--since-days 7). Evidence: .cache/archive-release/investigations/ct-q4e2-20261108/.

**2026-11-09T16:34:36Z**

2026-11-09: wired option (b) into scheduled capture. fetch_meetings has --since-days N, which relists committee-meeting/<congress>/{house,senate,nochamber} with fromDateTime = now - N days, for each Congress the window touches (year_to_congress). This is the same request shape as the 11-08 supervised spec. capture-archive.yml runs it with --since-days 7 and a fixed research User-Agent before the budgeted capture, and uploads archive-meetings/summary.json. The 7-day overlap repeats a missed day. Unchanged details store as unchanged. Tests: test_capture_scheduler.py::test_scheduled_meeting_relist_covers_each_chamber_and_every_congress_in_the_window and .github/tests/test_archive_workflows.py::test_capture_relists_recent_meetings_before_the_budgeted_capture. Done condition still open: one scheduled run plus a nightly publishing a meeting dated after the previous release. See the ct-4jms Runbook.

**2026-11-10T13:27:30Z**

2026-11-10: blocked on the same owner step as ct-4jms (the two hosted capture secrets). Nothing else changed here today.

**2026-11-10T20:39:29Z**

2026-11-10 release 77673bfb8fcf published the results of a meetings relist run by hand on this Mac (run 20261110T140153Z-6b3c368e77f8: 38 receipts, 35 Congress.gov details). Per the cause record: 3 new meetings, 25 nominations, 10 recording matches and 4 witnesses, plus 37 witness re-keys (ct-uywf). The relist is not yet seen running from the scheduled workflow, which still waits on the hosted secrets (ct-4jms).

**2026-11-11T14:40:09Z**

validated 2026-11-11, left open: the code is on main (fetch_meetings --since-days 7 in capture-archive.yml) and a hand relist proved the path (release 77673bfb8fcf: 3 new meetings from run 20261110T140153Z-6b3c368e77f8). The done condition needs a scheduled run, which waits on ct-4jms's secrets.

**2026-11-12T21:45:32Z**

2026-11-12 owner decision (15:06-05:00): a forced workflow_dispatch capture plus a manual Mac nightly counts as Wave 7 acceptance; schedules (03:23 UTC capture, 05:30 local nightly) stay enabled. Evidence: hosted capture-archive.yml run 43302430173 (event workflow_dispatch, main 9924b385, environment archive-capture with ARCHIVE_CAPTURE_R2_* secrets set 14:50-05:00) green in 22m47s; meetings relist 20261112T204014Z-4f9efb076145 + budgeted capture 20261112T204110Z-fc2d35e98d37 from release 750a2a24d00a (2,000 requests, 1,085 captures, 152 MB). Nightly 20261112T210256Z ingested 1,142 new receipts and refused at the gate; cause record model/jobs/release-causes/750a2a24d00a-6c46b8f7a606.json (55 groups, evidence .cache/archive-release/investigations/capture-night-20261112/) committed 0695e4ba; resume 20261112T213624Z published 6c46b8f7a606 at 21:40Z (unpin + notes f5cbc687, docs/releases/2026-11-12-6c46b8f7a606.md). Hosted MCP pinned (ca808760), version 8b2ed383, smoke green on 6c46b8f7a606. Published release adds 21 meetings dated after Release 5 (e.g. 119589, 119594, 119596, 119597, 338823-338832; dated 2026-11-17..19). Done condition met: meetings dated after the previous release are in published release 6c46b8f7a606.
