# Filename reader: local checks and first backfill

D3 builds a distinct work list of filename/source-URL pairs through the native engine, runs the maintained filename parser in a persistent bounded worker, and stages typed `filename_readings`. The work list includes current recovery decisions and excludes readings at the same parser version and active unreadable decisions. Both D3 and the release model read `model/sql/filename-inputs.sql` through the fixed `filename_captures` view, then the shared effective-filename SQL. Parser/producer code, vocabulary values, lockfile, both SQL files, parameters, lake schema, `parser_worker.py` and `process_resources.py` determine the version. A dedicated producer package keeps unrelated D1 and D2 edits out of that version.

The shared-input/version correction (`5400f1f3`, `9218e303`) passed 38 focused checks in 7.69 seconds with engine `48636e5`: the complete filename suite and the existing actual D3/model pair-parity fixture. Contract-first checks reproduced five failures for canonical SQL loading/refusal and the three omitted digest dependencies before the source change. The isolated version fixture copies the complete producer package and all version inputs, then changes/restores each file; unrelated D1 changes remain excluded. The producer decreased from 357 to 354 lines by deleting its duplicate input SQL. Independent code and architecture reviews approved the shared-input/version correction.

The local parity completion passed all 38 filename checks in 6.63 seconds with engine `48636e5`. It invokes the actual `viewer_publication.archive_model.source_steps()` filename steps and real D3 staging with the same captures and already-current recovery records. Both paths produce the complete expected seven filename/source-URL pairs: header precedence, literal member basename, requested-only fallback, accepted and rejected recoveries, and the same basename at two distinct URLs. Repeated exact pairs collapse and retained-import captures add no work. Native `EXCEPT ALL` returns zero in each direction. This checks names before the model's later source-file filtering; the engine-owned broader model fixture may retain its separate extension request.

B4's reviewed-pin correction and raw-only rebuild fixture landed in `18129d19`/`72191130` (85 focused checks passed in 16.88 seconds). Canonical unique unreadable admission landed in `72e08e98`/`eff53177` (87 passed in 16.95 seconds). The rebuild retains raw receipts and unreadable provenance, deletes capture and filename stages, reconstructs captures through D1, and checks same-version exclusion, unavailable-input retry and new-version retry. Pending decisions still refuse append before catalog effects. These are recorded local runs at those commits; live import and append remain the owner gates below.

Earlier evidence: the local native producer and golden group passed 141 checks, and a later filename suite passed 27 checks in 50.30 seconds with engine `3746f22`. Independent reviews approved that earlier implementation and bounded fixes. Those earlier results do not qualify this correction. No remote catalog or bucket operation ran.

## Owner commands

First qualify the complete D1 captures and the target Linux runtime. `RECOVERY_INVENTORY` is a pinned JSON list of `{key,path}` entries. It must include **both** selected recovery objects from `shared/raw-recoveries-owner-32c13ffa`: the byte-identical base decisions and the 57 superseding owner decisions. Include any other kept raw recovery objects. `UNREADABLE_INVENTORY` likewise lists all kept unreadable provenance objects; an empty list is explicit. Choose a fresh work directory outside the checkout and an explicit timezone-bearing decision time.

The local staging command writes no live data:

```sh
.venv/bin/python -I -m congress_api.lake.filenames \
  --engine-config "$DOCSPEC_JOB_CONFIG" --captures "$PINNED_CAPTURES" \
  --recovery-inventory "$RECOVERY_INVENTORY" \
  --unreadable-inventory "$UNREADABLE_INVENTORY" \
  --decided-at "$D3_DECIDED_AT" --work "$D3_BACKFILL_WORK"
```

After owner qualification, the first remote append command is:

```sh
.venv/bin/python -I -m congress_api.lake.filenames \
  --engine-config "$DOCSPEC_LIVE_JOB_CONFIG" --captures "$PINNED_CAPTURES" \
  --recovery-inventory "$RECOVERY_INVENTORY" \
  --unreadable-inventory "$UNREADABLE_INVENTORY" \
  --decided-at "$D3_DECIDED_AT" --work "$D3_LIVE_APPEND_WORK" \
  --apply --table "$D3_VERSIONED_TABLE"
```

The live configuration supplies the explicit engine remote authority; omit `--catalog-root`. For a reviewed new table, add `--create-table --table-location "$REVIEWED_TABLE_URI"`; add `--create-namespace` only for a new namespace. For subsequent work, supply `--existing "$PINNED_FILENAME_READINGS"`. Local catalog runs instead supply `--catalog-root "$LOCAL_CATALOG_ROOT"` with a local engine configuration.

New unreadable decisions use the shared `retention.provenance.import_unreadable` helper and a timestamp plus content SHA key. Component callers supply an explicit durable body store. Stage-only commands return `unreadable_pending=true` and an `unreadable_stage`; append refuses before any catalog effect while that import is pending. Import the reviewed stage with the existing provenance command, refresh `UNREADABLE_INVENTORY` from durable raw, then rerun the producer and append:

```sh
.venv/bin/python -I -m congress_api.cli.provenance \
  --stage "$UNREADABLE_STAGE" --apply --bucket congressional-tech-raw
```

The first live import and append remain owner gates. Local tests import into a raw store outside the producer work, delete all stages, and rebuild from raw alone: unreadable inputs stay excluded, unavailable inputs remain pending, and new versions retry. No live append, unreadable import or production qualification is claimed here.
