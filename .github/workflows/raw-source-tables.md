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

## Two steps

1. **Inventory known files.** Read capture receipts for filenames, requested/final
   URLs, response facts and parent/link context. Include links whose files have
   not been downloaded. New retained parent XML/HTML can supply additional links
   and publisher labels. The existing filename table supplies unchanged facts.
2. **Extract useful metadata.** Run house-naming on new or changed filename
   inputs, combine its fields with source metadata, and group proved aliases.
   Opening retained document contents is optional (`--inspect-bodies`).

The two public tables retain distinct views of the same catalog:

| File | Contents |
| --- | --- |
| `catalog-generations/<generation>/document-filenames.parquet` | Exact file/URL observations, receipt locators, source context and per-filename fields |
| `catalog-generations/<generation>/documents.parquet` | Grouped documents, extracted metadata and all known aliases |

`indexes/catalog.json` selects both immutable files together after their IDs,
checksums, and row counts pass validation. Consumers read this selection once
and use the named pair. Root `indexes/document-filenames.parquet` and
`indexes/documents.parquet` are migration inputs only when no selection exists.
A corrupt or incomplete selected generation fails instead of falling back to
unselected roots. An interrupted generation upload leaves the last selected
pair readable. A competing writer must pass the conditional selection update.
Local commands stage outputs outside the archive, preserving legacy root files
even during the first migration. Their results return the selected generation's
file paths.

Raw receipts and bodies remain authoritative. The capture index locates those
receipts; the filename table is the reusable inventory. There is no additional
saved source graph or filename-result table. Old `indexes/processing/sources.parquet`
and `filenames.parquet` objects are ignored; this change does not delete archive data.

An unchanged update reads neither receipts nor bodies and publishes nothing.
On new captures, it replays new source records. Scoped meeting facts may be read
from older Congress.gov receipts, and exact URL/body recovery may read older
receipts; ordinary updates do not download all existing document bodies.
A changed source parser or `--repair` rebuilds source interpretation from receipts
and retained parent pages. Filename-rule changes reuse the inventory's context.

Optional content inspection keeps one disposable result cache,
`indexes/processing/bodies.parquet`, keyed by reader and body digest. This avoids
repeating expensive PDF work, including inspections that found no classification.
Missing bodies remain retryable. Only explicit inspection writes this cache;
completed readings are saved approximately every minute and at stage exit.
Metadata-only updates preserve earlier content readings and their reader version.
An interrupted source/filename build reruns unpublished work from the receipts
and last published inventory; there is no promise of resuming its internal join.

Acquisition loads download state, applies new capture rows and imports changed
inventory URLs. Unindexed receipt batches recover interrupted acquisition.
The rebuild uses a disposable local SQLite database to bound metadata joins
and grouping. It is working storage, not a new source authority or service.

## Commands

Update retained metadata without acquisition:

```sh
raw-source-sync --rebuild-only
```

Reconstruct the inventory and explicitly inspect retained document contents:

```sh
raw-source-sync --rebuild-only --repair --inspect-bodies
```

The local archive uses the same updater:

```sh
document-filename-index .cache/congressional-tech-raw
```

The old `--documents-only`, `--metadata-only` and `--source-metadata-only` flags
remain accepted as aliases for automatic updating. Callers no longer choose
legacy refresh paths. Content inspection has one explicit switch. `--inventory-dir` remains a one-time legacy
inventory import; a standalone filename table can be refreshed without a raw
archive. Neither local operation fetches upstream sources.

In GitHub Actions, choose **Capture raw sources and rebuild document tables**.
Leave `repair` and `inspect_bodies` disabled for normal runs. `limit` and `transport` apply only to
capture mode. Metadata-only runs pass no Zyte token and skip native-fetcher setup.
Capture mode invokes the updater once after acquisition.
Acquisition saves its summary and releases the download queue, state, fetcher and
signal handlers before the updater starts. Failed or interrupted acquisition saves
raw progress but does not start a catalog build. The updater streams prior-table
columns and derives flat filters from paired occurrences rather than retaining
both representations. It shares repeated immutable strings and occurrence values
across aliases, consumes input rows during assembly, and releases interpretation
caches before grouping documents. During explicit content inspection, native XML
and format reading precede source-kind selection; recognized source kinds avoid
unnecessary PDF-cover reads. The existing 16 MiB inspection
limit is checked against captured byte lengths before downloading bodies;
unavailable bodies are attempted once per run and remain retryable next time.
PDF-cover inspection closes its reader and in-memory buffer after every file,
including unreadable PDFs, instead of depending on later garbage collection.

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
publication leaves the previous selected pair readable. Legacy root files may
already be unmatched; the rebuild can repair them by publishing a validated
generation.

The Actions summary and retained artifact include operation, revision, publication
result and progress. Live progress is also available at
`status/raw-source-sync.json`, including process memory and `heartbeat_expires_at`.
Treat an expired heartbeat as unavailable/stale, not proof of ongoing work.
A small finalizer job on a separate worker records the collection job's outcome
even if the original worker dies. It checks run ID, attempt and object version,
so it cannot overwrite a later run's status. If that job also cannot run, the
heartbeat expiry remains the fallback. GitHub remains authoritative for job state.
A capture summary with `catalog_status=pending` proves retained acquisition only;
it does not claim new tables were published. A missing completion summary fails
the step. Hosted publication requires checking the resulting table pair.

The [architecture review](../../docs/raw-source-pipeline-review.md) records the
failure evidence, boundaries, changes and verification limits.

The workflow allows four hours. Capture remains bounded to 90 minutes, leaving
time for updating metadata or an explicitly requested repair.


## Operational accounting and qualification

The summary records acquisition, catalog publication, and planning statuses
separately. A catalog failure leaves `acquisition_status=completed` and
`catalog_status=failed` when collection already finished. A collector failure
drains successful tasks already in flight, saves their receipts and state, and
fails acquisition before publication. Failures identify their exception type
without placing exception payloads in status reports.

`accounting` names each counting unit: distinct normalized URLs, submitted and
completed capture tasks, native request dispatches, usable capture results,
unique retained body keys, filename rows, and grouped documents. URL outcomes
and source-family membership explain exclusions, failures, and source pages.
Native dispatch counts describe commands queued before worker execution; actual
wire HTTP starts remain unknown. Stored bodies include failed responses and
provider bytes. Grouped document metadata can describe uncaptured files. These
counts cannot be interpreted as interchangeable totals.

The offline CI gate tests each acquisition write boundary, partial collector
failure, offline publisher rebuild, immutable-pair selection, bounded staging,
source context, and the pinned benchmark on a small fixture. Both committee
updates and raw capture upload the fixture qualification report when validation
runs. Successful validation caches include revision and dependency identity.

For a full source/index snapshot benchmark, use
[`scripts/benchmark_core_rebuild.py`](../../scripts/benchmark_core_rebuild.py)
as described in [`core-workflow-qualification.md`](../../docs/core-workflow-qualification.md).
It pins consumed source/index inputs, seeds, and published outputs; records time,
reads and stage memory; and compares hashes of complete records with a reference
pair, preserving duplicate counts. Linux aggregate process
memory is sampled across worker children; other platforms report parent memory
and leave the aggregate budget unqualified. Below 8 GiB for a full Linux
metadata rebuild remains a target until that full run is executed and retained.
