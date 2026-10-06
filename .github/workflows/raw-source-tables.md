# Raw source document table updates

`capture-raw-sources.yml` saves capture batches and rebuilds the document tables
in separate runs. Capture persists bodies, receipts and retry state immediately;
the published tables reflect that evidence after the next successful rebuild.
Routine updates preserve saved interpretations and add new evidence. Only an
explicit rebuild reinterprets existing metadata; a fresh archive is built once.

| Trigger | Operation |
| --- | --- |
| Relevant code pushed to `main` | Validate Python and Rust; no archive reads or writes |
| Manual dispatch, `mode=update` (default) | Add new evidence, preserving saved metadata; no acquisition |
| Manual dispatch, `mode=rebuild` | Reinterpret all retained metadata with current rules; no acquisition |
| Manual dispatch, `mode=capture` | Capture missing sources; leave published tables unchanged |
| Daily at 03:23 UTC | Add accumulated evidence, preserving saved metadata; no acquisition |

Acquisition uses explicit dispatches so a failed or unverified batch cannot be
followed automatically by a scheduled capture. The population monitor dispatches
one capture at a time after the previous job and its verification succeed.
Generated outputs and `pipeline-data` commits do not trigger this workflow.

## Verified capture batches

Capture defaults to at most 20,000 attempts, including delayed retries, and five
hours of admission. Slow admitted requests can extend the run while it drains.
The job has a six-hour ceiling for setup, draining, checkpointing and verification.
`initial_only=true` selects pending URLs and their in-run retries; it leaves old
failures and retained-body replays for an explicit later operation. New links
remain part of the initial population. Set it false only for a deliberate retry
or replay run; `repair` is incompatible with initial-only acquisition.

For a targeted local recovery pass, use `--capture-only --retry-outcome retry_later
--retry-outcome request_failed`. This selects only due URLs in those categories,
honors their recorded retry times, and preserves the usual per-run retry bounds.
It fetches those URLs again without replaying retained bodies. Newly discovered
links are saved as pending for a separate initial pass. It cannot be combined with
`--initial-only`, `--repair`, or seed files.

Before fetching, capture rechecks saved pending URLs. It can recover the explicit
GPO document URL inside a LIS `/cgi-lis/t2GPO/` wrapper, or split concatenated
complete file URLs when every part independently passes the usual scope checks.
It does not guess missing URL components or split query parameters. The original
value remains in download state as `repaired_url`; unrecoverable pending values
become `excluded_scope`. These outcomes do not count as download attempts. Each
recovered target retains its original value and repair reason in receipts and
the catalog's existing source-association fields. Existing target captures are
reused, and a malformed catalog row's body is never assigned to a derived target.

CI uses the same Rust source and Python capture code as local operation. It runs
60 file starts/second, 80 tasks, 48 downloads, three metadata processes, a 2 GiB
parent buffer, 5 GiB spool and 64 MiB file cap. A five-second process-tree memory
sample requests graceful capture shutdown above 12 GiB; this is a sampled stop,
not a hard allocation limit. A memory stop fails the job after checkpointing.

Every run uploads a source manifest tied to its immutable checkout. Pass
`expected_source_digest` to refuse code or package-data differences before any
writes. The Linux binary is compiled from the locked Rust sources; its digest
need not match a macOS binary. Runtime dependency versions are recorded in the
artifact. The archive extra still pins PyArrow 25.0.1 to verify existing legacy
checkpoints before accessing the real archive. New checkpoints use the logical
row digest described below; their identity does not depend on Parquet encoding.

An optional `previous_summary` JSON dispatch input verifies the previous completed
capture against the current R2 checkpoint before acquisition. Use it when moving
from local capture and for each monitored continuation. The same verifier runs
after capture. It checks full checkpoint pairing, all run receipts and latest URL
states, queue accounting, all new metadata parts, and a deterministic body sample
(200 hash-selected, 10 largest, and 25 failed). It does not reread every historical
body or reused metadata reading. Reports and summaries are uploaded as artifacts.
A failed job or missing verification report stops automatic continuation.

## Checkpoint identity and transition

New capture and catalog checkpoints store `rows-v1:<sha256>` in `capture_digest`.
The digest includes ordered field names, types and nullability, the row count,
and each logical row in order. Its JSON encoding preserves nulls, empty strings,
Unicode and integer values. Arrow chunks, Parquet compression, writer-version
footers and table metadata do not affect it. Tests fix the expected digest and
compare retained files written by PyArrow 23.0.1 and 25.0.1.

