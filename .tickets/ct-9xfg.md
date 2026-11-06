---
id: ct-9xfg
status: closed
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


## Notes

**2026-11-06T15:44:57Z**

Closed implementation acceptance at reviewed source cffa18e06fa299a7dde1277b961fb1942710202a: status/overview distinguish source updates, observed record bounds, capture and publication time; absent older metadata and incomplete coverage remain explicit. Retained current/incomplete/old-schema controls, focused table lookup and compact overview measurements passed. The full app lane and fresh installed 0.6.2 wheel preserve the 18-tool discovery path. Final selected production data and deployed package readback stay with ct-m104. [Independent acceptance assessment](../.cache/archive-release/mcp-research-20261106/reviews/greybeard-final/resume-20261106/ASSESSMENT.md) [Fresh installed-wheel acceptance](../.cache/archive-release/mcp-research-20261106/release/resume-20261106/HANDOFF.md)
