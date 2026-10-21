# Raw source document table updates

`capture-raw-sources.yml` saves capture batches and updates the catalog in
separate runs. Capture retains bodies, receipts and retry state immediately;
the published catalog reflects that evidence after the next successful update.
Ordinary updates read selected raw changes and their affected dependencies. They
preserve saved values and refuse an implicit full rebuild. Existing archives
require explicit exact-value adoption and source-contribution qualification.

| Trigger | Operation |
| --- | --- |
| Relevant code pushed to `main` | Validate Python and Rust; no archive reads or writes |
| Manual dispatch, `mode=update` (default) | Apply new retained evidence incrementally; no acquisition |
| Manual dispatch, `mode=capture` | Capture missing sources; leave published catalog unchanged |
| Daily at 03:23 UTC | Apply accumulated evidence incrementally; no acquisition |

All archive operations require an explicit `--native-config` for the maintained
DocSpec runtime. Hosted jobs require its configured distribution and execution
inputs; missing configuration refuses execution. A local passing test does not
establish hosted deployment or production adoption.

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

## Legacy checkpoint background before native adoption

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
Use the original writer to investigate incompatible legacy checkpoints before
preparing exact adoption inputs. The current operational CLI refuses `--repair`
and `--rebuild-only`; neither flag authorizes bypassing verification. Preserve
the original checkpoint bytes and never replace a saved digest to force a match.

The new format is a forward transition. Finish any old writer before dispatching
a new one, and update pinned continuation branches before resuming automation.
Do not run an older revision after new checkpoints have been saved: it cannot
understand `rows-v1` and may fall back to replay. Downgrades require an explicit
compatibility plan; CI's shared writer lock alone does not enforce code versions.

## Native catalog updates and explicit migration

DocSpec owns exact completed data versions. `indexes/raw.json` selects coherent
capture, URL-state and reading references. `indexes/catalog.json` selects a
coherent native catalog and its retained source/dependency evidence. The filename
view preserves source observations and document mappings; the document view
combines proved aliases using the maintained grouping rules. Readers pin one
selection. A failed update or losing conditional write leaves the old selection
readable. Original Parquet files, receipts, bodies, IDs, mappings and review data
remain retained.

An unchanged incremental update checks its selected identity and publishes
nothing. Changed raw deliveries replay their affected receipt/body dependencies.
Native lookup and output leaves have finite row and decoded-byte limits. SQLite
holds affected rows and memberships on disk. Explicit continuation directories
keep completed native chunks and completed component summaries for retry.
Restart still reconstructs disposable grouping indexes and emits final tables;
it skips completed metadata combination. One document summary can exceed the
16 MiB leaf budget; that row refuses admission without truncating its values.

Existing file catalogs require these separate, explicit steps:

1. Adopt the exact existing catalog pair with `--adopt-catalog OPERATION`.
   When the pair is already retained, add `--retained-catalog DIRECTORY`.
   The directory contains `catalog-selector.json`, `filenames.parquet` and
   `documents.parquet`. The saved selector must exactly match the live selection;
   file hashes, sizes and row metadata are checked locally before native work.
   Corrupt or missing retained files refuse without downloading replacements.
   This reads every selected source/document value back from native storage and
   verifies IDs, mappings and original row order; it does not regroup or classify.
2. Adopt investigated capture/state files and the exact retained reading inventory
   with `--adopt-raw INPUTS_JSON`. Pin the already adopted catalog identity in the
   receipt's `filename_version`. The maintained bounded owner performs one raw
   selection only after its source and input checks succeed.
3. Run `--qualify-sources` against the adopted selections. It replays the complete
   retained source inventory and requires every selected source/document value
   and ID mapping to remain exact. A mismatch refuses publication for investigation.
4. Resume `--update-only` for ordinary changes. A later global source-rule change
   requires `--upgrade-source-rules VERSION` after contribution qualification.
   The nonempty version names that deliberate change; it cannot authorize source
   acquisition, dropping old ownership, or implicit legacy reconstruction.

Operational raw adoption receipts use version 2 with explicit local paths, SHA-256
pins and exact original source bucket/key/version pins. Copy each source version
verbatim from its retained receipt ETag; do not strip its quotes or infer it from
the local file hash. Relative paths resolve beside the receipt. Retain the receipt and continuation
directory when retrying:

