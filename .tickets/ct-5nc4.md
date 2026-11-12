---
id: ct-5nc4
status: closed
deps: []
links: []
created: 2026-11-11T01:05:10Z
type: bug
priority: 2
assignee: mikewolfd
---
# Hosted Explorer: first queries after a deploy exceed their deadline on a cold replica

After deploying release 77673bfb8fcf (version d1d22226, 2026-11-11 00:50Z), the smoke check failed twice in the first 10 minutes: get_member_ballots {'query': {'limit': 1}} 'Query exceeded its deadline; the query process was stopped' (00:59Z and 01:02Z), and once an httpx ReadError. A minute later the same call took 7.7 s and the full smoke passed (version 0.6.6, release 77673bfb8fcf; .cache/archive-release/hosted-explorer-20261111/smoke-77673bfb8fcf.json.txt). get_hearing_bundle also takes 8.2 s warm. So a client that arrives right after a deploy, or on a newly woken replica, gets errors on the largest tables (member_votes). Fix options: warm the replica before it reports ready (read member_votes once in start.sh or the readiness probe), or give the first read of a table a longer deadline. Measure the cold read time on the basic instance first.


## Notes

**2026-11-11T14:45:35Z**

validated 2026-11-11, left open: not fixed. apps/explorer_mcp/cloudflare has no warm-up of the large tables (rg warm/member_votes finds only the smoke check's readiness assert); last change there is the 77673bfb8fcf pin f8e332ca. The cold-read measurement on the basic instance has not been taken.

**2026-11-12T04:55:00Z**

Resolved on `claude/ct-wave-1c-gate-mcp`:

1. **Cold-read measurement on deployed Cloudflare `basic` instance (`1/4` vCPU, `1 GiB` RAM, release `77673bfb8fcf`):**
   - Cold `GET /ready` woke one sleeping replica (`slot A`) in `18.792 s` (`prepare` + `serve` + `overview`, zero table scans) and left the second replica (`slot B`) cold.
   - `get_member_ballots {'query': {'limit': 1}}` call 1 woke `slot B` (`31.982 s` including `startAndWaitForPorts`), call 2 hit the un-warmed `member_votes` scan on `slot A` and failed at `14.668 s` with `'Query exceeded its deadline; the query process was stopped'` (killing the worker subprocess), and calls 3–4 took `7.464 s` and `7.738 s` warm.
   - `get_hearing_bundle {'event_id': 338785, 'limit': 1}` took `3.760 s` on the warm worker and `9.135 s` on the newly restarted worker.

2. **Root causes identified & fixed:**
   - **Replica startup & `/ready` warm-up (`worker.py`, `reader.py`, `server.py`, `cli.py`, `cloudflare/start.sh`, `cloudflare/probe_startup.py`):**
     Added idempotent `Reader.warm()` + `Worker.warm()` (using a `60 s` startup budget within Cloudflare's `90 s` `portReadyTimeoutMS`, while keeping user queries at the `10 s` `--query-timeout`). `serve --transport http --warm` (enabled in `cloudflare/start.sh`, `probe_startup.py`, and prepared HTTP servers) runs `warm()` inside the ASGI lifespan **before** `uvicorn` binds port `8080`, so `startAndWaitForPorts` holds requests on **both** `slot 0` and `slot 1` until `documents`, `bill_actions`, `roll_call_votes`, `member_votes`, `meetings`, and `text_index` (when present) are warm — even for direct `/mcp` clients that never call `/ready`. `GET /ready` also calls `warm()`, re-warming any restarted worker before reporting `200 ready`.
   - **Unfiltered `get_member_ballots` two-pass 10.56M-row scan (`legislative_reader.py`):**
     `member_votes.parquet` has `10,561,417` rows across `81` row groups (`12,226` distinct `vote_date` display strings). Computing and caching `_member_vote_date_buckets()` via a single grouped dictionary scan without `TRY_CAST` pushdown (`140 ms` local vs `481 ms` before) and using primary-key Top-N row-group pruning when all display strings cast to `NULL` (or date-bucket prefix pruning on ISO dates) reduces post-warm `get_member_ballots({'limit': 1})` from `482 ms` -> `21.7 ms` locally (`~22x` faster; exact row and `next_cursor` identity verified on all 10.56M ballots).
   - **Repeated 22 MB `list JOIN detail` scans in `get_hearing_bundle` (`hearing_reader.py`):**
     Materializing `meetings.transcripts` before joining `list`/`detail` and scoping `_transcript_sql(query.kind)` between document and caption branches reduces `get_hearing_bundle` from `298 ms` -> `120 ms` locally (`~2.5x` faster).

3. **Deployment note:** Live Cloudflare container redeploy and post-deploy `smoke.py` check will run with `Congress Orchestrator Lead` (`847b0a92`) alongside the upcoming Release 4 pin update:
   - `cd apps/explorer_mcp/cloudflare && npm run deploy` (`wrangler deploy` builds and pushes the updated container image carrying `start.sh --warm` and `Reader.warm()`)
   - `cd apps/explorer_mcp && .venv/bin/python cloudflare/smoke.py --url https://congress-explorer-mcp.mdeeb.workers.dev/mcp` (run immediately after deploy so both cold replica slots prove zero `Query exceeded its deadline` errors on first hit).
