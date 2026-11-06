---
id: ct-krdp
status: open
deps: []
links: [ct-m704, ct-28tj]
created: 2026-11-05T23:51:58Z
type: feature
priority: 2
tags: [mcp, mcp-research-20261105, mcp-proposal-013, search-retrieval]
---
# Retrieve multiple document references in one Congress MCP call

Let researchers read metadata or text for a set of known document references. Reuse the existing `get_document` identity, verification, and paging paths.

## Acceptance Criteria

- Accept multiple release-bound document references with a metadata or text request for each. Return results in input order with independent paging state and useful per-item errors.
- Preserve the existing reference and body-verification rules. Bound batch size, aggregate response bytes, and work. Give callers a way to continue items that hit the response budget.
- Exercise mixed metadata and text, a missing reference, a stale release reference, and a paged text item in the same request. Compare successful items with their single-document responses.

