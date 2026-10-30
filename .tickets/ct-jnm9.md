---
id: ct-jnm9
status: open
deps: [ct-93zs]
links: []
created: 2026-10-30T14:10:03Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, mcp, explorer]
---
# Expose published HTML metadata and its meaning through Congress Explorer MCP

Assistant users need the same document dates, descriptions, classifications, and evidence as site users.

User value: assistants can answer what a document is and when its page changed without guessing from a title or treating a page update as the hearing date.

Evidence: docs/experiments/extruct-metadata-20261030/report.md and summary.json. Full extraction and comparison artifacts are under output/extruct-metadata-20261030/ (local, Git-ignored); preserve portable fixtures and manifests needed for tests rather than relying solely on these local paths.

## Design

Owner: apps/explorer_mcp, reconciling with its current in-progress implementation before editing. Consume one pinned published release; keep extraction and metadata selection upstream. Update schema descriptions and document-detail/evidence output only where the current generic published-column access does not already cover the new data. Add targeted query support when it serves the existing tools, rather than duplicating the schema in a second parser.

Preserve bounded result size, paging, date precision, and missing/partial/conflicting metadata status. Detail retrieval should expose original source pointers and selected content references without dumping the entire raw metadata payload.

## Acceptance Criteria

- Actual-release integration checks retrieve the same description, source type, publication/modification dates, and conflict evidence as the site fixture.
- Dataset/schema information explains the new field meanings and identifies the pinned release.
- Tests cover old releases, absent fields, partial extraction, and large metadata/content without unbounded responses.
- Hearing date remains distinct from page publication/modification in tool output; citations resolve to the selected source reading.
- Existing generic support is reused where sufficient; no extraction logic or independent identity policy is added to MCP.

