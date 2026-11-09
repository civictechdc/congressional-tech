---
id: ct-9u0h
status: open
deps: []
links: []
created: 2026-11-09T15:50:38Z
type: bug
priority: 3
assignee: mikewolfd
---
# Check that hosted MCP error text survives the claude.ai connector


From the 2026-11-09 hosted MCP audit: through the auditor's connector, invalid SQL and the oversized schema selector both arrive as a bare INVALID_ARGUMENT, while the hosted server itself returns bounded, specific text (verified 2026-11-09 by direct JSON-RPC: 'Published control exceeds 128 KiB; use a table, relationship, or recipe selector', and pydantic validation detail for bad arguments). ct-ofex found the same non-reproduction on direct transports. Task: identify which connector path drops isError text, and whether returning errors as a structured result (not isError) keeps them visible there. Related: ct-ofex. Tags: mcp, mcp-audit-20261109.
