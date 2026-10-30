# Engine-first archive capture, publication, backfill and maintenance

`capture-archive.yml` (**Capture archive sources**) and `archive-jobs.yml` (**Archive publish, backfill and maintenance**) operate the engine-first raw capture and derived release pipeline. Capture schedules bounded raw acquisitions from the live archive release pointer and weekly inventory seeds; `archive-jobs.yml` executes committed `docspec` model specifications to publish verified releases, run producer backfills, and maintain raw and derived storage.

| Workflow | Trigger | Operation |
| --- | --- | --- |
| `capture-archive.yml` | Daily at `03:23 UTC` or `workflow_dispatch` (when `vars.ARCHIVE_CAPTURE_ENABLED == 'true'` on `main`) | Run `congress_api.cli.capture_schedule` against the public release pointer and weekly seed inventories |
| `archive-jobs.yml` (`publish`) | `workflow_run` after successful **Capture archive sources** on `main`, or `workflow_dispatch` with `operation=publish` | Execute the committed model publish specification (`viewer_publication.archive_publish_job`), run local browser contract and HTTPS canary gates, and atomically advance the release pointer |
| `archive-jobs.yml` (`backfill`) | `workflow_dispatch` on `main` with `operation=backfill` | Execute the committed producer backfill specification (`viewer_publication.archive_backfill_job`) |
| `archive-jobs.yml` (`maintenance`) | Weekly on Sundays at `07:17 UTC` or `workflow_dispatch` on `main` with `operation=maintenance` | Verify raw archive integrity, check retained receipt evidence, and prune unreferenced derived releases (`viewer_publication.archive_maintenance_job`) |

## Shared concurrency and runtime admission

All R2 and lake writers (`capture-archive.yml`, `archive-jobs.yml`, `update-data.yml`, and `publish-explorer.yml`) share the `raw-source-mirror` concurrency group with `cancel-in-progress: false` and `queue: max`. This serializes writes across capture, publication, backfill, and maintenance without canceling an in-flight operation. Both archive workflows run with `contents: read` permissions and require an explicit `vars.CLOUDFLARE_ACCOUNT_ID` endpoint binding on every step that holds R2 credentials.

Every job verifies its pinned `docspec` runtime artifact (`vars.DOCSPEC_RUNTIME_ARTIFACT`) and engine credentials before accessing storage:

- `capture-archive.yml` uses `.github/actions/setup-local-job-runtime` (`.github/scripts/setup-local-job-runtime.py`), which verifies the pinned runtime and runs `docspec doctor` before any capture step executes.
- `archive-jobs.yml` first runs `.github/scripts/run-archive-job.py <operation> --check-binding` against `.github/archive-jobs.json`. Pending or blocked job specifications (`status == "blocked"` or missing `--execute` arguments) refuse immediately before installing the native runtime or opening storage. After binding admission succeeds, `.github/scripts/setup-native-runtime.py` installs and verifies the pinned runtime binary.

## Bounded capture batches (`capture-archive.yml`)

The `capture` job runs in the `archive-capture` environment on `ubuntu-24.04` with a 360-minute ceiling. It requires positive integer budgets configured in repository variables:

- `ARCHIVE_CAPTURE_REQUEST_BUDGET` (`--request-budget`)
- `ARCHIVE_CAPTURE_BYTE_BUDGET` (`--byte-budget`)
- `ARCHIVE_CAPTURE_SPOOL_BUDGET` (`--spool-budget`)
- `ARCHIVE_POINTER_URL` (`--pointer`)

`congress_api.cli.capture_schedule` compares the live public release at `ARCHIVE_POINTER_URL` with the existing checked-out weekly seed files (`pipeline-data/congress_meetings.jsonl.gz`, `pipeline-data/gpo-evidence.jsonl.gz`, `pipeline-data/meeting-inventory/house.json.gz`, `pipeline-data/meeting-inventory/house-sites.json.gz`, and `pipeline-data/meeting-inventory/senate.json.gz`), plans the bounded batch under `$RUNNER_TEMP/archive-capture`, and applies the capture schedule. Run reports (`*.json`) are uploaded as the `archive-capture-<run_id>-<run_attempt>` workflow artifact.

## Release publication, backfill and maintenance (`archive-jobs.yml`)

`.github/archive-jobs.json` binds each operation (`publish`, `backfill`, `maintenance`) to its owner CLI module and committed specification under `model/jobs/`:

1. **Publish (`publish`)**:
   - Runs `.github/scripts/run-archive-job.py publish --check-binding --github-output "$GITHUB_OUTPUT"` to validate the committed publish specification and export the planned `publisher_work` directory without opening the runtime.
   - Installs the pinned `docspec` runtime, Node project dependencies, and the publication browser, then builds `apps/site` (`npm run build`) once.
   - Invokes `.github/scripts/run-archive-job.py publish` (`python -I -m viewer_publication.archive_publish_job --spec <spec> --execute`), which executes the native model release build, verifies the release manifest (`origin.kind == "model"`, `display_only == false`) and Parquet tables, runs the local Playwright archive contract against the built site and candidate release, uploads the release objects, runs the HTTPS canary gate, and performs an `If-Match` conditional pointer update.
   - Uploads `outgoing-pointer.json`, `outgoing-pointer.response.json`, `contract.json`, and `canary.json` from `publisher_work` as `archive-publish-evidence-<run_id>-<run_attempt>`.
2. **Backfill (`backfill`)**:
   - Runs `.github/scripts/run-archive-job.py backfill --check-binding`, installs the pinned runtime, and executes `.github/scripts/run-archive-job.py backfill` (`python -I -m viewer_publication.archive_backfill_job --spec <spec> --execute`) to admit and record historical or producer backfill batches into the native dataset tables.
3. **Maintenance (`maintenance`)**:
   - Runs `.github/scripts/run-archive-job.py maintenance --check-binding`, installs the pinned runtime, and executes `.github/scripts/run-archive-job.py maintenance` (`python -I -m viewer_publication.archive_maintenance_job --spec <spec> --execute`).
   - Verifies raw capture custody in `congressional-tech-raw` (`congress_api.retention.raw_verifier`), validates retained receipt evidence (`viewer_publication.receipt_evidence`), and runs derived release retention (`viewer_publication.archive_maintenance`) to keep the current release plus the previous two verified releases while refusing to delete any referenced object.

## Local CLI reference

```sh
# Plan or apply a bounded capture batch against the public release pointer
python -I -m congress_api.cli.capture_schedule \
  --pointer "$ARCHIVE_POINTER" \
  --request-budget 5000 \
  --byte-budget 2147483648 \
  --spool-budget 5368709120 \
  --work /tmp/archive-capture \
  --apply

# Admit captured raw batches and reading receipts into native datasets
python -I -m congress_api.cli.captures_ingest \
  --engine-config "$DOCSPEC_JOB_CONFIG" \
  --work /tmp/archive-capture

# Verify raw archive checkpoints, receipts, and body samples
python -I -m congress_api.cli.raw_verify \
  --bucket congressional-tech-raw \
  --captures "$CAPTURES_PARQUET" \
  --engine-config "$DOCSPEC_JOB_CONFIG" \
  --receipt-inventory "$RECEIPT_INVENTORY" \
  --verification-inventory "$VERIFICATION_INVENTORY" \
  --work /tmp/raw-verify

# Check binding or execute committed archive jobs
python -I .github/scripts/run-archive-job.py publish --check-binding
python -I .github/scripts/run-archive-job.py publish
python -I .github/scripts/run-archive-job.py backfill
python -I .github/scripts/run-archive-job.py maintenance
```
