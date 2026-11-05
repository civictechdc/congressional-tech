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

The meeting export deliberately retains event references from linked documents, even without a meeting record, so users can still open the document. The `e145` export gives those references the same bare null chamber as source-backed meeting rows. House event `119583` is the document-only example. It links to `HHRG-119-ED00-20261023-SD001.pdf`, and the exact House ByEvent URL had zero attempts in the checked release. Dated event `104064` already has a null chamber in the retained producer rows and has both House and Senate committee keys. The exact raw body was unavailable in that audit. Whether the publisher supplied a chamber remains unresolved.

## Implementation and remaining checks

The first-wave merge `18049548` adds `chamber_basis` to explain the published chamber. It distinguishes `source` for a stated value, `source_chamber_unknown` for a source-backed meeting with a null chamber, and `meeting_detail_missing` for a document-backed event reference.

The retained `e145` census accounts for all 713 nulls, with 166 source-backed unknowns and 547 missing meeting details. The SpicyRegs comparison matched 72 null-chamber events. Twenty-three focused model and schema checks passed, including unknown source chamber, absent meeting detail and an explicit joint chamber.

After the build hold clears, the release coordinator will run the maintained `ss-ikn9` comparison on the exact selected archive and account for changes from the baseline. Check `104064` for a source-backed unknown and `119583` for a listed detail gap or a supported recovery. Preserve both event IDs and the document link for `119583`. [Release follow-through](../docs/plans/production-mvp-follow-through-20261105.md)

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
