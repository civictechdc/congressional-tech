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
# Resolve the 713 meetings.parquet rows with NULL chamber (547 with no meeting record) (ss-ikn9)

In release c94bfedc, 713 of 18,687 meetings.parquet rows have chamber NULL; 547 of those have no meeting_date (no meeting record behind the event_id), 72 are also in spicy-regs committee_meetings (71 spicy-regs states as nochamber, 1 as house: event 117688's House row matched with archive chamber NULL), 95 predate spicy-regs' window (spicy-regs wf/layer2-archive docs/evidence/committee-meetings-archive-comparison-2026-10-30.json (generation fbf53579, release c94bfedc): coverage_archive_to_committee_meetings). spicy-regs holds committee_meetings retirement until these are resolved (owner 2026-10-31).

## Acceptance Criteria

Every meetings.parquet row either states its chamber or carries a documented reason (e.g. joint/nochamber) in a column schema.json names; event_ids with no meeting record are either filled from Congress.gov detail or listed as an explicit gap in the release.

