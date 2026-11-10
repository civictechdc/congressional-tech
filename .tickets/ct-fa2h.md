---
id: ct-fa2h
status: open
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: bug
priority: 2
assignee: mikewolfd
tags: [capture, senate, url_state]
---
# www.energy.senate.gov refuses the fetcher: 303 in-scope addresses at 403

url_state on 2026-11-10: 303 in-scope www.energy.senate.gov addresses are at 403, including 9 that were 200 and stored on 2026-10-05 (e.g. .../hearings-2025-12-17-business-meeting-to-consider-pending-legislation/). 506 of the 510 first fetches reported earlier are /wp-json/oembed/ addresses the scope already excludes. Separately 88 Senate addresses went from 404 to a request failure with no status. No address lost last_good_at. Source: .cache/archive-release/release-20261110/causes/review-capture-address/.

## Acceptance Criteria

The 303 addresses are fetched, or the refusal is recorded with what was tried (user agent, rate, route); the 88 request failures have a recorded status or reason.

