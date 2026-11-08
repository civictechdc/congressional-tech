---
name: explore-congress
description: Research congressional hearings, witnesses, bills, members, recordings, and related documents with Congress Explorer, or help connect its hosted or local MCP server.
---

# Explore Congress

This skill can be installed by itself through `npx skills` or included in the
Congress Explorer plugin. A skill-only install provides instructions; it does not
install Python dependencies, register an MCP server, or download congressional data.

If Congress Explorer's MCP tools are available, start with `get_dataset_info`.
The desktop plugin prepares a local metadata cache on first use. The web plugin
queries the hosted server, which may need time to start after being idle; it
does not install software or download a snapshot onto the user's computer.
Both use a selected immutable release. Document bodies are fetched only when
requested with `get_document(section='text')`.

Report the selected release and available tables. Ask what the user wants to
research, or continue their existing congressional question. Discover published
keys and relationships through `get_dataset_info` before joining unfamiliar
tables. Use `query_sql` for read-only joins and aggregates, and call
`get_document` with `section: "text"` (and optional `page`, `offset`, `max_chars`,
or `query`) when the question needs verified text or snippet search inside an
archived document.
State the collection's published limits; missing records do not prove absence.

If its tools are unavailable, use the [setup guide](https://civictechdc.github.io/congressional-tech/mcp/)
to choose the installation for the user's actual client. For a research request,
explain that the server needs connecting before its data can be queried. For a
setup request, follow the guide's current installation commands within the user's
requested scope, preserve other client settings, and check the connection afterward.
Do not assume the installed skill directory contains the plugin or server code.

Choose the plugin for the execution environment. `congress-explorer-web` connects
to `https://congress-explorer-mcp.mdeeb.workers.dev/mcp` without authentication.
For ChatGPT web, open Plugins → Add custom MCP server, use that URL, select
No authentication, and create and install the plugin. A repository marketplace
entry does not register a connection in the user's ChatGPT account.

`congress-explorer` runs locally in ChatGPT/Codex desktop and Claude Code/Cowork
desktop. Claude chat uses the separate `.mcpb` desktop extension. The plugin
requires `uv` on the host's PATH; the `.mcpb` uses the host-managed uv runtime.
Show the user https://docs.astral.sh/uv/getting-started/installation/ if uv is
missing, then have them restart the client. Use local setup commands only for
a local installation. Do not edit other client settings. The plugin format does
not automatically switch transports; use the matching plugin for the session.

For data setup errors, show the actual error. Repeating `get_dataset_info` retries
a failed initial preparation. Do not delete caches or change a selected release
to work around an error. Hosted data is pinned by the service deployment;
local `prepare` commands cannot refresh it. For a hosted `503`, retry after the
server's `Retry-After` delay. To refresh data at the user's request with a full
local plugin installation, run
`uvx --python 3.12 --from congressional-explorer-mcp==0.6.3
congress-explorer-mcp prepare`, then restart the connection. For a manual server
installation, use `congress-explorer-mcp prepare`. Use the same
`CONGRESS_MCP_DATA_DIR` if it was customized. Queries never refresh data silently.
