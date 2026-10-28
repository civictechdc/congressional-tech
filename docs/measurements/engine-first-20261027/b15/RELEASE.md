# B15 weekly raw preservation release

Prepared on `release/b15-weekly-raw` from existing `origin/main` `7411f5b7`. Contracts `38700dec` precede implementation `674b0471`. This owner-approved port copies the maintained weekly writer and applies only its synchronous storage and workflow changes. A local snapshot commit is preserved as create-only raw bodies and receipts before its Git ref is published.

Main's `scripts/dev.py`, `test-suites.toml`, setup action, lockfile and dependency declarations are unchanged. This release requires no native runtime configuration. The generic capture `ReceiptWriter`, lake and site are outside the weekly import graph; the shipped `pipeline_raw.py` writes its own receipts. Existing `body_files.py` is reused unchanged.

## Shipped source, configuration and tests

Line counts include complete files, not added lines.

| File | Lines |
|---|---:|
| `.github/scripts/prepare-raw-writer.sh` | 23 |
| `.github/scripts/save-pipeline-data.sh` | 20 |
| `.github/tests/test_clean_raw_writer.py` | 205 |
| `.github/tests/test_update_data_workflow.py` | 93 |
| `.github/workflows/update-data.yml` | 276 |
| `model/registries/credential-parameters.json` | 42 |
| `model/registries/import-runs.json` | 6 |
| `packages/congress_api/src/congress_api/cli/pipeline_raw.py` | 65 |
| `packages/congress_api/src/congress_api/retention/body_store.py` | 282 |
| `packages/congress_api/src/congress_api/retention/pipeline_raw.py` | 245 |
| `packages/congress_api/src/congress_api/retention/r2.py` | 602 |
| `packages/congress_api/src/congress_api/retention/receipt_privacy.py` | 167 |
| `packages/congress_api/src/congress_api/retention/writer_identity.py` | 25 |
| `packages/congress_api/tests/test_async_capture_native.py` | 387 |
| `packages/congress_api/tests/test_body_store_contract.py` | 215 |
| `packages/congress_api/tests/test_pipeline_raw.py` | 230 |
| `packages/congress_api/tests/test_r2_archive_store.py` | 345 |
| `packages/congress_api/tests/test_writer_identity.py` | 86 |

The release ticket and this handoff are the only additional metadata. Correction to the implementation commit body's count: `r2.py` is **597 → 602** lines; the committed diff is authoritative.

## Verification

Baseline workflow checks: **3 passed**. New workflow contracts failed **8** cases before the port. After the port, the project runner passed **123** focused checks, including real archive helpers, conditional storage/checksums, clean identity, source-byte identity and all five local weekly success/failure cases. The five-case weekly dry run uses a local raw store and a local bare Git repository; setup, body and receipt failures make zero push calls, and a push failure leaves raw evidence intact. No network write, live import or hosted workflow ran. Architecture review found one existing SDK retry fixture with a malformed body key; the forward fix derives its key from the fixture bytes. Its 25 loopback cases were collected and deselected by the offline lane, and remain unexecuted. Independent code and architecture reviews identified that same fixture issue; commit `16664219` fixes it. The code reviewer separately ran 112 focused checks and 8 existing public-body checks successfully.

Run the focused lane from this worktree:

```sh
.venv/bin/python scripts/dev.py test production-offline \
  --path .github/tests/test_clean_raw_writer.py \
  --path .github/tests/test_update_data_workflow.py \
  --path packages/congress_api/tests/test_pipeline_raw.py \
  --path packages/congress_api/tests/test_writer_identity.py \
  --path packages/congress_api/tests/test_body_store_contract.py \
  --path packages/congress_api/tests/test_r2_archive_store.py \
  --path packages/congress_api/tests/test_r2_body_files.py
```

## Owner release steps

1. Add GitHub repository secrets **`R2_ACCESS_KEY_ID`** and **`R2_SECRET_ACCESS_KEY`** for the approved raw writer. `CLOUDFLARE_ACCOUNT_ID` is public workflow configuration. Existing workflow secrets remain in place.
2. Push the prepared branch, review its diff and merge it into main:

```sh
git -C /Users/mikewolfd/Work/wt/ct-b15-weekly-raw push origin release/b15-weekly-raw
```

3. After the merge and secret setup, enable and run the existing workflow:

```sh
gh workflow enable update-data.yml --repo civictechdc/congressional-tech
gh workflow run update-data.yml --ref main --repo civictechdc/congressional-tech
```

Check all four save steps. The first hosted run remains an owner gate.

## Owner rescued-batch import

Use the reviewed batch at `/Users/mikewolfd/Work/ct-raw-rescue/pipeline-data`. The release preview reports 33 snapshots, 2,013 files, 226 distinct bodies and zero missing blobs; it reads metadata and checks presence without hashing source blobs or connecting to storage. Repeat the preview:

```sh
.venv/bin/python -I -m congress_api.cli.pipeline_raw \
  --rescue-batch /Users/mikewolfd/Work/ct-raw-rescue/pipeline-data --dry-run
```

Before importing, set the `pipeline-data-rescue-20261027` entry in `model/registries/import-runs.json` to the **actual UTC import date** and commit that edit, leaving the application clean. The CLI refuses a stale date before connecting. Then run, as the owner:

```sh
.venv/bin/python -I -m congress_api.cli.pipeline_raw \
  --rescue-batch /Users/mikewolfd/Work/ct-raw-rescue/pipeline-data \
  --bucket congressional-tech-raw
```

The rescue keeps original snapshot times and uses its registered run; ordinary weekly saves use fresh fetch runs. No rescued data was modified or imported during release preparation.
