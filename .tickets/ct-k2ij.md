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

# Select House meeting XML for missing committee records

Researchers should be able to find structured committee records when Congress.gov already lists the event, documents and transcript. The legacy gap-filler skipped Rules event `118300` because those fields satisfied its selection rule. The exact XML has since been captured. [ct-717p](ct-717p.md) owns its delivery.

Release `e145d24c389e` has 295 House events with amendment documents, zero committee records and no published House XML update timestamp. That includes `118300` and 51 other events in Congress 119. Another 49 have a House XML update timestamp and zero committee records, including three in Congress 119. These are signals for investigation. A missing timestamp alone leaves receipt and body status unknown, and a populated timestamp leaves the amendment evidence unresolved.

## Smallest useful change

Plan a bounded set of events from the held inputs. Check exact receipt and body identities before selecting new acquisition. Use the maintained `fetch_meetings` House target plan or an explicit candidate input to the configured capture scheduler. The hosted workflow uses that scheduler, and Mac nightly consumes held receipts through incremental publication. The legacy predicate alone does not reach either path.

For the 49 events with a selected House observation, trace the exact body, producer output and model selection before choosing a fix. Distinguish a genuinely empty source list, a failed read, a missed producer row and a later selected version. Acquire only source evidence needed to resolve an actual gap.

## Acceptance Criteria

- The plan names each targeted event, why it needs House XML, and the held evidence considered. Approved bounded capture flows into the existing receipt, incremental producer and publication path within the established budget. Account for captured, unavailable and excluded events.
- Keep the 295 and 49 cohorts separate. Give the 49 a supported first missing boundary or a named missing-evidence disposition.
- Reuse the independent `ct-717p` event-specific URL or body check. Demonstrate rejection of wrong-event URLs, wrong-event bodies and bill keys inferred from amendment ordinals. Repeated filenames are insufficient evidence.

Reuse the `ct-717p` one-event trace and independent review in `.cache/archive-release/investigations/`.

[November 5 root-cause analysis and source evidence](../docs/plans/production-mvp-root-causes-round2-20261105.md).

## Notes

**2026-11-04T16:55:20Z**

Reusable completeness check for this work (from the ct-717p independent review, .cache/archive-release/investigations/ct-717p-event-118300-review-20261104.md): match on the event-specific link or body hash, not the document file name (Rules CA names repeat across meetings: Amdt-7 in 7 events, Amdt-1 in 53), emit a pass/fail status, and fail on any bill key derived from an amendment ordinal. The review's plant harness shows the name-only check misses a wrong-event link, a wrong-event body hash and an ordinal-derived bill key.
