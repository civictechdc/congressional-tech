---
id: ct-r4yl
status: in_progress
deps: []
links: [ct-9xfg]
created: 2026-11-05T23:51:58Z
type: feature
priority: 1
tags: [mcp, mcp-research-20261105, mcp-proposal-011, interface-hardening]
---
# Support compact entity responses in Congress MCP

`get_entity` returns a record that can contain large nested lists. Add a bounded way to request selected fields or a compact summary while preserving the current detail and document paths.

## Acceptance Criteria

- Let callers request published fields or choose an explicit summary/detail mode. Keep entity identity, the selected release, and the existing default behavior for calls without the new option.
- Describe available fields or modes through existing discovery. Validate unknown fields and document how callers can read omitted details. Preserve nulls and evidence references in requested fields.
- Measure response bytes for a large bill in compact and full modes. Verify exact entity lookup, documents paging, older release schemas, and the response cap.