```json
{
  "version": 2,
  "operation": "investigated-raw-adoption-20261020",
  "inputs": {
    "captures": {
      "path": "captures.parquet",
      "sha256": "<64 lowercase hex characters>",
      "source": {"bucket": "congressional-tech-raw", "key": "indexes/captures.parquet", "version": "<exact retained source ETag>"}
    },
    "state": {
      "path": "state.parquet",
      "sha256": "<64 lowercase hex characters>",
      "source": {"bucket": "congressional-tech-raw", "key": "indexes/download-state.parquet", "version": "<exact retained source ETag>"}
    }
  },
  "filename_version": {
    "selector_sha256": "<exact adopted catalog selector SHA-256>",
    "selected_ref": {"key": "<exact selected metadata key>", "bytes": 0, "sha256": "<exact metadata SHA-256>"}
  }
}
```

Copy the complete `filename_version` from the verified adopted catalog identity;
the displayed metadata reference is illustrative, not an executable seed. Raw
state retains its complete investigated Arrow schema, including extra typed fields.
Operational adoption checks both source versions before preparation and again
immediately before its existing raw selector update. The request binds these
pins, so retries cannot substitute another source version. Completed retries use
the original delivery and preserve later selected native changes.

**Production cutover gate:** record that every legacy writer is inactive or fenced
and keep that state through selection. Checks on the two source objects and the
conditional `indexes/raw.json` update are separate operations; they detect drift
but do not atomically fence a legacy writer. Any drift requires investigation and
new reviewed inputs; it does not authorize an automatic refresh or rebuild.
The local `adopt_tables` fixture helper establishes local input preservation only,
not remote source authority.

The legacy body-reader cache is a source for explicit adoption only. Normal
native updates use the selected keyed reading inventory and do not scan that cache.

## Commands

Use the same explicit native configuration and retain `--catalog-directory`
between retries. These examples name local input files; do not run adoption
against an archive without its investigated pins.

```sh
raw-source-sync --native-config native.json --capture-only
raw-source-sync --native-config native.json --update-only
raw-source-sync --native-config native.json --adopt-catalog investigated-pair-20261020
raw-source-sync --native-config native.json --adopt-raw investigated-raw-inputs.json
raw-source-sync --native-config native.json --qualify-sources
raw-source-sync --native-config native.json --upgrade-source-rules source-rules-2
```

All four explicit migration modes skip acquisition, provider-token lookup and
source HTTP worker setup. They use operation-specific continuation identities;
an interrupted retry uses the same candidate and directory. A changed request
refuses reuse instead of silently replacing retained work.

The local raw archive command enters the same maintained incremental path:

```sh
document-filename-index .cache/congressional-tech-raw --native-config native.json
document-filename-index .cache/congressional-tech-raw --native-config native.json --qualify-sources
```

The local command refuses raw archives without explicit native configuration.
`--rebuild`, `--repair`, and global `--inspect-bodies` cannot replay them. A
standalone filename-only input and an explicit `--inventory-dir` import retain
their separate local utility paths. Scoped retained-body reinspection uses the
capture command described below and appends new readings without source HTTP.

GitHub Actions exposes only `update` and `capture`. Metadata-only runs require
no Zyte token or native source fetcher. Capture mode uses `--capture-only`; a later
incremental update applies retained progress from successful or interrupted capture
runs. The workflow does not automatically adopt an existing archive or change
its global source rules.

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
up to 100 pending runs, so a new capture does not replace a queued catalog update.
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
publication leaves the previous selected pair readable. An incomplete or unmatched legacy pair refuses exact adoption and requires
investigation; ordinary operations never reconstruct a replacement implicitly.

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

The workflow allows six hours for setup, capture or catalog updating, and
verification. Capture admission remains bounded to five hours, followed by
draining. Separating the jobs avoids repeating catalog work on every capture
batch; these time limits do not establish a full-corpus memory bound.


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
[`scripts/measure/benchmark_core_rebuild.py`](../../scripts/measure/benchmark_core_rebuild.py)
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