Bare 64-character digests identify the previous Parquet-based algorithm. Readers
verify these with the original algorithm; they never accept a mismatch as a
version migration. Reading alone does not change the archive. The next successful
capture save or changed-evidence catalog publication writes the new digest. An
unchanged catalog remains untouched. Keep the legacy PyArrow pin until those
checkpoints have transitioned.

A missing digest/cursor field, invalid cursor, unknown digest version or digest
mismatch stops ordinary acquisition or updating before recovery/publication.
A historical archive without either checkpoint field can still bootstrap. For
an incompatible legacy checkpoint, use its original writer to verify it first;
only explicitly requested repair/rebuild can replay after investigation. Do not
change a saved digest to bypass verification.

The new format is a forward transition. Finish any old writer before dispatching
a new one, and update pinned continuation branches before resuming automation.
Do not run an older revision after new checkpoints have been saved: it cannot
understand `rows-v1` and may fall back to replay. Downgrades require an explicit
compatibility plan; CI's shared writer lock alone does not enforce code versions.

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

Generic ZIP downloads retain both the original archive and its file members.
Each member keeps its exact name, entry position, parent archive body key and
receipt pointer. Duplicate names remain distinct occurrences; identical bytes
share storage and metadata. Members use the existing metadata reader and capture
index. The next table update gives each member its own filename and body, with
the ZIP URL recorded as provenance rather than a fabricated member download URL.
Literal absolute links in member XML or HTML can add downloads; archive-relative
paths cannot. Office packages stay intact, and nested ZIPs are retained without
recursive expansion. Encrypted, corrupt, unsupported or oversized entries keep
explicit processing results. Expansion is bounded by member count, directory
size, individual and total decompressed bytes, and temporary copy space.

Direct 429/503 responses with a valid `Retry-After` defer another direct attempt
without occupying a download slot or invoking Zyte. GovInfo's ZIP generation page
waits at least 30 seconds. Each URL gets at most three delayed retries in one run;
all attempts count toward the run limit, and deferred state survives checkpoints.

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
Push validation uses a separate `raw-source-validation-<ref>` group, so code checks
can run while a data operation holds the writer lock. It skips pipeline-data,
credential-bearing archive steps and the status finalizer, even on failure.
Daily and manually dispatched operations retain the shared writer lock.
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

The workflow allows six hours for setup, capture or rebuilding, and verification.
Capture admission remains bounded to five hours, followed by draining. Separating the jobs avoids paying the
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
### Targeted local recovery

`raw-source-sync --capture-only --urls urls.json` restricts scheduling to an
explicit JSON array of source URLs. The complete archive state still loads and
is checkpointed. Discovered off-list links remain pending. Combine this with
`--retry-outcome retry_later --retry-outcome request_failed` for due network
retries; malformed legacy URLs are refused before dispatch and listed in the
summary without counting them as downloads.

Other failed outcomes, including `http_error` and `size_limit`, require both
`--retry-outcome` and `--urls`; successful captures cannot be selected as retry
outcomes. `--retry-now` explicitly bypasses existing `next_attempt_at` values
for that selection. It preserves old receipts and still honors new source
`Retry-After` waits and the three delayed retries allowed within a run.

For selected larger-file recovery, `--max-file-mib 0` removes the independent
file policy. The effective response capacity comes from the existing body and
spool reservations, approximately 682 MiB with a 2 GiB parent body budget and
5 GiB spool budget. This is resource-bounded admission, not unlimited memory
or disk. A response beyond that capacity records `resource_limit`, its original
transport error and declared length when available, without invoking Zyte for
the local refusal. ZIP archive and member byte allowances also use the parent
reservation; member count, directory, nesting and reader safeguards remain.
The summary records the policy value, effective byte capacity and whether the
selected retry overrode prior scheduling. Normal runs keep the 64 MiB default.

`--reinspect-retained --urls urls.json --capture-only` instead validates only
those retained bodies, even if they were previously inspected. It starts no
source HTTP worker and appends new readings without replacing old metadata.
Every selected URL must already have a body. It cannot be combined with seeds,
repair, initial-only or retry-outcome selection.

Static PNG and JPEG validation uses Pillow, records its version in new metadata
fingerprints, verifies structure, and decodes pixels in a disposable process.
Reader bounds are 16 MiB input, 16 million pixels, 5 CPU seconds and 10 elapsed
seconds; compressed PNG text is bounded separately. Linux also applies a 512 MiB
address-space limit. Animated images remain unsupported. These reader bounds do
not raise the capture's 64 MiB file cap. Catalog refreshes cannot reactivate an
excluded generated probe without an independent publisher link to that URL.
The catalog retains image format identity separately from capture validity, so
invalid image bytes remain represented without decoding pixels again or
interrupting a rebuild.
