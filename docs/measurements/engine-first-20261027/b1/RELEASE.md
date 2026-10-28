# B1 lock-probe release

`release/b1-lock-probe` starts at shared `origin/main` `7411f5b7`. It ports the maintained CLI and probe from `6b79fd16`; ten focused tests pass, including no-connection dry run, bucket guards, multipart completion/abort and CLI refusal of 403 or 409 in place of 412. No live probe or lock was run.

```sh
cd /Users/mikewolfd/Work/wt/ct-release-b1
uv sync --locked
.venv/bin/python scripts/dev.py test production-offline \
  --path packages/congress_api/tests/test_raw_lock_probe.py
.venv/bin/python -I -m congress_api.cli.raw_lock_probe --bucket "$B1_BUCKET"
```

The last command is a no-connection preview. See [the owner checklist](../owner-raw-safety.md) for scratch bucket creation, exact lock configuration and readback. Set `B1_BUCKET` to a fresh `cx-engine-first-lock-probe-*` bucket and install the same enabled indefinite `bodies/` lock proposed for raw. Use an object read/write credential on that scratch bucket; a credential that itself denies overwrites cannot qualify the lock. Do not reuse the locked probe bucket for M1, which must purge tables.

```sh
.venv/bin/python -I -m congress_api.cli.raw_lock_probe \
  --bucket "$B1_BUCKET" --execute > "$SAFE_WORK/b1-result.json"
jq -e '.safe_to_lock == true and .statuses == .expected' "$SAFE_WORK/b1-result.json"
```

Require this complete status map:

| Operation | HTTP status |
|---|---:|
| Fresh create-only PUT | 200 |
| Existing-key create-only PUT | **412** |
| Unconditional overwrite | 403 |
| Delete | 403 |
| Fresh multipart initiation | 200 |
| Fresh multipart completion | 200 |
| Existing-key multipart completion | 403 |

Before locking `bodies/` and `provenance/`, check that the **412 belongs specifically to `statuses.create_existing`**, after a successful fresh create at the same `key` under `bodies/lock-probe/`. It must be the failed `If-None-Match: *` condition, rather than a permission or lock denial before conditional evaluation. Check `safe_to_lock=true`, exit status zero, the matching bucket/key, and every other status. A 403, 409, missing result, transport failure or incomplete multipart observation stops the procedure. Do not reinterpret a 409 as “already exists.” If the existing-key conditional result is not 412, B3 and ARCH §7.1 need a reviewed change before any raw lock.

Before applying raw locks, list `provenance/`, save its object metadata and enumerate anything outside `<kind>/<timestamp>.jsonl`; record each exception and its reason without renaming or deleting it. Preserve the initial recovery records and verification history. Only then install enabled indefinite rules on `bodies/` and `provenance/` and GET the configuration back. Leave `receipts/` writable until B0's final clean scan and coverage check pass.

Stop: omit `--execute` to keep the preview read-only, or interrupt the executing CLI and retain its output/error. Stop before applying raw locks on any failed observation. The scratch objects intentionally remain under the scratch lock; removing the scratch rule later is an owner cleanup action. Never test overwrite or delete against raw.
