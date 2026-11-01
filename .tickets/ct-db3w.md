---
id: ct-db3w
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
# Capture the 7 committee meetings spicy-regs holds and the release lacks (ss-ikn9)

Seven event_ids in spicy-regs committee_meetings (generation fbf53579) are absent from meetings.parquet in release c94bfedc: House 117688; Senate 335202, 335760, 335780, 337725, 338764, 338786 (spicy-regs wf/layer2-archive docs/evidence/committee-meetings-archive-comparison-2026-10-30.json (generation fbf53579, release c94bfedc): coverage_committee_meetings_to_archive.missing_event_ids). spicy-regs holds committee_meetings retirement until the archive covers them (owner 2026-10-31).

## Acceptance Criteria

Each of the seven event_ids appears in a published release's meetings.parquet, or the release records why the event is excluded (e.g. Congress.gov withdrew it), and the spicy-regs comparison reports zero committee_meetings rows missing from the archive.

