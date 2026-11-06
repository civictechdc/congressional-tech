---
id: ct-nozw
status: in_progress
deps: []
links: [ct-hnpc, ct-9xfg, ct-m94a, ct-6r1i]
created: 2026-11-05T23:51:58Z
type: feature
priority: 2
tags: [mcp, mcp-research-20261105, mcp-proposal-015, interface-hardening]
---
# Expose ready-to-run congressional research queries in MCP

Build on the current scalar filters and published relationship recipes. Make recurring research queries callable with named parameters and reuse the activity feed for cross-collection event timelines.

## Acceptance Criteria

- Support recent bills, pending nominations, hearings by committee, and legislation by subject without requiring callers to write SQL. Document filter meaning, date and status fields, supported coverage, and paging.
- Reuse the maintained recipe and query paths. Return canonical IDs, source references, and explicit missingness for each result set. Use published subject associations and status evidence.
- Compare each named query with its underlying release rows. Exercise ambiguous committee or subject input, an empty result, and a collection with unavailable coverage.

