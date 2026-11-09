---
id: ct-9u0h
status: closed
deps: []
links: []
created: 2026-11-09T15:50:38Z
type: bug
priority: 3
assignee: mikewolfd
---
# Check that hosted MCP error text survives the claude.ai connector


From the 2026-11-09 hosted MCP audit: through the auditor's connector, invalid SQL and the oversized schema selector both arrive as a bare INVALID_ARGUMENT, while the hosted server itself returns bounded, specific text (verified 2026-11-09 by direct JSON-RPC: 'Published control exceeds 128 KiB; use a table, relationship, or recipe selector', and pydantic validation detail for bad arguments). ct-ofex found the same non-reproduction on direct transports. Task: identify which connector path drops isError text, and whether returning errors as a structured result (not isError) keeps them visible there. Related: ct-ofex. Tags: mcp, mcp-audit-20261109.

## Notes

**2026-11-09T16:35:41Z**

2026-11-09 (branch claude/ct-thread3-mcp-polish): investigated in code and against hosted 0.6.4 (release 63016450, direct JSON-RPC over HTTP, UA ct-mcp-polish/1). One error path only: FastMCP 4.1.4 turns ToolError (reader errors), pydantic validation and unknown tools into result{isError:true, content:[one text block]}, no structuredContent, never a JSON-RPC error object (fastmcp/server/mixins/mcp_operations.py call_tool handler). Text arrives intact for invalid SQL, unknown column, table=schema (128 KiB control), extra argument and boolean event_id under protocol versions 2024-11-05, 2025-03-26, 2025-06-18 and 2025-11-25 (2026-07-28 negotiates 2025-11-25). Claude Code's stdio client showed a local install's isError text verbatim; the Python MCP 2.3.0 and FastMCP clients skip output-schema validation on isError results. The bare INVALID_ARGUMENT is therefore produced by the claude.ai connector from isError results, discarding their text; I cannot reach that connector from here. A structured non-error result would pass such a connector, but every client would read failures as successes, so no server change was made; owner decision. Deciding test: in claude.ai call get_dataset_info(table='schema') and record what the model receives. Details: apps/explorer_mcp/VERIFICATION.md.

**2026-11-09T17:52:45Z**

2026-11-09 owner decision: keep errors as error results; closed as connector-side. Server (FastMCP 4.1.4) and every tested client keep the full error text on the wire under all negotiated protocol versions; only the claude.ai connector flattens isError results to INVALID_ARGUMENT. Returning failures as structured non-error results was rejected because every other client would then read failures as successes. Evidence in apps/explorer_mcp/VERIFICATION.md (0.6.5 section).
