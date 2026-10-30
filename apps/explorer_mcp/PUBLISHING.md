# Releasing Congress Explorer MCP

The runtime, data publication and website are separate releases. The package
contains code and documentation; it never bundles a congressional dataset.

## Package and website

1. Update `__version__` in `src/congressional_explorer_mcp/__init__.py` and both
   version fields in `server.json`. Update the README's versioned download URLs.
   Run `python3 apps/explorer_mcp/scripts/build_desktop.py` from the repo root to
   refresh the generated client manifests and marketplace catalogs.
   The website reads its release version directly from `server.json`.
2. Run the app's existing test runner, build with `uv build apps/explorer_mcp`,
   and run `scripts/check_distribution.py` against the wheel. The check installs
   into a temporary tool environment outside the checkout and tests preparation,
   both configuration formats, MCP discovery and a real row read. Also build the
   desktop archives with `scripts/build_desktop.py --check --output-dir dist` and
   run `scripts/check_desktop.py dist` with the app's Python. It unpacks both
   archives outside the checkout, launches all three client configurations, checks
   discovery before download, prepares a fixture on the first query, and verifies
   reuse without a reachable publication on restart.
3. Push a `congress-mcp-vVERSION` tag. `publish-congress-mcp.yml` tests the app,
   builds the wheel and source distribution, checks package metadata, and verifies
   the wheel and both desktop archives on Linux and macOS before creating GitHub
   release downloads. The pinned MCPB and Claude Code CLIs validate the manifests.
4. Deploy the site only after the release download exists. It advertises that
   exact GitHub wheel, `.mcpb` and `.plugin.zip`, so onboarding remains usable
   without a PyPI account. Keep all three assets on the same release tag.

The publishing workflow also supports a manual dispatch with an existing tag.
It never overwrites an existing GitHub release's assets.

## PyPI setup

An account owner must configure a pending trusted publisher at
<https://pypi.org/manage/account/publishing/> before the first PyPI upload:

| Field | Value |
|---|---|
| Project | `congressional-explorer-mcp` |
| Owner | `civictechdc` |
| Repository | `congressional-tech` |
| Workflow | `publish-congress-mcp.yml` |
| Environment | `pypi` |

Then dispatch **Publish Congress MCP** on main with the release tag and
`publish_pypi: true`. GitHub supplies a short-lived publishing credential. No
long-lived token belongs in the repository. PyPI receives the exact distributions
already published on GitHub, including when a dispatch retries publication.
Once PyPI returns the new release,
verify `uv tool install --python 3.12 congressional-explorer-mcp==VERSION` from
a fresh environment before changing the website's primary install command.

## MCP Registry

`server.json` describes the PyPI package and its stdio launch. The README contains
the matching `mcp-name` ownership marker. The package also provides the matching
`congressional-explorer-mcp` executable for registry clients using uvx.

After PyPI publication, use the official `mcp-publisher` CLI, authenticate with a
GitHub identity authorized for `civictechdc`, and publish from this directory.
Registry setup still requires users to run `prepare` before connecting. Follow
the [registry publishing guide](https://modelcontextprotocol.io/registry/quickstart).
Do not describe a prepared manifest as a published registry listing.

## Client support

Generated JSON is consumed through the actual FastMCP stdio client in the test
suite. Generated Codex TOML is parsed and compared with that same launch command.
Desktop application checks are recorded separately in `VERIFICATION.md`; protocol
tests do not establish that every desktop application's setup UI has been tested.

## Desktop packages and directories

The `.mcpb` uses MCPB 0.4's host-managed uv runtime. The plugin ZIP has portable
OpenAI and Claude manifests around the same source, dependency lock and setup
skill. Plugin users install uv on the host; neither archive contains a virtual
environment or dataset. Release assets are unsigned; the platform's install
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
