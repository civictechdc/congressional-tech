# M1 scratch smoke release

`release/m1-smoke` starts at shared `origin/main` `7411f5b7`. Script implementation `abb3df9d` follows contracts `53179f3a`; eleven project-runner process-fake checks pass. The semi-formal code review approves the source with no open BLOCKER or CONCERN.

The optimized native probe is ready in the immutable shared packet:

```sh
export M1_PROBE=/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-coord/shared/m1-probe-eb3a121/basin_maintenance_probe
export M1_PROBE_SHA256=31d70fcba7013f6914b78bdd1be83eefbde8e0c4d9dfae7262f81f2c98705f0b
```

- Source: docspec-rs `eb3a121a1434b5e4284e5ba1d92f829acdff5e35`, frozen by engine in its own source archive.
- Platform: **darwin-arm64**; size **137,211,008 bytes**. This package qualifies the owner's current Mac artifact; no Linux binary was built here.
- Build: `CARGO_PROFILE_RELEASE_DEBUG=0 cargo +1.94.0 build --locked --offline --release --no-default-features --features remote --example basin_maintenance_probe -j 2`.
- Packet includes `build.json`, `native-plan.json` and `help.txt`. Engine ran the connection-free native plan from this exact binary. Release independently verified its SHA-256/size/source receipt and successfully generated the Python wrapper's plan against it. Neither plan contacted storage.

The native help/plan retain descriptions of retired maintenance, projection and cap experiments. Run the five-step smoke below; those historical descriptions do not expand the owner's task or establish a format verdict. Retain the packet until the owner has a durable copy; moving the binary is safe when its expected SHA stays fixed.

## Owner command

Use the [ordered owner checklist](../owner-raw-safety.md) in the B15 package first. Provision a **different, unlocked** `cx-engine-first-lock-probe-*` scratch bucket and its Basin catalog. B1's indefinitely locked bucket cannot qualify purge. Supply only through the owner's environment: `DOCSPEC_M1_BUCKET`, `DOCSPEC_M1_CATALOG_URI` (ending in that bucket), `DOCSPEC_M1_WAREHOUSE`, `DOCSPEC_M1_S3_ENDPOINT`, `DOCSPEC_M1_CATALOG_TOKEN`, `DOCSPEC_M1_ACCESS_KEY_ID`, `DOCSPEC_M1_SECRET_ACCESS_KEY`. The script checks credential names, never reads their values, and inherits them directly into the native probe.

```sh
cd /Users/mikewolfd/Work/wt/ct-release-m1
uv sync --locked
.venv/bin/python scripts/dev.py test production-offline --path scripts/tests/test_m1_smoke.py
M1_NS="docspec_m1_$(.venv/bin/python -I -c 'import uuid; print(uuid.uuid4().hex)')"
.venv/bin/python -I scripts/m1_smoke.py --binary "$M1_PROBE" \
  --binary-sha256 "$M1_PROBE_SHA256" --namespace "$M1_NS" --work "$SAFE_WORK/m1-plan"
.venv/bin/python -I scripts/m1_smoke.py --binary "$M1_PROBE" \
  --binary-sha256 "$M1_PROBE_SHA256" --namespace "$M1_NS" --work "$SAFE_WORK/m1-live" --execute
cat "$SAFE_WORK/m1-live/summary.json" "$SAFE_WORK/m1-live/remaining.json"
```

The default is plan-only: it never invokes the probe. Execution requires `--execute`, an exact binary hash, a fresh local work directory, canonical scratch namespace and dedicated bucket/catalog. The native bucket guard stays intact.

Execution creates `growth`, appends days 0–2 at 100 rows/day, checks all 300 rows unchanged, runs the server stale-commit race on empty days 3–4, then purges the table. It preserves each JSON report and the post-purge object listing under the **owned table prefix**. The catalog namespace can remain; this is not a whole-bucket-empty claim. Review any remaining orphan objects without deleting them automatically.

Stop: interrupt on failure and keep the work directory. The script stops before the next action and performs no automatic purge after a failure. Use its retained `plan.json` and namespace to investigate a separately scoped cleanup. A fresh attempt needs a fresh namespace/work directory. No Basin call, real bucket write or live purge occurred during preparation; the owner's remote smoke remains unverified.
