---
id: ct-opy0
status: open
deps: []
links: []
created: 2026-10-31T07:22:48Z
type: bug
priority: 2
assignee: mikewolfd
external-ref: ss-ikn9
tags: [spicy-regs, meetings, layer2]
---

# Explain why a published meeting’s chamber is unknown

Readers should be able to tell whether an event is joint, whether the source leaves its chamber unclear, or whether a document is the only evidence of the event. In `e145d24c389e`, 713 of 18,687 meeting rows have no chamber and 547 also have no date. The November 2 pinned comparison found joint committee codes on 165 of 166 dated nulls. A committee code alone does not settle every row’s chamber.

## Root cause (2026-11-05)

The meeting export deliberately retains event references from linked documents, even without a meeting record, so users can still open the document. It publishes those references with the same bare null chamber as source-backed meeting rows. House event `119583` is the document-only example. It links to `HHRG-119-ED00-20261023-SD001.pdf`, and the exact House ByEvent URL had zero attempts in the checked release. Dated event `104064` already has a null chamber in the retained producer rows and has both House and Senate committee keys. Its exact raw body was unavailable locally, so whether the publisher omitted a chamber or the parser failed to recognize it remains open.

## Smallest useful change

Use the existing meeting and document evidence to publish a supported chamber or a clear reason for its absence. Distinguish supported joint identity, a source whose chamber is unstated or unverified, and an event reference without meeting detail. Preserve source values and links. Use Congress.gov detail for an exact missing event when it supplies the needed evidence. Otherwise record the specific gap. Compare the selected release through the existing `ss-ikn9` `coverage_archive_to_committee_meetings` check.

## Acceptance Criteria

- Each published meeting row has a supported chamber or a documented reason for its absence in a field named in the release schema. Joint identity requires supporting evidence. A source-backed unknown stays distinguishable from a missing meeting record.
- Each event reference without meeting detail is filled from Congress.gov detail where available or listed as an explicit release gap. Preserve the event IDs and document links. Confirm the distinction on `119583` and `104064`.
- The comparison accounts for the original 713 nulls and changes in the selected population.

## Coordination and evidence

The JEC matcher can use supported local committee identity while leaving the raw chamber unknown. This ticket owns the shared explanation for missing chamber. Absent event `117688` has its own recovery scope. [JEC matching](ct-kthe.md) · [Absent event](ct-db3w.md) · [Root-cause analysis](../docs/plans/production-mvp-root-causes-20261105.md) · [Earlier release comparison](../docs/measurements/release-diff-c94bfedc-448651e7-20261101.md)

## Notes

**2026-11-02T00:36:42Z**

Unchanged on 448651e7: 713 NULL chamber = 166 dated + 547 undated. Correction: the House row matched with archive chamber NULL is event 119583, not 117688; 117688 is absent. 165 of the 166 dated rows have joint committee codes. 0 of the 547 are in meeting_records.

**2026-11-05T20:18:06Z**

Integrated chamber_basis so readers can distinguish a publisher that omitted chamber from a missing meeting detail, while preserving the raw chamber value. The retained e145 census distinguishes 547 detail gaps from 166 source-unknown cases. Focused producer/model checks passed. The full candidate and selected-release readback wait until all waves finish.
