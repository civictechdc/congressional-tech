---
id: ct-7jv1
status: in_progress
deps: []
links: []
created: 2026-11-09T15:50:38Z
type: feature
priority: 3
assignee: mikewolfd
---
# Say in meeting results whether captions are archived or only advertised by the publisher


From the 2026-11-09 hosted MCP audit: 195 meetings report publisher caption availability (mostly YouTube metadata) but hold no retained caption track, and 3 claim a video association without a retained recording. The auditor withdrew the bug once the distinction was clear, and asked that the API state it. Proposal: expose the existing distinction as a named field on meetings and hearing bundles (for example captions: {advertised: true, archived: false, basis: ...}) so transcripts[] being empty is self-explaining. Data already exists; no new capture. Tags: mcp, mcp-audit-20261109.

## Notes

**2026-11-09T16:35:16Z**

2026-11-09 (branch claude/ct-thread3-mcp-polish, unpublished): meeting records (get_entity detail, search_entities, run_research_query hearings_by_committee), the get_hearing_bundle meeting row and the get_transcript inventory now carry captions {advertised, archived, basis}. advertised = published meeting_coverage captions state 'present' (videos.has_caption or a recording track); archived = the meeting's own meetings.transcripts entries with source='captions'; basis = retained_track, advertised_not_archived, else the coverage reason/state (e.g. recording_without_video_record), or coverage_unavailable. Computed in the page SQL (one correlated subquery, no new capture), so the existing 128 KiB row budgeting still covers it. Hosted 0.6.4 readback of the same expression over all 18,692 meetings of release 63016450: retained_track 705, advertised_not_archived 308, recording_without_video_record 3, recording_link_pending 8,291, unknown 9,385; it costs no measurable time beside a plain 200-row page. The audit's 195 is lower than the 308 measured over every meeting; the 705 retained tracks equal the reader's event-scope caption sources exactly. Tool descriptions for get_entity, get_hearing_bundle and get_transcript and HEARING_RESEARCH.md name the field.
