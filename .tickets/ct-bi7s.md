---
id: ct-bi7s
status: closed
deps: []
links: []
created: 2026-11-09T15:50:38Z
type: feature
priority: 3
assignee: mikewolfd
---
# Seek the first spoken caption cue when a transcript page opens on silent segments


From the 2026-11-09 hosted MCP audit (release 63016450…, server 0.6.4): the first few get_transcript pages for hearing 338785 returned empty rows with has_more: true because the playlist opens with segments that carry no spoken captions. Correct, but the client must keep paginating blind. Proposal: when a page would be empty and has_more is true, continue to the first segment with cues and return it, with the skipped segment range stated in the response, so one call lands on text. Keep explicit cursors working as today. Tags: mcp, mcp-audit-20261109.

## Notes

**2026-11-09T16:29:11Z**

2026-11-09 (branch claude/ct-thread3-mcp-polish, unpublished): hosted 0.6.4 reproduction: hearing 338785's playlist (senate:govtaff093026, 728 segments) opens with 107 silent segments that all share ONE body; the raw reader fetched it 107 times and queried the resource map once per segment, so pages 1-3 came back empty at ~4.5 s each and cues began at segment 108 on the 4th call. Fix (both raw and indexed readers): a get_transcript caption read without a cursor whose page is still empty keeps reading past the 32-segment page, up to MAX_SEEK_SEGMENTS=256 segments (raw reader also stops seeking after half the 10 s deadline), and states skipped_segments {first,last}; cursor reads keep 32-segment pages. The raw reader now reads each body once per call and loads the resource map 32 rows at a time. Tests on the hearing_release and source_fixture fixtures: 40 silent segments land on cue segment 41 in one call reading the silent body at most once; 300 silent segments return empty with skipped 1-256, then cursor pages 257-288, 289-300 + cue. Planting MAX_SEEK_SEGMENTS=32 fails the test. Hosted readback after publish: expect one call for 338785 to return ordinal 108 with skipped_segments {1,107}.

**2026-11-09T18:07:39Z**

2026-11-09 hosted readback on 0.6.5 (worker deployed, PyPI and GitHub release published): get_transcript(event_id=338785, source_id=469b3687...) returns in one call skipped_segments {first:1,last:107}, 25 cues starting 00:21:25.317, has_more true. Closed.
