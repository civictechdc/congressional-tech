# Raw source document table updates

`capture-raw-sources.yml` collects missing sources and updates the document tables
in R2. Ordinary updates reuse completed work. Full source replay is an explicit
repair operation; a fresh archive or changed source parser also needs replay.

| Trigger | Operation |
| --- | --- |
| Relevant code pushed to `main` | Update metadata; no acquisition |
| Manual dispatch, `mode=rebuild` (default) | Update metadata; no acquisition |
| Manual dispatch, `mode=capture` | Capture missing sources, then update metadata |
| Every six hours | Capture missing sources, then update metadata |
| `Update committee data` completes on `main` | Capture missing sources, then update metadata |

The completion trigger accepts only runs from this repository, including failed
collection runs with retained partial progress. Generated outputs and
`pipeline-data` commits do not trigger this workflow.

## What an update reads

The updater reads the capture index, existing tables and processing checkpoints.
It checks that the previously consumed capture prefix has not changed. With the
same source parser, only new captures and previously unavailable source bodies
need replay. New links can still be associated with older captures by exact URL.
A changed filename parser reuses source interpretation and body results. Changed
body readers invalidate body results independently. A changed source reader
replays source context; this conservative invalidation covers the source-parser
set, not individual committee layouts.

The internal checkpoints are three Parquet files under `indexes/processing/`:

| File | Contents |
| --- | --- |
| `sources.parquet` | Source rows, paired page/link observations, scoped meeting facts and URL associations |
| `filenames.parquet` | Filename and source URL, with flat filename-derived fields |
| `bodies.parquet` | Body key and reader, with flat content-derived fields; an empty result records a completed inspection |

These files contain derived processing state. They do not replace raw bodies,
receipts or the public document tables. Missing bodies do not count as completed
inspections. Source interpretation is saved before filename/PDF work; completed
filename and body stages are saved before publication, including on ordinary
exceptions. A hard kill can still lose the current stage's unsaved work.

An unchanged update reads no raw receipts or bodies and leaves the published
pair alone. Updates still rewrite the derived Parquet tables when their inputs
or meanings change. The first run after this change initializes checkpoints.

Acquisition loads saved download state first, applies new capture rows, and
imports document URLs only when the filename table's object version changes.
It continues to recover receipt batches that were saved before an interrupted
index write. `--repair` enables reconstruction from the historical capture index.

## Commands

Update retained metadata without acquisition:

```sh
raw-source-sync --rebuild-only
```

Explicitly replay retained sources and filename/body interpretation:

```sh
raw-source-sync --rebuild-only --repair
```

The local archive uses the same updater:

```sh
document-filename-index .cache/congressional-tech-raw
```

The old `--documents-only`, `--metadata-only` and `--source-metadata-only` flags
remain accepted as aliases for automatic updating. Callers no longer choose
which interpretation stages to run. `--inventory-dir` remains a one-time legacy
inventory import; a standalone filename table can be refreshed without a raw
archive. Neither local operation fetches upstream sources.

In GitHub Actions, choose **Capture raw sources and rebuild document tables**.
Leave `repair` disabled for normal runs. `limit` and `transport` apply only to
capture mode. Metadata-only runs pass no Zyte token and skip native-fetcher setup.
Capture mode invokes the updater once after acquisition.

## Validation, publication and recovery

The workflow checks out the event's exact `github.sha`. Successful Python
validation is reusable only for that revision, operating system, architecture,
Python version and installed dependency versions. The tested Rust binary has a
separate exact-match cache, including its pinned toolchain. There are no fallback
cache keys. Cache misses rerun validation; failed validation never saves a success
marker or binary. Data integrity checks still run on every table publication.
The cache uses GitHub's [separate restore and save actions](https://github.com/actions/cache/tree/main/restore).

All R2 writers share the `raw-source-mirror` concurrency group with
`cancel-in-progress: false`. The workflow has read-only repository permissions.
Before replacement, it validates the paired tables and preserves exact previous
table bytes in `catalog-history/sha256/`. Conditional writes reject competing
index updates. Readers must check matching `catalog_id` values; interrupted
publication may leave an unmatched pair, which the next update repairs.

The Actions summary and retained artifact include operation, revision, publication
result and progress. Live progress is also available at
`status/raw-source-sync.json`. A missing completion summary fails the step;
a last status of `running` may indicate an interrupted process. Hosted completion
and publication require examining the actual run and its resulting tables.

The workflow allows four hours. Capture remains bounded to 90 minutes, leaving
time for updating metadata or an explicitly requested repair.
