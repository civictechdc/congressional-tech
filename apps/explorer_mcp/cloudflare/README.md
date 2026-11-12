# Congress Explorer on Cloudflare

**MCP URL:** `https://congress-explorer-mcp.mdeeb.workers.dev/mcp`

**Authentication:** None.

[Deployment and verification record](../../../docs/measurements/congress-mcp-cloudflare-20261105.md).
[Version 0.6.1 release verification](../../../docs/measurements/congress-mcp-0.6.1-20261105.md).

The Worker exposes `/mcp` over HTTPS and forwards requests to the existing
Python FastMCP and DuckDB server in Cloudflare Containers. A browser MCP client
needs only the URL. The server offers the same declared read-only tools as the local
installation. This uses Cloudflare's supported Containers integration, without
a DuckDB-Wasm rewrite or a tunnel to a developer's computer.

The endpoint is public and requires no authentication. It serves the public
archive only. A client sends tool arguments to Cloudflare; its AI provider also
receives tool results. Logs retain request and runtime diagnostics.

## Resources and behavior

- Two `basic` containers at most: 1 GiB memory and 1/4 vCPU each. Requests choose
  either replica; stateless HTTP does not require session affinity.
- Containers stop after five idle minutes. Their disposable disks hold metadata,
  the release's SQLite text index, up to 128 MiB of extracted document text, and
  up to 512 MiB of DuckDB scratch space. Capacity must include the image and reserve.
- Each fresh container downloads and verifies the immutable release in
  `wrangler.jsonc` and warms the DuckDB query worker and large Parquet tables
  (`member_votes`, `bill_actions`, `roll_call_votes`, `documents`, `meetings`)
  before opening its HTTP listener or reporting ready. Readiness allows up to
  90 seconds; cold connections are slower than warm connections. Clients should
  retry a temporary `503` using its `Retry-After` header.
- The gateway accepts at most 64 KiB per request. Cloudflare rate limiting allows
  approximately 60 requests per minute per client IP at each Cloudflare location.
  This is not a global quota; clients behind one proxy share an IP limit.
- The existing query process retains its 10-second query timeout, 512 MiB DuckDB
  memory limit, read-only file access, output limits, and bounded queue. Startup
  and `/ready` warm-up use a 60-second startup budget within the container's
  90-second port readiness allowance.
- Containers are usage-billed under the existing paid Cloudflare account.
  Instance count and idle shutdown bound resource use, not a monthly spend cap.
  See [Container pricing](https://developers.cloudflare.com/containers/platform/pricing/).

The root URL describes the service and configured publication. `GET /ready`
opens and warms the selected worker, large Parquet tables, and text index, then
reports its software version and exact release ID. A starting or unusable
instance returns `503`. `smoke.py` checks readiness, actual MCP initialization
and data reads.

## Build and deploy

Use Node.js 22 and a running Docker daemon that can build `linux/amd64` images.
From this directory:

```sh
npm ci --workspaces=false
npm run types
npm run typecheck
npm test
npx wrangler whoami
npx wrangler deploy --dry-run --outdir dist
npm run deploy
```

`account_id` identifies the existing congressional-data Cloudflare account.
Wrangler uses an existing login or a scoped deployment credential; no credentials
are stored in this directory. On a fresh machine, run `npx wrangler login` first.
The Docker image builds from `apps/explorer_mcp`, uses its exact `uv.lock`, and
runs as an unprivileged user. Its base image is pinned by digest.

Wrangler prints the HTTPS Worker URL. Append `/mcp` when registering the server
in a remote MCP client. For ChatGPT, use its custom remote MCP/app configuration
with authentication set to **None**, subject to your account's available features
and workspace policy. This deployment does not register or publish an app in an
OpenAI directory.

Deployment may make the Worker live before the container image finishes rolling
out. Wait for `npx wrangler containers list --json` to show the application active,
then run this check from the repository root with the URL and the full release ID
from `wrangler.jsonc`:

```sh
uv sync --locked --project apps/explorer_mcp
apps/explorer_mcp/.venv/bin/python apps/explorer_mcp/cloudflare/smoke.py \
  https://YOUR-WORKER.workers.dev/mcp --release-id FULL_RELEASE_ID
```

The check compares the tool list with the package's `TOOL_NAMES`, exercises
available research paths, confirms the selected release, checks useful SQL errors,
rejects a write, and reads through two concurrent clients. Older fixtures retain
explicit unavailable results. For final release qualification, add
`--probe-plan plan.json --require-research`: the plan supplies retained `event_id`,
`document_reference` and `search_text`; real cue, page and search citations must reopen.
Use that same plan for the installed CLI and desktop package checks.
The `Validate Congress MCP` workflow checks the gateway, generated types, image
build, and the Python tests; it does not automatically deploy.

## Local checks

`npm run dev` runs the Worker and container integration locally. Use its printed
URL with `smoke.py`. The container downloads the public pinned release, so this
integration check requires network access. The Python HTTP regression tests use
local fixtures and compare the declared tools with the in-process server.

Before changing instance size or the 90-second startup allowance, measure the
actual candidate with `probe_startup.py` under the archive watchdog. It uses a
new durable data directory, runs the normal streamed-and-hashed `prepare`, waits
for `/ready`, and performs the HTTP smoke check. Its receipt distinguishes the
local source runtime from the actual hosted image; measure that image separately.
For example, from the repository root:

```sh
python3 scripts/archive_watchdog.py --rss-gb 2 --expect-gb 0.4 \
  --start-available-gb 6 --interval 0.2 --report DURABLE_WORK/startup-watchdog.json -- \
  apps/explorer_mcp/.venv/bin/python apps/explorer_mcp/cloudflare/probe_startup.py \
  --publication IMMUTABLE_MANIFEST --work DURABLE_WORK/fresh-start \
  --probe-plan plan.json --require-research
```

`probe_capacity.py` checks manifest asset bytes plus measured image bytes, the
body cache, query scratch and reserve against explicit disk, RSS and startup
limits. Supply byte values from the built image and its measured process tree;
a small fixture or an estimated index size does not qualify a hosted instance.

For the complete Python suite, run from the repository root through the checkout's
documented watchdog and test runner:

```sh
python3 scripts/archive_watchdog.py --rss-gb 2 --expect-gb 0.9 \
  --start-available-gb 6 --interval 0.2 -- \
  apps/explorer_mcp/.venv/bin/python scripts/dev.py test explorer-mcp -- -q
```

## Archive and software updates

Change `PUBLICATION` to a verified immutable release manifest, run `npm run types`,
and redeploy. Do not set it to the moving `viewer-publications/manifest.json`
pointer: document references must resolve to the same release across replicas.
Container names include the publication URL so an existing replica cannot serve
the previous release under the new configuration. The two-instance cap can cause
temporary `503` responses until old replicas sleep or the rollout replaces them.

The data is not refreshed by a tool call. Software updates build from this checkout
and its pinned dependencies; they do not depend on the PyPI release. To reverse
an update, restore the previous source, dependency pins, and publication URL, then
redeploy and run the same smoke check. No archive data is mutated by deployment.

See [Cloudflare's deployment guide](https://developers.cloudflare.com/containers/guides/deploy/)
for image rollout details and `npx wrangler tail` for live diagnostics.
