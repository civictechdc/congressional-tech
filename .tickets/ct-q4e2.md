---
id: ct-q4e2
status: open
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
