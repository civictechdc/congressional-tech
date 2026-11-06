---
id: ct-hnpc
status: in_progress
deps: [ct-6r1i]
links: [ct-9xfg, ct-nozw]
created: 2026-11-05T23:51:57Z
type: feature
priority: 0
tags: [mcp, mcp-research-20261105, mcp-proposal-005, legislative-activity]
---
# Add a dated legislative activity feed to Congress MCP

Let researchers ask what happened in a week without writing SQL. Build on the published legislative events from [ct-6r1i](ct-6r1i.md) and other supported event sources.

## Acceptance Criteria

- Expose `get_activity(since, until?, chamber?, committee?, topic?, limit?)`. Define date-window boundaries, supported event types, filter meanings, deterministic ordering, and paging.
- Return the event date or timestamp with its precision, type, subject, source reference, and applicable coverage limits. Derive committee and topic matches from supported published associations.
- Exercise a representative week across supported event types, a filtered week, a valid empty interval, and an interval with unavailable coverage. Compare sampled events with their source rows and retain distinct events that share a date.

