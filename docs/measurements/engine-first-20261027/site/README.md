# Release reader and site: local evidence

The shared reader and `/archive/` page work against the native hand release and development F0 v3. The live dashboard remains on its existing publication until the switch. This is local mechanism evidence; engine's corrected full F0 and owner device qualification remain outstanding.

Inputs: hand release `00981fd54931766d8699d87c4af58e4d9012f43864dd16f4d89a92697f71e25a`; development F0 `1268f7e959cfee068c98e4e460e50d69822406ca5dd198d13d12f386b705e2af`, 1,241,157 rows. F0 v3 predates the converter's reviewed saved-field/source fixes and must not establish final F0 acceptance.

| Check | Observed result |
| --- | --- |
| Starting full offline lane | 11,381 passed, 33 failed, 3 errors; all 36 supplied baseline identities unchanged |
| Native hand reader | 10 checks pass, including mandatory files, candidate identity, stale pointer, labels, filters and transient retry |
| Native shards | Nonzero detail shard and cross-shard source range pass through the project Python runner |
| Full F0 warm ranges | Different 1,024-row pages and return to page zero pass with a one-byte evictable data cache; dictionaries are not fetched twice |
| Built hand and F0 site | Desktop 1440×1000 and phone profile 390×844 pass, including the browser 404 reload and delayed Back cancellation |
| Full F0 profile | Startup 7.74–7.86 seconds; sampled page-plus-worker maximum 398–408 MB; one measured worker |
| Candidate canary | 39.15 seconds, with real stored body, pointer/cache/Range checks, text search, facets, detail/link/source/recovery ranges and URL state |
| Saved HTML isolation | Opaque sandbox, no opener, blocked subresources, no persistent active Blob link |

The real saved fixture is a 707-byte gzip object whose recorded stored SHA-256 is `cf147300cb3cf8dada5d9d39971c22fc14edd5b99c751f122fe931b04fffd8d9`; it unpacks to 4,186 bytes of `text/vtt`. The fixture origin verifies explicit stored identities and reads approved files only.

Heap estimates are not observed heaps. Packed F0 list accounting is 157,421,015 bytes, with estimated transient peak 197,138,063 bytes and provisional 256 MiB reader admission. Sampled Chromium totals include the page, its own worker and backing storage, at 50 ms intervals; this is a sampled maximum. Node's observed canary peak reached 1.44 GB. Fixed 256/384 MiB Node object-heap trials refused; dropping column references and yielding also refused at 384 MiB. That intervention and the unadmitted cap proposal were withdrawn. No memory improvement or real-phone budget is claimed. Contended deadline/preflight failures remain in scratch, alongside passing isolated retries.

## Reproduce and hand off

From the repository root, set `F0`, `HAND`, `BODIES`, `SAVED_ROW`, `PLAYWRIGHT_MODULES`, `CHROME` and a fresh `EVIDENCE` directory to the approved artifacts/tools. `BODIES` maps each physical key to `{path, stored_sha256, stored_bytes}`. The approved v3 sample uses row `1002212`.

```sh
PUBLIC_ARCHIVE_RAW_BASE_URL=/ npm --prefix apps/site run build --workspaces=false
ARCHIVE_F0="$F0" npm --prefix apps/site run test:archive-f0 --workspaces=false
npm --prefix apps/site run canary:archive-local --workspaces=false -- --release "$F0" --bodies "$BODIES" --saved-row "$SAVED_ROW" --output "$EVIDENCE/canary.json"
VIEWER_BENCHMARK_MODULES="$PLAYWRIGHT_MODULES" npm --prefix apps/site run contract:archive --workspaces=false -- --release "$F0" --next-release "$HAND" --link-key 0000072476e92cca --browser-executable "$CHROME" --output "$EVIDENCE/browser.json"
```

Run the browser command again with hand/F0 exchanged and `--hand true`. The final corrected F0 requires these same checks; select its actual saved row/link through the native release rather than assuming a row number remains stable.

The owner runs `measure:archive` with `--device-class real-desktop`, and on a real phone with `--device-class real-phone --cdp <endpoint>`. A phone can reach the local origin using `--port 8765 --page http://localhost:8765/congressional-tech/archive/` with owner-managed USB forwarding. Use the same final F0, at least three repeats, and fresh receipt paths. The harness owns only its new page; CDP connection cleanup leaves the owner's existing browser running.

```sh
npm --prefix apps/site run targets:archive --workspaces=false -- --measurements "$PHONE_RECEIPT,$DESKTOP_RECEIPT" --output archive-targets.json --startupMs "$STARTUP_MS" --searchMs "$SEARCH_MS" --detailMs "$DETAIL_MS" --heapBytes "$HEAP_BYTES"
```

The ceilings are the owner's decision after those measurements. Both canary and browser contract automatically read `apps/site/archive-targets.json`; it currently records `owner-gated`. Profile receipts cannot create measured targets. Node's different observed heap cost remains part of that gate.

Engine owns CI/publish wiring. After uploading a candidate, run `npm --prefix apps/site run canary:archive --workspaces=false -- --pointer "$ORIGIN/viewer-publications/manifest.json" --release "$CANDIDATE_ID" --raw "$ORIGIN/" --output "$EVIDENCE/uploaded-canary.json"`. HTTPS is mandatory outside explicit loopback fixture mode. The browser contract requires two actual releases for stale-tab verification. No live storage, workflow or origin configuration was changed here; Docker was not used.
