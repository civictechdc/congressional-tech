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
# Publish per-meeting detail-read state (list-only vs detail read) (ss-ikn9)

spicy-regs committee_meetings records whether each meeting's Congress.gov detail was read or only listed, with the committee_meetings_detail_reads table holding one row per detail read. The release states no equivalent, so a consumer cannot tell a list-only meeting from a fully read one (spicy-regs wf/layer2-archive docs/evidence/committee-meetings-archive-comparison-2026-10-30.json (generation fbf53579, release c94bfedc): state_without_destination). spicy-regs retirement waits on this (owner 2026-10-31).

## Acceptance Criteria

meetings.parquet or a keyed companion states, per event_id, whether the detail record was read and when; schema.json documents it.

