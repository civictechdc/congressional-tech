---
id: ct-ofex
status: closed
deps: []
links: [ct-m104]
created: 2026-11-05T23:51:58Z
type: bug
priority: 1
tags: [mcp, mcp-research-20261105, mcp-proposal-008, interface-hardening]
---
# Return actionable SQL errors from Congress MCP

The proposal reports a generic `INVALID_ARGUMENT` response from SQL calls. The local worker already forwards exception text. Reproduce the reported behavior on the applicable MCP transport and identify where the details are lost.

## Acceptance Criteria

- Check malformed SQL, an unknown column or table, and bad or missing parameters through standard I/O and the hosted tool path. Record the release, transport, request shape, and returned error for each case.
- Return a bounded, useful message for parser, binder, and parameter errors on the affected path. Include the offending identifier, location, or expected parameter when safe. Keep internal paths and secrets out of responses.
- Verify the same diagnostic cases after the repair and exercise successful parameterized SQL, read-only enforcement, and the existing timeout and memory limits. If the current paths already pass, retain the reproduction evidence and identify the affected client or version before changing code.


## Notes

**2026-11-06T15:44:57Z**

Closed as investigated: retained ordinary hosted connector/HTTP 0.6.1 e145 and current stdio/HTTP parser, binder, unknown table/column, missing/bad parameters, read-only refusal and parameterized success cases return actionable bounded diagnostics. The reported generic INVALID_ARGUMENT was not reproduced and its affected client/version remains unidentified; no speculative SQL rewrite was made. Independent AST comparison confirms the relevant current query and forwarding paths are unchanged. Final deployed 0.6.2 readback stays with ct-m104. [Independent acceptance assessment](../.cache/archive-release/mcp-research-20261106/reviews/greybeard-final/resume-20261106/ASSESSMENT.md) [Fresh installed-wheel acceptance](../.cache/archive-release/mcp-research-20261106/release/resume-20261106/HANDOFF.md)
