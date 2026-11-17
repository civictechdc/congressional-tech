---
id: ct-1qr7
status: open
deps: []
links: []
created: 2026-11-17T18:18:49Z
type: task
priority: 2
assignee: mikewolfd
tags: [capture, queue]
---
# Do not fetch again an address that is already saved under another spelling

Root cause 6 of the 2026-11-17 RCA. The fetch queue held https://transportation.house.gov/calendar/EventSingle.aspx?EventID=409450 beside the saved eventsingle.aspx form; the capture fetched the page again, its bytes differed only in a news sidebar, and its link key changed. The recapture proof handles the symptom; the queue should not ask for it.

## Acceptance Criteria

A queued address whose normalized form is already saved is not fetched as new. Measured before and after on a published release: how many queued addresses were duplicates of saved ones.

