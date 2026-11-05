---
id: ct-db3w
status: open
deps: []
links: [ct-r4rd]
created: 2026-10-31T07:22:48Z
type: bug
priority: 2
assignee: mikewolfd
external-ref: ss-ikn9
tags: [spicy-regs, meetings, layer2]
---

# Account for eight SpicyRegs meetings missing from the archive

Researchers should be able to find a committee meeting held by either archive or see why it falls outside coverage. Comparing SpicyRegs `37a6ebd4` with archive release `e145d24c389e` confirms eight missing events. All eight are absent from the selected parsed meeting input as well as `meetings.parquet`. The receipt and admission causes remain unresolved for each event.

| Event | SpicyRegs date |
| --- | --- |
| House `117688` | 2024-09-25 |
| Senate `335202` | 2023-11-30 |
| Senate `335760` | 2024-05-15 |
| Senate `335780` | 2024-05-15 |
| Senate `337725` | 2025-12-09 |
| Senate `338764` | 2026-09-23 |
| Senate `338786` | 2026-09-30 |
| House `119588` | 2026-11-13 |

SpicyRegs labels all eight Scheduled. That label alone does not establish a successful publisher response. The first seven fall within the archive's observed date span. `119588` is beyond that span and needs an explicit future-event or source-window decision.

## Smallest useful change

Check existing source windows, exact detail receipts, held bodies and producer eligibility for the named IDs. Use the existing meeting acquisition or producer path to repair each demonstrated gap. A supported withdrawal or a deliberate scope exclusion gets its own evidence. Reuse the same generation pair for the membership comparison and the separate [ct-r4rd](ct-r4rd.md) value comparison. Handle nullable URLs in the comparator's URL self-check separately. The event-ID result does not depend on URL lookup, and e145 publishes no NULL source URLs.

## Acceptance Criteria

- Every named event appears in a qualified, published `meetings.parquet` or has an evidence-linked exclusion.
- Record both generation IDs, the comparable event population and all exclusions. The SpicyRegs event comparison reports zero unaccounted-for missing meetings in that population.
- Keep SpicyRegs adoption and retirement in `ss-ikn9`. Reuse `coverage_committee_meetings_to_archive.missing_event_ids` and the qualified archive output as evidence.

[November 5 root-cause analysis and source evidence](../docs/plans/production-mvp-root-causes-round2-20261105.md).

## Notes

**2026-11-02T00:36:42Z**

Live on generation fbf53579: House missing 117688; Senate missing 335202, 335760, 335780, 337725, 338764, 338786. All 7 are absent from meetings.parquet on 448651e7. New on generation 37a6ebd4: 119588, scheduled for 2026-11-13. The zero-missing criterion also needs spicy-regs to move its bound and the NULL URL defect fixed.
