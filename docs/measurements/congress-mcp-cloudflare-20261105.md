# Congress Explorer Cloudflare deployment — November 5, 2026

The public Streamable HTTP endpoint is
`https://congress-explorer-mcp.mdeeb.workers.dev/mcp`. It requires no authentication.
A Cloudflare Worker forwards to the existing Python FastMCP/DuckDB application
in Cloudflare Containers. Browser clients need no local server or desktop install.

## Deployed state

| Item | Verified value |
|---|---|
| Worker | `congress-explorer-mcp` |
| Worker version | `dc69f880-abf3-4af5-8213-23480efda995` |
| Container application | `a035cdc3-0956-4091-bba9-33050b1ceb04` |
| Container image digest | `sha256:20c71d8ce56c76f25756a4f631220afc48202a4f49e5d32553c98828281e6683` |
| Archive release | `e145d24c389e43e05a0bcb3f71cd1f75ee919a066dfa810f0ba39a16283d4a99` |
| Resources | At most two `basic` containers, each 1 GiB memory, 1/4 vCPU and 4 GB disk |
| Idle shutdown | Five minutes |
| Rollout result | Deployment exited 0; both version 1 instances running; application reported no health errors |

The immutable archive URL is pinned in `apps/explorer_mcp/cloudflare/wrangler.jsonc`.
Container names include that URL. New document references therefore remain tied
to the same release even when requests reach different replicas.

## Verification

- The full `explorer-mcp` lane exited 0: **127 passed, 2 skipped**. The two skipped
  tests require separately produced native fixtures; native producer qualification
  was not rerun for this hosting change. HTTP regressions compare all six tools
  with local results and exercise two clients without a server session ID.
- Worker TypeScript checking and all **six gateway tests** passed. Wrangler's
  dry run built the Linux container and bundled the Worker successfully.
- All six tools passed through both `wrangler dev` and the public HTTPS endpoint,
  using the locked FastMCP client. Both checks confirmed the pinned release,
  counted **356,735 visible documents**, rejected `DROP VIEW`, and successfully
  read through two concurrent clients.
- Public gateway checks returned `204` for a ChatGPT-origin preflight, `403` for
  an unapproved origin, and `413` for a 65,537-byte request.
- A local Linux/amd64 container restricted to 1 GiB and 1/4 vCPU used a peak of
  **344,150,016 bytes (328.2 MiB)** in its cgroup during the six-tool check.
  Startup from an empty data directory to HTTP readiness took **23.9 seconds**.
  This ran through amd64 emulation on Apple Silicon; it is a local capacity check,
  not a production latency guarantee or a load test.

The remote smoke check measured 7.288 seconds for initial dataset discovery,
3.036 seconds for document search, and 0.223–0.609 seconds for the remaining
four tool calls. These are individual observations, including initialization
work where applicable, not latency percentiles.

The full suite initially exposed stale synthetic fixtures for the newly published
`witness_key_map` table and `witness_by_any_key` recipe. The fixtures now include
that table and check both a current key and an earlier key. No producer code or
published archive files were changed.

Retained local evidence lives in
`.cache/archive-release/investigations/mcp-cloudflare-20261105/`: deployment log,
Worker/container identifiers, watchdog reports, complete test output, Docker
resource measurements, local and remote six-tool results, and gateway checks.
The dedicated local Colima profile was stopped after deployment.

For deployment, update, retry, and client setup instructions, see
[`apps/explorer_mcp/cloudflare/README.md`](../../apps/explorer_mcp/cloudflare/README.md).
The endpoint has been verified with an MCP client; registering it in a user's
ChatGPT account remains a client setup step. This does not publish a directory app.

## Separate web and desktop plugin configurations

The plugin update adds `congress-explorer-web` with a single Streamable HTTP
connection to the deployed Worker. `congress-explorer` retains its existing
local stdio launch commands and desktop-only metadata. The documented portable
format specifies one transport per server and provides no browser/desktop
selector, so the two plugins require explicit selection rather than an automatic
fallback. See the [OpenAI packaging guide](https://developers.openai.com/plugins/build/plugins#bundled-mcp-servers-and-lifecycle-hooks).

`server.json` owns the local package pin and the remote URL. The generator copies
the shared skill and assets into the web plugin and verifies them byte-for-byte.
It emits separate local and web ZIPs. The web package used for the live check is
`.cache/archive-release/distributions/congress-mcp-web-20261105/congress-explorer-web-0.5.2.plugin.zip`,
SHA-256 `3f0f2d43f81e28b054b720ac6b57c27e6013ea2522c6a8fffcd3b6aac7f606e6`.

The update passed schema validation for `server.json`, both portable plugin
manifests, and both MCP configurations. The full MCP lane now passes **128 tests**,
with the same two native-fixture skips. All three local desktop launch
configurations passed from extracted archives outside the checkout using the
released PyPI package. A FastMCP client loaded `mcp.json` directly from the web ZIP
and passed all six live tools, write rejection, and concurrent-client checks.
The setup site also built successfully with separate web and desktop instructions.

Evidence: `plugin-schemas.json`, `plugin-tests.log`, `desktop-packages.log`,
`web-package-smoke.json`, and `plugin-site-build.log` in the investigation directory
above. The new web package and repository metadata have not been published to a
plugin directory or installed into the user's ChatGPT account.
