---
id: ct-9xfg
status: open
deps: []
links: [ct-hnpc, ct-m104, ct-m94a, ct-nozw, ct-r4yl]
created: 2026-11-05T23:51:57Z
type: feature
priority: 1
tags: [mcp, mcp-research-20261105, mcp-proposal-007-012, legislative-activity, interface-hardening]
---
# Expose collection freshness and a compact Congress MCP overview

`get_dataset_info` already offers focused table, relationship, and recipe selectors. Add concise entry points for capability discovery and source freshness using the same published metadata.

## Acceptance Criteria

- Expose `get_dataset_status()` with the selected release ID and publication date, latest known source update by collection, observed date bounds, coverage gaps, and unavailable values. Keep source updates, archive capture dates, and release publication dates distinct.
- Expose `get_overview()` with a small list of available capabilities and discovery selectors. Preserve focused `get_dataset_info(table=...)` schema lookup and existing relationship and recipe access.
- Verify a current collection, a collection with incomplete history, and a release that lacks source-update metadata. Compare the overview size with the existing unscoped discovery response and exercise a focused schema lookup without loading the full relationship model.

