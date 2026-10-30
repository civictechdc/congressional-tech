---
name: setup
description: Connect Congress Explorer, check its available congressional data, and help the user start researching.
---

# Set up Congress Explorer

Use the Congress Explorer MCP server's `get_dataset_info` tool. On first use,
the server downloads the published metadata snapshot to the user's local cache.
Tell the user this can take a little longer than later queries. It does not
download document bodies. Reopening the client reuses the selected snapshot.

Report the selected release and available tables. Ask what the user wants to
research, or continue their existing congressional question. Discover published
keys and relationships through `get_dataset_info` before joining unfamiliar
tables. Use `query_sql` for read-only joins and aggregates, and fetch returned
document URLs with the client's own reading tools when the question needs text.
State the collection's published limits; missing records do not prove absence.

If the server is unavailable, check whether this is a local desktop session.
This plugin's local server works in ChatGPT/Codex desktop and Claude Code/Cowork
desktop. Claude chat uses the separate `.mcpb` desktop extension. The plugin
requires `uv` on the host's PATH; the `.mcpb` uses the host-managed uv runtime.
Show the user https://docs.astral.sh/uv/getting-started/installation/ if uv is
missing, then have them restart the client. Do not edit other client settings.

For data setup errors, show the actual error. Repeating `get_dataset_info` retries
a failed initial preparation. Do not delete caches or change a selected release
to work around an error. To refresh data at the user's request, run
`uv run --project <installed-plugin-directory> --python 3.12 --locked --no-dev
congress-explorer-mcp prepare`, then restart the connection. Use the same
`CONGRESS_MCP_DATA_DIR` if it was customized. Queries never refresh data silently.
