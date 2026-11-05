# Congress Explorer MCP 0.6.1 — November 5, 2026

Version **0.6.1** is published on GitHub and PyPI and deployed at
`https://congress-explorer-mcp.mdeeb.workers.dev/mcp`. Live MCP queries verified
the latest published archive, containing **356,735 documents**.

The archive pointer was last updated at **15:12:15 UTC on November 5, 2026**.
It selects `e145d24c389e43e05a0bcb3f71cd1f75ee919a066dfa810f0ba39a16283d4a99`.
The hosted service was already pinned to this release before the update. This
patch retains that selection and redeploys the software; it does not add records
or recompute the archive. The release manifest's file list passed the MCP
release-identity checks: 26 files, 101,654,759 bytes.

## What changed

- Updated the Python package, desktop extension, local plugin, web plugin, and
  installation commands to 0.6.1.
- Added the Congress Explorer package version to the MCP connection response.
  Deployment checks now verify the running software version as well as the data
  release, including a second concurrent client.
- Retained the existing local-cache behavior: an installed desktop server keeps
  its selected data until the user runs `prepare`. A software upgrade alone does
  not replace an existing local snapshot.

## Deployed state

| Item | Verified value |
|---|---|
| Source commit | `52d47d08b52a474716074d332dc89543d949edba` |
| Release tag | `congress-mcp-v0.6.1` |
| Worker version | `e575c637-ef11-4935-b772-6fa8ce9e4d05` |
| Container application | `a035cdc3-0956-4091-bba9-33050b1ceb04` |
| Container application version | `3` |
| Image digest | `sha256:bcfb8c3054b015bad98599f83774688cb3be69e66bb70edccbf76bd95d18a0f1` |
| Replica state | Both instances running version 3; no application health errors |
| Live MCP software version | `0.6.1` |
| Live MCP archive release | `e145d24c389e43e05a0bcb3f71cd1f75ee919a066dfa810f0ba39a16283d4a99` |

## Verification

- The full `explorer-mcp` lane exited 0: **128 passed, 2 skipped**. The two
  native-producer fixture tests were not run for this software release; the
  archive and producer code did not change. HTTP and stdio checks both verify
  the reported package version.
- Worker types regenerated without a diff. TypeScript checks, all six gateway
  tests, and Wrangler's Linux container build and deployment dry run passed.
- The public HTTPS endpoint passed all six MCP tools, read-only SQL rejection,
  and concurrent-client checks. Four additional connections each reported
  software 0.6.1 and the expected archive release. Both replicas subsequently
  reported application version 3.
- Desktop packages launched successfully outside the checkout on macOS.
  [Release workflow 42085471793](https://github.com/civictechdc/congressional-tech/actions/runs/42085471793)
  passed Linux and macOS installation checks, fresh PyPI installation, and all
  desktop configurations against the published PyPI package.
- The website build passed with version 0.6.1 download links. The dedicated
  `congress-mcp` Colima profile was stopped after deployment.

[Release downloads](https://github.com/civictechdc/congressional-tech/releases/tag/congress-mcp-v0.6.1)
and [PyPI package](https://pypi.org/project/congressional-explorer-mcp/0.6.1/).
Retained commands, manifests, logs, package metadata, and verification results
are under `.cache/archive-release/investigations/mcp-0.6.1-20261105/`.

