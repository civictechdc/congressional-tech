---
id: ct-4kuo
status: open
deps: [ct-9s7b]
links: []
created: 2026-11-05T23:51:57Z
type: feature
priority: 0
tags: [mcp, mcp-research-20261105, mcp-proposal-002, transcript-reliability]
---
# Read hearing transcript and caption text by event in Congress MCP

Researchers can read a known document through `get_document(section='text')`. Add event-based access to the official transcript, committee transcript, and complete caption sources already discoverable from a meeting. Reuse the verified body reader in [ct-o7t4](ct-o7t4.md) and the meeting inventory in [ct-9s7b](ct-9s7b.md).

## Acceptance Criteria

- Expose `get_transcript(event_id, kind?, offset?, limit?)`. Identify available sources by kind, provenance, and stable reference. Let callers select a specific source when several match.
- Return page or text windows for official and committee transcripts and timestamped cues for complete caption tracks. Return paging information and enough source detail to reopen the same text. Resolve retained files and supported playlists on the server.
- Keep body verification, archive access limits, and bounded responses. Report partial or unavailable material explicitly. Exercise a transcript-only hearing, a caption-only hearing, multiple sources, and an incomplete track through the MCP tool.

