# Capture scheduler: local checks and owner command

The scheduler reads one verified release's `url_state.parquet`, capture scope, capture profile and active URL variants. It runs the release's normalization and URL-key SQL through the native engine, takes unfetched URLs first, then reviewed cut-offs, then the oldest due time. Weekly inventory seeds preserve existing retry deadlines. Capture uses the common fetcher, receipt writer and body store; it reads no raw index and has no replay mode.

On this Mac, 69 focused checks passed in 18.32 seconds with engine `3746f22`: 33 scheduler checks, ten shared-profile checks and 26 import-boundary checks. They include the actual shared SQL and persistent parser worker with fake HTTP/local storage, request/byte/spool limits, credential-bearing discovery refusal, all reviewed cut-off dispositions and immutable release pins. Independent code and architecture reviews approve the integration and shared-validator reuse. The scheduler decreased from 541 to 522 lines when the duplicate validator was removed. No live capture ran; these checks do not qualify the Linux artifact or production budgets.

## Owner gate

First publish an engine-built release with all four inputs, supply the approved Linux runtime whose source revision matches its capture profile, and size request, byte and spool budgets from that release's due rows. Supply writer credentials externally and run from a clean pinned checkout after the switch checklist permits capture. `ARCHIVE_CUTOFF_URLS` names the reviewed cut-off URL JSON list. Keep work outside the checkout; its path must be new.

The following uses exactly the weekly seed paths supported by the maintained workflow; absent files are omitted. For a read-only planning run, omit `--apply` and choose a separate fresh work directory. The first live command is prepared, not executed:

```sh
seeds=()
for path in pipeline-data/congress_meetings.jsonl.gz pipeline-data/gpo-evidence.jsonl.gz \
  pipeline-data/meeting-inventory/house.json.gz pipeline-data/meeting-inventory/house-sites.json.gz \
  pipeline-data/meeting-inventory/senate.json.gz; do
  if [ -f "$path" ]; then seeds+=(--seed-inventory "$path"); fi
done
.venv/bin/python -I -m congress_api.cli.capture_schedule \
  --pointer "$ARCHIVE_POINTER" --engine-config "$DOCSPEC_JOB_CONFIG" \
  --request-budget "$REQUEST_BUDGET" --byte-budget "$BYTE_BUDGET" --spool-budget "$SPOOL_BUDGET" \
  --cutoff-urls "$ARCHIVE_CUTOFF_URLS" "${seeds[@]}" --work "$CAPTURE_WORK" --apply
```

Existing releases without the capture profile refuse. Public pointer runs cannot replace release-pinned SQL or rules with workspace files. The disabled workflow remains under the switch owner's control; no workflow, secret, bucket or catalog was changed here.
