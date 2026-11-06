---
id: ct-irxg
status: open
deps: [ct-4kuo, ct-j78x]
links: [ct-oh9y]
created: 2026-11-05T23:51:57Z
type: feature
priority: 0
tags: [mcp, mcp-research-20261105, mcp-proposal-003, transcript-reliability]
---
# Return a hearing dossier in one Congress MCP call

Add a research-friendly tool over the published `hearing_dossier` recipe from [ct-adoh](ct-adoh.md). The recipe and [ct-j78x](ct-j78x.md) own the existing joins and supported recording associations.

## Acceptance Criteria

- Expose `get_hearing_bundle(event_id, include?)`. Return the meeting, committees, current witnesses, prepared testimony, official and committee transcripts, captions, recording observations, and coverage in one bounded response. Optional includes and paging references let callers narrow or continue large sections.
- Use the transcript references from [ct-4kuo](ct-4kuo.md), the existing current-witness rule from [ct-9479](ct-9479.md), and the shared recording associations. Preserve event versus package scope and distinguish official transcripts, committee transcripts, captions, and prepared testimony.
- Return coverage states for the requested sections and preserve source references. Exercise a hearing with several material kinds, a hearing with sparse evidence, and the package-scoped recording for event `334136` against the selected release.

