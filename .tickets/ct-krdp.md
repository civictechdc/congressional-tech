---
id: ct-krdp
status: closed
deps: []
links: [ct-m704, ct-28tj, ct-m104]
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


## Notes

**2026-11-06T15:44:57Z**

Closed implementation acceptance at reviewed source cffa18e06fa299a7dde1277b961fb1942710202a: mixed metadata/text requests retain input order, independent paging/errors, missing/stale-reference refusals and unchanged single-document identity checks. Batches of 1/4/10 exercise aggregate bytes/work/time bounds with sequential payload lifetime; retained 4 MiB body evidence peaked at 0.37 GiB RSS. Current full app lane and fresh installed 0.6.2 stdio acceptance passed. Final same-release deployment readback stays with ct-m104. [Independent acceptance assessment](../.cache/archive-release/mcp-research-20261106/reviews/greybeard-final/resume-20261106/ASSESSMENT.md) [Fresh installed-wheel acceptance](../.cache/archive-release/mcp-research-20261106/release/resume-20261106/HANDOFF.md)
