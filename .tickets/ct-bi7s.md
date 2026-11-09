---
id: ct-bi7s
status: open
deps: []
links: []
created: 2026-11-09T15:50:38Z
type: feature
priority: 3
assignee: mikewolfd
---
# Seek the first spoken caption cue when a transcript page opens on silent segments


From the 2026-11-09 hosted MCP audit (release 63016450…, server 0.6.4): the first few get_transcript pages for hearing 338785 returned empty rows with has_more: true because the playlist opens with segments that carry no spoken captions. Correct, but the client must keep paginating blind. Proposal: when a page would be empty and has_more is true, continue to the first segment with cues and return it, with the skipped segment range stated in the response, so one call lands on text. Keep explicit cursors working as today. Tags: mcp, mcp-audit-20261109.
