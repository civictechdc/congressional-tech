# B15 weekly raw preservation release

`release/b15-weekly-raw` starts at the shared `origin/main` `7411f5b7`. It preserves source files as create-only bodies and receipts before either collection or publication force-pushes `pipeline-data`. The release includes the publication job's pinned `uv` setup and `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` environment. All five save steps use the same script. Setup, body or receipt failure prevents its push; a push failure leaves raw evidence intact.

The application writer runs from a clean checkout at the exact application commit with `uv sync --locked`. No native runtime is required. Main's runner, Python dependencies and lockfile remain unchanged; `test-suites.toml` adds a storage-only loopback lane because the existing native lane also requires source-fetch.

## Local verification

- **150 focused checks pass**, including both actual workflows' commands against local bare Git and fake raw storage, storage integrity, writer identity, interrupted rescue retries, and the owner-command/runner checks.
- **26 SDK loopback checks pass**, using the repository's local HTTP fakes with real synchronous/asynchronous S3 SDKs. No SDK loopback check is skipped. These files also belong to the existing CI native loopback lane.
- The actual rescue CLI passed twice against an injected local S3 protocol fake on **copies of two real snapshots: 122 files, 303,593,622 distinct source bytes**. Input hashes and stored object identities remained identical. A conflicting receipt was refused before PUT.
- No hosted workflow, real bucket, Basin job or network write ran. Hosted behavior, R2 lock semantics and live readback remain owner gates.

```sh
cd /Users/mikewolfd/Work/wt/ct-b15-weekly-raw
uv sync --locked
.venv/bin/python scripts/dev.py test production-offline \
  --path .github/tests/test_owner_raw_safety_commands.py \
  --path .github/tests/test_dev_environment.py \
  --path .github/tests/test_clean_raw_writer.py \
  --path .github/tests/test_update_data_workflow.py \
  --path packages/congress_api/tests/test_pipeline_raw.py \
  --path packages/congress_api/tests/test_writer_identity.py \
  --path packages/congress_api/tests/test_body_store_contract.py \
  --path packages/congress_api/tests/test_r2_archive_store.py \
  --path packages/congress_api/tests/test_r2_body_files.py
.venv/bin/python scripts/dev.py test storage-loopback -- -ra
```

## Owner sequence

Use [the ordered owner checklist](../owner-raw-safety.md), starting with rescue import or a verified copy off this disk. It contains the before/after inventories and receipt/body readback commands. Do not enable either workflow before installing the secrets: merging this release triggers `publish-explorer.yml` automatically.

```sh
gh secret set R2_ACCESS_KEY_ID --repo civictechdc/congressional-tech
gh secret set R2_SECRET_ACCESS_KEY --repo civictechdc/congressional-tech
git push origin release/b15-weekly-raw
gh pr create --repo civictechdc/congressional-tech --base main --head release/b15-weekly-raw \
  --title 'Preserve pipeline snapshots in raw before publication' \
  --body 'Preserve source snapshots before both pipeline-data pushes; local failure and SDK loopback checks pass. See B15 RELEASE.md.'
gh pr merge release/b15-weekly-raw --repo civictechdc/congressional-tech --merge
gh workflow enable update-data.yml --repo civictechdc/congressional-tech
gh workflow enable publish-explorer.yml --repo civictechdc/congressional-tech
gh workflow run publish-explorer.yml --ref main --repo civictechdc/congressional-tech
gh workflow run update-data.yml --ref main --repo civictechdc/congressional-tech
```

Verify the automatically triggered publication and the first collection run, then its downstream publication. Require successful raw preservation before all five snapshot pushes; inspect each raw summary's receipt key and download that receipt, confirm its snapshot commit URL, and match every referenced body key to the post-run body listing. Stop with `gh workflow disable` for both workflows; cancel an active run with `gh run cancel RUN_ID`. Do not rerun the old save helper by itself.

## Rescued batch

Read-only preview refreshed from `/Users/mikewolfd/Work/ct-raw-rescue/pipeline-data`: **35 snapshots, 2,135 files, 226 distinct bodies, zero missing blobs**; 10,722,485,958 file bytes and 1,176,433,815 distinct source bytes. This preview trusts recorded digests; the actual import hashes source bytes before storage.

```sh
.venv/bin/python -I -m congress_api.cli.pipeline_raw \
  --rescue-batch /Users/mikewolfd/Work/ct-raw-rescue/pipeline-data --dry-run
```

Before the live command, register the actual UTC import date for `pipeline-data-rescue-20261027` in `model/registries/import-runs.json` and commit only that file. The writer requires a clean application tree and refuses a stale date before connecting. Keep that exact commit, batch order and date for retries.

```sh
.venv/bin/python -I -m congress_api.cli.pipeline_raw \
  --rescue-batch /Users/mikewolfd/Work/ct-raw-rescue/pipeline-data \
  --bucket congressional-tech-raw
```

This writes missing bodies at `bodies/sha256/<shard>/<sha256>` (reusing recognized legacy suffixes) and one receipt per 50,000 files at `receipts/pipeline-data/<registered-date>/pipeline-data-rescue-20261027-000001.jsonl.gz`. The present batch needs one receipt. Lines retain the original snapshot times, order, repetitions and Git blob IDs, with `mode=fetch` and the registered import run. Derived `committee-explorer/` files are excluded.

A rerun on the **same UTC date, exact clean application commit and unchanged batch** is idempotent: it verifies existing body storage, validates completed receipt identities and retains their original creating lines. It can finish a partial import without replacing completed receipts. Different input, writer or recorded storage metadata fails closed. After UTC midnight the date guard stops; retain the original commit and evidence and arrange a reviewed continuation rather than changing the registry to create a second dated import. Never delete or rewrite the rescue batch after import; keep the independent backup.
