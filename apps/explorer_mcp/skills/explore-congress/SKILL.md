---
name: explore-congress
description: Research congressional hearings, witnesses, bills, members, recordings, and related documents with Congress Explorer, or help connect its local MCP server.
---

# Explore Congress

This skill can be installed by itself through `npx skills` or included in the
Congress Explorer plugin. A skill-only install provides instructions; it does not
install Python dependencies, register an MCP server, or download congressional data.

If Congress Explorer's MCP tools are available, start with `get_dataset_info`. On first use,
the server downloads the published metadata snapshot to the user's local cache.
Tell the user this can take a little longer than later queries. It does not
download document bodies. Reopening the client reuses the selected snapshot.

Report the selected release and available tables. Ask what the user wants to
research, or continue their existing congressional question. Discover published
keys and relationships through `get_dataset_info` before joining unfamiliar
tables. Use `query_sql` for read-only joins and aggregates, and fetch returned
document URLs with the client's own reading tools when the question needs text.
State the collection's published limits; missing records do not prove absence.

If its tools are unavailable, use the [setup guide](https://civictechdc.github.io/congressional-tech/mcp/)
to choose the installation for the user's actual client. For a research request,
explain that the server needs connecting before its data can be queried. For a
setup request, follow the guide's current installation commands within the user's
requested scope, preserve other client settings, and check the connection afterward.
Do not assume the installed skill directory contains the plugin or server code.

Check whether this is a local desktop session.
This plugin's local server works in ChatGPT/Codex desktop and Claude Code/Cowork
desktop. Claude chat uses the separate `.mcpb` desktop extension. The plugin
requires `uv` on the host's PATH; the `.mcpb` uses the host-managed uv runtime.
Show the user https://docs.astral.sh/uv/getting-started/installation/ if uv is
missing, then have them restart the client. Do not edit other client settings.

For data setup errors, show the actual error. Repeating `get_dataset_info` retries
a failed initial preparation. Do not delete caches or change a selected release
to work around an error. To refresh data at the user's request with a full plugin
installation, run
`uvx --python 3.12 --from congressional-explorer-mcp==0.4.0
congress-explorer-mcp prepare`, then restart the connection. For a manual server
installation, use `congress-explorer-mcp prepare`. Use the same
`CONGRESS_MCP_DATA_DIR` if it was customized. Queries never refresh data silently.
