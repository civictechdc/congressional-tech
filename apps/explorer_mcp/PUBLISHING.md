# Releasing Congress Explorer MCP

The runtime, data publication and website are separate releases. The package
contains code and documentation; it never bundles a congressional dataset.

## Package and website

1. Update `__version__` in `src/congressional_explorer_mcp/__init__.py` and both
   version fields in `server.json`. Update versioned commands and download URLs
   in the README and `skills/explore-congress/SKILL.md`.
   Run `python3 apps/explorer_mcp/scripts/build_desktop.py` from the repo root to
   refresh the generated client manifests and marketplace catalogs.
   The website reads its release version directly from `server.json`.
2. Run the app's existing test runner, build with `uv build apps/explorer_mcp`,
   and run `scripts/check_distribution.py` against the wheel. The check installs
   into a temporary tool environment outside the checkout and tests preparation,
   both configuration formats, MCP discovery and a real row read. Also build the
   desktop archives with `scripts/build_desktop.py --check --output-dir dist` and
   run `scripts/check_desktop.py dist --wheel dist/PACKAGE.whl` with the app's Python.
   The optional wheel supplies the unpublished version through uv's local package
   search path; omitting it tests the actual PyPI release. The check unpacks both
   archives outside the checkout, launches all three client configurations, checks
   discovery before download, prepares a fixture on the first query, and verifies
   reuse without a reachable publication on restart.
3. Push a `congress-mcp-vVERSION` tag from the verified release branch.
   `publish-congress-mcp.yml` tests the app, builds the distributions, validates
   the manifests, and checks the wheel and desktop archives on Linux and macOS.
   It then publishes to PyPI, verifies a fresh PyPI installation and all three
   client launch configurations, and creates the GitHub release downloads.
4. Merge the website updates to main only after that workflow passes. The site
   advertises the same PyPI version as the `.mcpb` and `.plugin.zip`. A main push
   deploys the site automatically, so publishing first avoids broken install links.

The publishing workflow also supports a manual dispatch with an existing tag.
It never overwrites an existing GitHub release's assets.

## PyPI setup

Trusted publishing is configured for this repository. To recreate it, an account
owner configures a publisher at <https://pypi.org/manage/account/publishing/>:

| Field | Value |
|---|---|
| Project | `congressional-explorer-mcp` |
| Owner | `civictechdc` |
| Repository | `congressional-tech` |
| Workflow | `publish-congress-mcp.yml` |
| Environment | `pypi` |

Tag pushes publish automatically. A manual **Publish Congress MCP** dispatch
takes the existing release tag. GitHub supplies a short-lived publishing credential;
no API token is required. Retries reuse existing GitHub distributions when available
and skip already uploaded PyPI files. A fresh PyPI install and client launch checks
must pass before GitHub download links are published.

## MCP Registry

`server.json` describes the PyPI package and its stdio launch. The README contains
the matching `mcp-name` ownership marker. The package also provides the matching
`congressional-explorer-mcp` executable for registry clients using uvx.

After PyPI publication, use the official `mcp-publisher` CLI, authenticate with a
GitHub identity authorized for `civictechdc`, and publish from this directory.
The registry launch prepares missing data on the first tool call. Follow
the [registry publishing guide](https://modelcontextprotocol.io/registry/quickstart).
Do not describe a prepared manifest as a published registry listing.

## Client support

Generated JSON is consumed through the actual FastMCP stdio client in the test
suite. Generated Codex TOML is parsed and compared with that same launch command.
Desktop application checks are recorded separately in `VERIFICATION.md`; protocol
tests do not establish that every desktop application's setup UI has been tested.

## Desktop packages and directories

The `.mcpb` uses MCPB 0.4's host-managed uv runtime, a tiny Python entry point,
and a generated `pyproject.toml` that pins the PyPI package. The plugin ZIP contains
OpenAI and Claude manifests plus the research skill; both manifests launch the
same pinned package through `uvx`. Plugin users install uv on the host. Neither
archive contains the server source, a virtual environment, or a dataset.
Release assets are unsigned; the platform's install
confirmation and any unsigned-package notice still apply.

The repo's `.claude-plugin/marketplace.json` serves Claude Code, and
`.agents/plugins/marketplace.json` serves ChatGPT/Codex. Both point to
`apps/explorer_mcp`. The ZIP can also be uploaded in Claude Cowork's plugin UI.
The OpenAI public directory requires a separately approved local-MCP submission;
publishing GitHub assets does not create either vendor's directory listing.

Official packaging references:
- [Claude MCPB](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md)
- [Claude plugins](https://code.claude.com/docs/en/plugins-reference)
- [OpenAI plugins](https://developers.openai.com/plugins/build/plugins)
- [OpenAI desktop-only submission](https://developers.openai.com/plugins/deploy/desktop-only)
