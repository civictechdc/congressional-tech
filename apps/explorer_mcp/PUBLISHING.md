# Releasing Congress Explorer MCP

The runtime, data publication and website are separate releases. The package
contains code and documentation; it never bundles a congressional dataset.

## Package and website

1. Update `__version__` in `src/congressional_explorer_mcp/__init__.py` and both
   version fields in `server.json`. Update the README's versioned download URL.
   The website reads its release version directly from `server.json`.
2. Run the app's existing test runner, build with `uv build apps/explorer_mcp`,
   and run `scripts/check_distribution.py` against the wheel. The check installs
   into a temporary tool environment outside the checkout and tests preparation,
   both configuration formats, MCP discovery and a real row read.
3. Push a `congress-mcp-vVERSION` tag. `publish-congress-mcp.yml` tests the app,
   builds the wheel and source distribution, checks package metadata, and verifies
   the wheel on Linux and macOS before creating GitHub release downloads.
4. Deploy the site only after the release download exists. It advertises that
   exact GitHub wheel, so onboarding remains usable without a PyPI account.

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
long-lived token belongs in the repository. Once PyPI returns the new release,
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

An optional Claude Desktop `.mcpb` installer is a later distribution option. The
versioned wheel is the common installation path for this release.
