---
id: ct-r4rd
status: open
deps: []
links: []
created: 2026-10-31T07:22:48Z
type: feature
priority: 2
assignee: mikewolfd
external-ref: ss-ikn9
tags: [spicy-regs, meetings, release, layer2]
---
# Publish the meeting fields spicy-regs committee_meetings carries and meetings.parquet lacks (ss-ikn9)

spicy-regs will retire its committee_meetings capture and read meetings.parquet instead (spicy-stack ss-ikn9, owner 2026-10-31: retirement waits for this ticket). Measured against spicy-regs wf/layer2-archive docs/evidence/committee-meetings-archive-comparison-2026-10-30.json (generation fbf53579, release c94bfedc): these committee_meetings columns have no destination in the release: congress, update_date (Congress.gov updateDate), location_building and location_room (the release states no split location), and the Congress.gov meeting_type label (Hearing/Markup/Meeting) where meetings.meeting_type states the House XML code for House rows (HHRG 726, HMKP 429, HMTG 228 rows; 1,383 House rows differ). Committee name and url resolve through the committees table by system_code.

## Acceptance Criteria

meetings.parquet (or a declared companion keyed by event_id) publishes congress, update_date, location building and room, and the Congress.gov meeting type label, documented in schema.json; spicy-regs' compare_committee_meetings_archive.py reports each with a destination and value agreement on matched event_ids.

