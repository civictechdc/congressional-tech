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

