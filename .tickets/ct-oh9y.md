---
id: ct-oh9y
status: open
deps: []
links: [ct-t915, ct-gi01, ct-irxg]
created: 2026-11-05T23:51:58Z
type: feature
priority: 1
tags: [mcp, mcp-research-20261105, mcp-proposal-009, interface-hardening]
---
# Separate reported meeting status from verified outcomes

Build on the publisher status and `not_held` correction in [ct-n61r](ct-n61r.md). Researchers need to distinguish a scheduled meeting from evidence that it took place or was canceled.

## Acceptance Criteria

- Expose the publisher-reported status and an independently supported outcome separately through meeting discovery and lookup. Represent held, canceled, and unknown outcomes with the supporting source and reason when known. Retain contradictory publisher observations.
- Use shared producer evidence for the outcome. Keep unsupported scheduled and stale notices unknown. Preserve date-specific scope for rescheduled meetings and show the same meanings in MCP and the site.
- Verify a scheduled-only meeting, a documented sitting, a supported cancellation, and conflicting or rescheduled evidence against their sources. Check that older releases surface unavailable outcome evidence and preserve their publisher status.

