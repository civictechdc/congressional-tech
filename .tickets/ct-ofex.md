---
id: ct-ofex
status: open
deps: []
links: []
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

