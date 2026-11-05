---
id: ct-tbrj
status: open
deps: []
links: []
created: 2026-10-31T07:22:48Z
type: feature
priority: 3
assignee: mikewolfd
external-ref: ss-ikn9
tags: [spicy-regs, meetings, layer2]
---

# Tell users whether and when Congress.gov meeting detail was read

A researcher or the SpicyRegs comparison should be able to distinguish a listed meeting from a successful detail read. The archive currently exposes the publisher's update time, not an event-specific detail-read observation. Listing and detail responses share the normalized `congress_gov` source. The newer `chamber_basis` field describes meeting-row coverage; it does not prove a detail read.

The original comparison lives in `spicy-stack/spicy-regs/docs/evidence/committee-meetings-archive-comparison-2026-10-30.json`. Its `state_without_destination` entry lists a missing destination but does not compare the `committee_meetings_detail_reads` attempt journal. Treat it as a feature inventory, not proof of every event's acquisition state.

## Smallest useful change

Derive a small event-keyed observation from retained evidence: the exact Congress, chamber and event detail route, its bound successful receipt, and evidence that the response supplied that event's detail. Use the observed read time and receipt locator separately from Congress.gov's `updateDate`. A digest-wide maximum fetch time alone is insufficient. Reuse held evidence and nullable meeting fields where possible; avoid a parser pin move if existing evidence supplies the qualification.

## Acceptance Criteria

- State successful detail reads, failed attempts, listings with no successful detail read within known observation coverage, and unknown coverage distinctly. Missing evidence must not become a claim that detail was never read. Document the state, time and evidence fields in the release schema.
- Qualify each successful observation against the exact event route, receipt and detail response. Keep source update time separate from retrieval and journal times. Cover one success, one known-scope listing-only case, one failure and one undated legacy case; preserve missing timestamps rather than inventing them.
- Have the `ss-ikn9` comparison read the actual detail-attempt evidence and compare selected observations on pinned inputs. Confirm the fields needed by its consumer. Keep the SpicyRegs retirement decision separate from this feature's implementation.

[Final root-cause review](../docs/plans/production-mvp-root-causes-round4-20261105.md).


## Notes

**2026-11-05T20:56:46Z**

Final root-cause review: require event-specific successful detail evidence, preserve unknown coverage and source update time, and extend the SpicyRegs comparison to the actual attempt journal.
