---
id: ct-k2ij
status: open
deps: []
links: [ct-717p]
created: 2026-11-04T16:47:47Z
type: task
priority: 2
assignee: mikewolfd
tags: [acquisition, house, committee-records]
---
# House gap-filler fetches meeting XML for events whose committee documents need it, not only for Congress.gov gaps

ct-717p trace (2026-11-04, .cache/archive-release/investigations/ct-717p-event-118300-trace-20261104.md): House meeting XML enters captures only via the House gap-filler (Congress.gov lacks documents, witnesses or a print), an explicit fetch spec, or a retained document-inventory link. Events that Congress.gov covers well are never fetched from docs.house.gov, so their committee_records (amendment CA documents etc.) are absent: 295 House events show amendment documents but no committee records and no House XML (52 in the 119th Congress). Separately, 49 events have House XML but still no committee records: an untraced, different cause.

## Acceptance Criteria

Selection rule covers events with committee documents that only the House XML carries; a plan-only run lists the affected events; the 49 House-XML-without-records events are traced to a cause; fetched bodies flow through the nightly within its budget.


## Notes

**2026-11-04T16:55:20Z**

Reusable completeness check for this work (from the ct-717p independent review, .cache/archive-release/investigations/ct-717p-event-118300-review-20261104.md): match on the event-specific link or body hash, not the document file name (Rules CA names repeat across meetings: Amdt-7 in 7 events, Amdt-1 in 53), emit a pass/fail status, and fail on any bill key derived from an amendment ordinal. The review's plant harness shows the name-only check misses a wrong-event link, a wrong-event body hash and an ordinal-derived bill key.
