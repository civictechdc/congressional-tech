#!/bin/sh
set -eu

# Every replica and cold start selects the same immutable release. Its local
# cache is disposable; the published archive remains the source of truth.
: "${CONGRESS_MCP_PUBLICATION:?An immutable archive manifest URL is required}"
congress-explorer-mcp prepare --publication "$CONGRESS_MCP_PUBLICATION"
exec congress-explorer-mcp serve --transport http --host 0.0.0.0 --port 8080
