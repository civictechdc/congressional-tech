# Raw source document table updates

`capture-raw-sources.yml` saves capture batches and rebuilds the document tables
in separate runs. Capture persists bodies, receipts and retry state immediately;
the published tables reflect that evidence after the next successful rebuild.
Routine updates preserve saved interpretations and add new evidence. Only an
explicit rebuild reinterprets existing metadata; a fresh archive is built once.

| Trigger | Operation |
| --- | --- |
| Relevant code pushed to `main` | Update metadata; no acquisition |
| Manual dispatch, `mode=update` (default) | Add new evidence, preserving saved metadata; no acquisition |
| Manual dispatch, `mode=rebuild` | Reinterpret all retained metadata with current rules; no acquisition |
| Manual dispatch, `mode=capture` | Capture missing sources; leave published tables unchanged |
| Every six hours, at minute 23 UTC | Capture missing sources; leave published tables unchanged |
| Daily at 03:23 UTC | Add accumulated evidence, preserving saved metadata; no acquisition |
| `Update committee data` completes on `main` | Capture missing sources; leave published tables unchanged |

The completion trigger accepts only runs from this repository, including failed
collection runs with retained partial progress. Generated outputs and
`pipeline-data` commits do not trigger this workflow.

## Table rebuild steps

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
Code changes alone do not invalidate source, filename, body, or document-group
metadata. `--rebuild-only` (or the legacy explicit `--repair`) replays source
interpretation from receipts and retained parent pages. With `--inspect-bodies`,
that explicit rebuild also replaces saved body readings. New evidence can still
change affected alias groups during an ordinary update. Implementation fingerprints
describe the build; reused values may predate it. Earlier published generations
retain their original metadata.

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
Filename enrichment consumes source rows in batches, gathers shared facts, and
writes one temporary Parquet stream. After all aliases are known, it reads that
stream once into grouping. It does not rewrite the rows after each enrichment
step. A disposable SQLite database supplies indexed lookups and grouping; it is
working storage, not a published format or service. Previous filename and body
interpretations are restored together, independent of code fingerprints.

## Commands

Save a capture batch without rebuilding document tables:

```sh
raw-source-sync --capture-only
```

Update retained metadata without acquisition:

```sh
raw-source-sync --update-only
```

Reconstruct the inventory and explicitly inspect retained document contents:

```sh
raw-source-sync --rebuild-only --inspect-bodies
```

The local archive uses the same updater:

```sh
document-filename-index .cache/congressional-tech-raw
# Explicitly reinterpret saved metadata:
document-filename-index .cache/congressional-tech-raw --rebuild
```

The old `--documents-only`, `--metadata-only` and `--source-metadata-only` flags
remain accepted as aliases for automatic updating. Callers no longer choose
legacy refresh paths. Content inspection has one explicit switch. `--inventory-dir` remains a one-time legacy
inventory import; a standalone filename table can be refreshed without a raw
archive. Neither local operation fetches upstream sources.

In GitHub Actions, choose **Capture raw sources and rebuild document tables**.
Leave `repair` and `inspect_bodies` disabled for normal runs. `limit` and `transport` apply only to
capture mode. Metadata-only runs pass no Zyte token and skip native-fetcher setup.
`inspect_bodies` requires update or rebuild mode. `repair` in capture mode reconstructs
capture state; in rebuild mode it replays source interpretation.
CI capture mode uses `--capture-only` and never invokes the updater. A later
rebuild reads all captures retained so far, including partial progress from
failed collection runs. Capture can also resume before that rebuild, using
saved receipts and retry state to avoid repeating successful downloads.
New files therefore remain absent from the published tables until a successful
rebuild; dispatch `mode=update` when an earlier publication is needed.

For compatibility, a local `raw-source-sync` invocation without a mode flag still
captures and updates metadata while preserving saved interpretations. It releases the download queue, state, fetcher and signal
handlers before the updater starts. Failed or interrupted acquisition saves raw
progress but does not start a catalog build. The updater streams prior-table
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
`cancel-in-progress: false` and `queue: max`. This serializes writes while allowing
up to 100 pending runs, so a new capture does not replace a queued rebuild.
GitHub cancels additional runs if that queue is full; schedules are not guaranteed
start times. See [GitHub's concurrency documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
The workflow has read-only repository permissions.
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
A successful capture-only summary has `acquisition_status=completed` and
`catalog_status=not_run`; its final progress stage is `capture_saved`. It does not
claim new tables were published or report new filename/document counts.
A missing completion summary fails
the step. Hosted publication requires checking the resulting table pair.

The [architecture review](../../docs/raw-source-pipeline-review.md) records the
failure evidence, boundaries, changes and verification limits.

The workflow allows four hours for setup and a capture batch or rebuild.
Capture remains bounded to 90 minutes. Separating the jobs avoids paying the
table rebuild cost on each capture batch; it does not reduce an individual
rebuild's memory requirement or guarantee a shorter rebuild.


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
