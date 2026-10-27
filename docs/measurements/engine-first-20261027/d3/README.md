# Filename reader: local checks and first backfill

D3 builds a distinct work list of filename/source-URL pairs through the native engine, runs the maintained filename parser in a persistent bounded worker, and stages typed `filename_readings`. The work list includes current recovery decisions and excludes readings at the same parser version and active unreadable decisions. Parser code, vocabulary values, lockfile, shared filename SQL, parameters and lake schema determine the version. A dedicated producer package keeps unrelated D1 and D2 edits out of that version.

The local native producer and golden group passed 141 checks. The later complete filename suite passed 27 checks in 50.30 seconds with engine `3746f22`, including the actual persistent worker, native append, parser failures, rebuild exclusion and two same-time unreadable batches sharing one body store. Content-qualified unreadable keys preserve both batches. Independent code and architecture reviews approve the implementation and bounded fixes. Shared remote-authority checks also pass with a recording adapter and real native local SQL; no remote catalog or bucket operation ran.

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

New unreadable decisions are staged under the returned `unreadable_key` and `unreadable_path`. Their durable raw import is a separate live backfill gate; a lake append alone does not persist them. The common D2/D3 backfill integration must retain those bytes through the body store before claiming a rebuildable live backfill. No live append, unreadable import or production qualification is claimed here.
