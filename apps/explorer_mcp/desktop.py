"""Shared entry point for desktop bundles and plugins; stdout is MCP only."""
import sys

from congressional_explorer_mcp.cli import main


if __name__ == '__main__':
    raise SystemExit(main(['serve', '--prepare-if-missing', *sys.argv[1:]]))
