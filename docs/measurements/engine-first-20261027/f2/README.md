# Capture scheduler: local checks and owner command

The scheduler reads one verified release's `url_state.parquet`, capture scope, capture profile and active URL variants. It runs the release's normalization and URL-key SQL through the native engine, takes unfetched URLs first, then reviewed cut-offs, then the oldest due time. Weekly inventory seeds preserve existing retry deadlines. Capture uses the common fetcher, receipt writer and body store; it reads no raw index and has no replay mode.

The body store acknowledges the acquired source before the receipt writer inspects it. Only a completed inspection publishes reusable format, version and integrity facts, for both source bodies and archive members. Known inspection read/resource failures record a stable `sniff_error`, leave the verdict unknown and preserve transfer completion; archive expansion then stays deferred so an unavailable local file cannot prevent its durable receipt. The scheduler uses the returned receipt's format for discovery. `--max-discovery-jobs` bounds replanning: after the bound, capture drains the existing queue under the same resource limits, while page bodies retain deferred links. Every run uses the release profile; the authored SQL/input override flags have been removed.

The initial review correction passed 84 focused checks in 15.44 seconds with engine `48636e5`, plus 36 existing sniff/pending-reading checks in 1.67 seconds. The review's remaining archive-reopen concern was reproduced by `714966f9` and fixed in `2f060977`; the completed-inspection correction `32ae2804`/`0e0ab719` received code-review approval. At `9d250ef5`, the combined scheduler, verifier, repair, fetcher, writer, expansion and completed-inspection group passed 104 checks in 19.25 seconds on engine `9b59263`. Fixtures use the actual profile SQL/rules, persistent discovery worker, fake HTTP adapters and local stores. No live capture ran; these checks do not qualify the Linux artifact or production budgets.

Earlier integration evidence used engine `3746f22`: 69 checks in 18.32 seconds (33 scheduler, ten shared-profile and 26 import-boundary checks), with independent approval of that earlier integration. That result does not qualify the later review correction.

The actual first engine-built real release, `ac866cc3f634249a786eea983b8cb3ef996ead48b26a4f227dea46794bbb23cf`, also passed the maintained CLI's read-only local planning path on engine `9b59263`. At `2026-10-28T00:00:00Z`, its 129 URL-state rows produced 89 due URLs, including 79 linked-but-unfetched URLs; the request budget selected five queued rows. No inventory seeds, HTTP requests, storage writes or apply operation ran. This checks the real release/profile seam; first live capture and production budget qualification remain owner gates.

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

Existing releases without the capture profile refuse. Both local and public runs use only release-pinned SQL, rules and variants. The disabled workflow remains under the switch owner's control; no workflow, secret, bucket or catalog was changed here.
