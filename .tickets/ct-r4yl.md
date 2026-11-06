---
id: ct-r4yl
status: closed
deps: []
links: [ct-9xfg, ct-m104]
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


## Notes

**2026-11-06T15:44:57Z**

Closed implementation acceptance at reviewed source cffa18e06fa299a7dde1277b961fb1942710202a: explicit fields/summary preserve identity, release, nulls/evidence and existing default detail; unknown fields, exact lookup, document paging, older schema and response limits passed. The retained real e145 bill 119-hr-1 measurement is 83,734 bytes for detail versus 719 bytes for scalar summary. Native/stdio projection checks and fresh installed 0.6.2 acceptance passed. Final deployed-version readback stays with ct-m104. [Independent acceptance assessment](../.cache/archive-release/mcp-research-20261106/reviews/greybeard-final/resume-20261106/ASSESSMENT.md) [Fresh installed-wheel acceptance](../.cache/archive-release/mcp-research-20261106/release/resume-20261106/HANDOFF.md)
