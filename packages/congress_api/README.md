# congress-api

`congress-api` collects congressional committee hearing metadata from Congress.gov, GovInfo, chamber committee sites, and Senate ISVP video. It retains publisher-shaped source records, joins them into meeting inventories, and can produce normalized transcripts. Console scripts are the primary interface; library code under `src/congress_api/` backs those commands and the [`committee-meeting`](../committee_meeting/README.md) adapters.

| Name | Value |
| --- | --- |
| PyPI / install name | `congress-api` |
| Import name | `congress_api` |
| Monorepo npm name | `@ct/congress-api` (private; Python packaging is authoritative) |
| Python | `>=3.12` (`pyproject.toml`) |

`import congress_api` does not re-export symbols. Import submodules directly, or run a console script from `pyproject.toml`.

## Related documentation

| Document | Topic |
| --- | --- |
| [SOURCE_MODELS.md](SOURCE_MODELS.md) | Source models, parsing, verification limits and witness-PDF evaluation |
| [Filename tooling](../house-naming/FILENAME_PATTERNS.md) | Regex filename parsing, corpus audits, residuals |
| [committee-meeting](../committee_meeting/README.md) | Canonical normalized meeting model |
| [Meeting state & refresh](../../docs/youtube-coverage/meeting-state.md) | Pipeline state directories and refresh rules |
| [Compatibility and maintenance](../../docs/congress-api-contracts.md) | Stable commands/artifacts, CI, versions, offline behavior, identity and replay safeguards |

## Install

From the repository root:

```bash
uv pip install -e packages/committee_meeting -e packages/congress_shared \
  -e packages/congress_api
```

Optional tests: `uv pip install -e "packages/congress_api[test]"` (adds `pytest>=9,<10`).

PDF recovery requires Poppler's `pdfinfo` and `pdftotext`: install `poppler-utils`
on Debian/Ubuntu or `poppler` with Homebrew. The normal cover reader remains
pypdf. Poppler handles rejected PDF structure and unsupported text operands,
with a 16 MiB input limit, a ten-second deadline per invocation, and bounded
stdout/stderr. It reads only the requested opening page. New metadata fingerprints
include reader versions; existing metadata remains reusable until an explicit
rebuild. A readable PDF structure does not prove that the publisher's document
is complete. Exact-file recovery can read larger, already-verified PDFs directly
from disk through the same opening-page classifier. Each Poppler process has a
ten-second deadline, a 1 MiB text-output limit, five CPU seconds and a sampled
512 MiB resident-memory limit; Linux also limits address space to 512 MiB. This
extracts cover facts from at most the first two pages, not full text or OCR.

Runtime dependencies include `committee-meeting`, `congress-shared`, `pydantic`, `lxml`, `requests`, `pypdf[fonts]`, `google-genai`, and `yt-dlp`. Sibling packages resolve through `[tool.uv.sources]` in `pyproject.toml`.

`congress-shared` supplies API key loading, default data paths, and `congress_metadata.json`. The separate `youtube-api` package collects YouTube data. These commands read its saved JSON with the standard library; TinyDB is not a congress-api dependency.

`hearing-transcribe` expects `ffmpeg` and `ffprobe` on `PATH`. YouTube and Senate audio paths use `yt-dlp`.

Filename rules and corpus tooling live in the independent [house-naming package](../house-naming/README.md).
The optional `archive` dependency group uses that package to build document tables;
ordinary source collectors do not require it.

## Streaming source capture

`raw-source-sync` runs a bounded async capture pipeline. Rust handles publisher
HTTP, and `aiobotocore` overlaps immutable R2 body uploads. Existing synchronous
fetch adapters run in a bounded executor; two processing threads run validation,
compression, House XML and PDF cover readers off the event loop. One writer
accepts confirmed bodies, appends metadata and publishes receipts. Concurrent
aliases share body uploads and readings. Saved readings, including unclassified
results, survive reader-version changes. Reading and uploading each body can
overlap; the writer waits for both before publishing its metadata and receipt.

`--workers` bounds admitted files across the whole lifecycle. The default
`--download-workers 16` bounds downloads and completed files waiting for a body
reader. Rust streams responses into temporary files, with a separate
`--max-spool-mib 2048` disk budget. Each download reserves room for one maximum
provider response; redirects and fallback consume and remove the previous file
before fetching the next. Failed native commands stop their writer and clean up
partial files before releasing the reservation.

`--max-buffer-mib 512` bounds processing payload reservations. A reader reserves
three maximum file sizes plus 1 MiB before loading its first body, then releases
the excess after separating actual body bytes. Files waiting for this capacity
stay on disk, so slow processing does not restrict HTTP to two downloads. Acquired
bytes and the fetcher's inspection result pass directly to retention; receipts
keep their existing serialized shape. Synchronous injected fetchers and retained
body replay still reserve memory before acquisition.

The payload budget is not an RSS limit; compressed copies, provider JSON, parser
allocations and loaded indexes add memory. A stop request closes admission,
drains admitted files, and saves the checkpoint. The summary records cumulative
task times by stage (these overlap), both reservation peaks, and CLI limits.

Metadata goes to an incremental Parquet writer under
`indexes/processing/body-results/<run-id>/`. It closes and uploads immutable parts
at 1,000 metadata rows, 4 MiB of estimated row data, five minutes, or the next
receipt checkpoint. The final partial part is saved on normal completion and
graceful interruption. Bodies are uploaded first, then metadata, then capture
receipts; an interrupted run can recover from completed receipts. Metadata
upload errors stop receipt publication, while extraction errors retain the raw
capture and record the error type. In-memory body inspection retains its 16 MiB
limit; file-based PDF recovery uses the bounded reader described above. Other
oversized formats still record `size_limit`. Existing readings remain unchanged
unless an explicit refresh selects their body keys.
Capture startup projects only body identities from previous parts. Catalog
updates scan completed metadata parts to recover readings, including parts whose
receipt upload was interrupted. This scan grows with the metadata history; it
does not transfer the source bodies. New optional fact columns do not invalidate
older parts.

The default command saves capture indexes and then incrementally updates the
published filename/document tables. Those updates reuse the new body facts
without rereading document bytes. Source-page context still uses the existing
House/Senate readers. `--capture-only` saves captures and extraction results for
a later `--update-only` run, as used by scheduled CI. To reinterpret prior body
metadata, explicitly use `--rebuild-only --inspect-bodies`.

### Exact large-file recovery

`congress_api.acquisition.streamed_recovery` provides `recover_zip` and
`recover_pdf` for a finite set of reviewed publisher files. The caller supplies
an existing `Archive`, an HTTP client, a private spool directory and a manifest
with the exact source URL, byte length and `Last-Modified` value. PDFs also require
the publisher's SHA-256; ZIP manifests list each member's name, size and CRC.
Assigning a member to a document URL requires a separate publisher SHA-256.
This library is an explicit recovery path, not an automatic retry policy.

Downloads use 16 MiB ranges and 1 MiB chunks, refusing version changes, redirects,
wrong ranges or incomplete data. A journal permits reuse only of checksum-verified
completed ranges. The default spool allowance remains 5 GiB. Conditional R2
writes preserve existing bodies; receipts, metadata and checkpoints use the normal
archive path. ZIP members retain original names and positions without using those
names as local paths or expanding nested archives. A document restored from a
qualified member is recorded as a replay, separately from network fetches.

The completed summary must pass `.github/scripts/verify-capture-run.py` before
another recovery starts. Sampled bodies larger than 64 MiB are verified serially
on disk, including both stored and decompressed hashes and lengths. The
`recovery_queue.plan_recovery` helper selects a frozen campaign once, with at most
one due follow-up for a generating GovInfo ZIP; other failures are not recycled.

For an explicit metadata refresh, `read_document_file` prepares a reading from a
hash-verified local body; `CaptureMetadata(..., refresh_body_keys=selected_keys)`
can append it without deleting previous metadata parts. Appending a reading alone
does not replace published classifications. A separately invoked
`rebuild_catalog(..., body_readings=selected_readings)` applies validated completed
PDF readings to every alias of those body keys, without downloading the bodies or
changing unrelated readings. An explicit empty cover clears stale cover fields;
the existing body-result cache preserves that decision in subsequent updates.
The output records each selected body key and reader fingerprint. Ordinary
updates continue reusing existing metadata.

For a local capture run that also updates the document index:

```bash
raw-source-sync --bucket congressional-tech-raw \
  --fetcher-binary packages/source-fetch/target/release/source-fetch \
  --transport auto --files-per-second 60 --workers 80 \
  --limit 20000 --max-seconds 5400 --index-workers 2 \
  --summary .cache/local-capture-summary.json
```

This uses the R2 and Zyte credentials from the environment. Run only one capture
or catalog writer at a time, including CI; local commands do not participate in
GitHub Actions concurrency groups.

## Credentials and environment

Congress.gov and the GovInfo collection API share one [data.gov](https://api.data.gov) key. `congress_shared.auth.load_congress_api_key` checks, in order:

1. `--congress-api-key` (via `parse_known_args`, even when the command did not declare the flag)
2. `DATA_GOV_API_KEY`
3. `~/.data.gov.api.key`, then `~/.data.gov.key`

| Variable / flag | Used by |
| --- | --- |
| `DATA_GOV_API_KEY` / `--congress-api-key` | `congress-meetings`, `congress-committees`, `gpo-fetch`, … |
| `GEMINI_API_KEY` | `hearing-transcribe` (Gemini windows) |
| `YOUTUBE_API_KEY` | Optional video duration in `hearing-transcribe` (else `yt-dlp`) |
| `ZYTE_TOKEN` | `congress_api.transport.zyte` / `transport.http.get_with_retry` for bot-challenged hosts; `house-meeting-records --zyte` |

`hearing-transcribe --proxy` is forwarded to `yt-dlp`.

## HTTP policy

This is the authoritative policy matrix. No clients are merged by the refactor.

| Call path / hosts | Pacing, retries and timeout | Zyte and metadata |
| --- | --- | --- |
| `transport.http.get_with_retry`: House repository, GovInfo, Congress.gov and committee sites | Direct starts: 1.2 s for `docs.house.gov`, 0.2 s elsewhere; 3 attempts, 60 s timeout. Retry 202/403/408/429/500/502/503/504/520 and request exceptions; other unallowed statuses stop. Next-start backoff is 2^(attempt+1) s; direct House 403 waits 60 s. `allowed` defines caller-confirmed statuses | Explicit `through_zyte=True`, not automatic fallback. Zyte skips local pacing; returned response is synthetic. `response_metadata` retains all available parsed header fields and states fidelity; callers retain metadata separately |
| `acquisition.meetings.get` and committee snapshot collection: Congress.gov | Delegates to the same gateway with **5 attempts**, injects API key/JSON format, decodes JSON | No Zyte option on this wrapper; safe gateway errors omit query secrets |
| `transport.senate.sess`: ISVP playlists and WebVTT | Module-level `requests.Session`, HTTPS `pool_maxsize=32`; default 3 immediate attempts, 30 s timeout. 404 is absence, empty 200 retries, exhausted failures raise | No Zyte. Typed media captures retain status/text/raw body; not gateway response-header metadata |
| `transcripts.generate`: GPO HTML and YouTube duration | Direct requests: 60 s for GPO HTML, 30 s for YouTube JSON; no shared retry/pacing. yt-dlp is the duration fallback | No Zyte; GPO HTML is retained separately |
| `transcripts.context`: GovInfo MODS and unitedstates GitHub Pages legislators | `urllib.request.urlopen`, 60 s timeout, explicit User-Agent; legislators cached in memory, MODS fetched on demand; no gateway retries | No Zyte; source bytes/models retained by the metadata path |
| Audio / Gemini | yt-dlp/ffmpeg and google-genai own their transports; Gemini has its existing application retry loop | Not part of the shared HTTP gateway |

A 200 challenge page is not automatically successful source parsing. Collector
validation decides usability. Failed checks remain failures; they must not
become empty source records. Host locks control request starts, not in-flight
completion. A supplied session is used directly; `session=None` uses a thread-local
session. See `tests/test_http_policy.py`, `test_http_response_metadata.py`,
`test_zyte_capture.py`, and caption source tests.

Exhausted gateway failures report the attempt count and bounded exception class
names, including nested DNS failures. Exception messages and query parameters
are excluded from these diagnostics. House request receipts retain the same
structured failure details.

## Package layout

Files are grouped by responsibility, with provider names inside each group:

| Directory under `src/congress_api/` | Responsibility | Examples |
| --- | --- | --- |
| `models/` | Describe publisher fields and preserve unknown values | Congress.gov, House XML, MODS, media, transcript models |
| `parsers/` | Interpret supplied bytes or decoded data; no files or HTTP | `congress.py`, `house.py`, `senate.py`, `gpo.py`, `witness_pdf.py`, `captions.py` |
| `acquisition/` | Select and collect source records; manage refresh decisions | `meetings.py`, `committees.py`, `house.py`, `senate.py`, `gpo.py`, `gaps.py` |
| `transport/` | Implement retries, pacing and provider/media access | `http.py`, `zyte.py`, `senate.py`, `audio.py`, `gemini.py` |
| `retention/` | Read/write captures, generated tables, failures and refresh state | `tables.py`, `meetings.py`, `gpo.py`, `captions.py`, `rejected_pages.py` |
| `adapters/` | Convert source data to `committee_meeting` using supplied identity/import context | Meeting, material, committee and transcript adapters |
| `matching/` | Classify meetings and associate documents, recordings and witnesses | `meetings.py`, `prints.py`, `recordings.py`, `completeness.py` |
| `transcripts/` | Produce published-text, caption and generated transcripts with distinct origins | `gpo.py`, `senate.py`, `generate.py`, `context.py`, `render.py` |
| `replay/` | Reinterpret saved evidence without fetching replacements | `house.py`, `senate.py`, `gpo.py` |
| `cli/` | Parse command arguments and connect collection, matching and output | Ten console entrypoints plus common flags |

The dependency direction is concrete: collectors use transports, parsers and
retention; parsers and matchers accept supplied data; adapters receive identity
and import context from their application. Models, parsers and matching cannot
import collection, storage or command wiring. Tests enforce this boundary.

For inventory witness recovery, `matching.completeness.witness_sources` selects
exclusive prints and linked PDFs. `acquisition.gaps.collect_witnesses` collects
those inputs. `matching.completeness.build` reads supplied observations to build
the report. `cli.inventory` connects those steps and saves partial progress.

The former provider-based import paths were removed; all in-repository consumers
use the directories above. Console names, flags, retained formats, parser versions
and stored evidence/matching identifiers remain unchanged. Source identifiers are
stable labels, not Python import paths. Replay commands use `congress_api.replay`.

## Console scripts

| Script | Module | Primary output |
| --- | --- | --- |
| `congress-committees` | `cli.committees` | Gzip JSONL of `CommitteeSnapshot` rows |
| `congress-meetings` | `cli.meetings` | `congress_meetings.jsonl.gz` |
| `house-committee-sites` | `cli.house_sites` | All-history site events/documents + `house-sites.json.gz` |
| `house-meeting-records` | `cli.house` | House CSVs + `house.json.gz` state |
| `senate-meeting-records` | `cli.senate` | Senate CSVs + `senate.json.gz` state |
| `meeting-inventory` | `cli.inventory` | Inventory CSVs + `inventory.json.gz` |
| `gpo-fetch` | `cli.gpo_fetch` | `gpo_hearings.csv` (+ optional evidence store) |
| `gpo-transcripts` | `cli.gpo_transcripts` | One `.txt` per package under `--out-dir` |
| `gpo-match` | `cli.gpo_match` | `gpo_hearing_videos.csv` + coverage CSV |
| `senate-captions` | `cli.senate_captions` | WebVTT text, receipts, `captions_index.csv` |
| `hearing-transcribe` | `cli.transcribe` | `{stem}.json` + `{stem}.gpo.txt` |
| `raw-source-sync` | `cli.raw_sync` | Missing bodies, appended receipts, capture/retry indexes and rebuilt filename/document tables in R2 |

`congress_shared.globals.add_global_args` adds `--tinydb_dir` where used. Commands that call `parse_known_args` leave `--congress-api-key` available for the key loader.

### Module-only CLIs

| Invocation | Role |
| --- | --- |
| `python -m congress_api.replay.house` | Upgrade retained House evidence from cache (no network) |
| `python -m congress_api.replay.senate` | Upgrade retained Senate pages from cache |
| `python -m congress_api.replay.gpo` | Merge cached MODS/HTML into GPO CSV and evidence |
| `python -m congress_api.cli.senate_captions` | Same as `senate-captions` |

## Common workflows

### Recurring raw-source capture

[Capture missing raw sources](../../.github/workflows/capture-raw-sources.yml)
runs as explicitly dispatched, verified batches using
`--capture-only --initial-only` to save evidence without rebuilding document tables. It reads the
R2 mirror's capture and filename indexes plus available native records on
`pipeline-data`. It downloads missing URLs, follows explicit document and subtitle
links, and leaves historical retries and retained-body scans for an explicit
later operation. It does not crawl site navigation or archive full video/audio files. Authenticated Congress.gov,
GovInfo collection and YouTube API requests remain with their existing collectors.

Production uses the Rust `source-fetch` reqwest worker, with **direct requests
first and one Zyte fallback when capture fails**. It starts at most **60 files
per second**; redirects and one fallback share the initial file slot, with up to
**80 concurrent source tasks**. The rate is a shared ceiling; source latency,
archive writes, and file inspection can lower completed captures per second.
CI limits each batch to 20,000 attempts (including delayed retries) and five hours
of admission. It verifies receipts, metadata parts, checkpoint accounting and a
body sample before the monitor may start another batch. The default local CLI
retains its 5,000-attempt/90-minute defaults; use explicit bounds for other runs.
Manual `direct` and `zyte` modes remain available. The default
response limit is 64 MiB; larger responses remain incomplete, never successful.
Increase `--max-file-mib` for a targeted run.

Fallback uses the same inspection rules as capture: request errors, non-200
statuses, partial bodies, empty or invalid files, challenges, and HTML without
recognized download links trigger one Zyte attempt. Successful files, HTML
wrappers with download links, and excluded media do not. A blocked redirect
stays blocked. Receipts retain the direct attempt's body, status, and headers
alongside the final result. Provider authentication failures still stop new
work after in-flight captures are retained.

Build the native worker with `cargo build --release --locked --manifest-path
packages/source-fetch/Cargo.toml --bin source-fetch`, then pass its path with
`--fetcher-binary` or put it on `PATH`. GitHub Actions builds and tests it before
collection. Python continues to own URL checks, file interpretation, receipts,
retry state, and catalog publication. Rust owns the shared HTTP pool and rate
limit; body files cross the process boundary through a temporary local directory.

Each run writes bodies to `bodies/sha256/` before appending immutable gzip JSONL
batches under `receipts/<family>/<date>/download-<run-id>-<batch>.jsonl.gz`.
Receipts preserve source/provider status, headers, available source context,
discovered links and body references. They retain unknown source dates and
saved-text fidelity when replaying older captures. Source status and retrieval
date remain distinct from the latest inspection time.

`indexes/download-state.parquet` tracks pending URLs, results and retries;
`indexes/captures.parquet` gains new receipt references. A separate rebuild,
scheduled daily at 03:23 UTC and available by manual dispatch,
reads accumulated evidence and writes the filename and document tables in an immutable
`catalog-generations/<generation>/` directory. A conditional update to
`indexes/catalog.json` selects both files together; readers validate that pair.
The old root table paths serve as migration inputs when no selection exists.
New captures appear in those tables after the next successful rebuild. Code pushes
run Python and Rust validation without archive access. The local
CLI preserves combined capture-and-rebuild behavior when no mode flag is given.
`--update-only` uses `retention/raw_catalog.py` and the existing
`retention/document_index.py` readers. Rebuilds replay indexed migration and
download receipts, House state/XML, Senate state/pages, Congress meeting records
and inventory relationships on the first build or an explicit rebuild.
Routine updates reuse verified prior observations and interpret new receipts.
The tables retain unfetched filenames, response-header
names, redirects and parent committee/meeting metadata. Filename and body
interpretations remain reusable when code changes. Only `--rebuild-only` or
`document-filename-index --rebuild` explicitly reapplies current rules. Body
readings are replaced only when that rebuild also uses `--inspect-bodies`.
Filename enrichment collects shared facts while consuming bounded source
batches, writes each temporary Parquet batch once, and reads it once into
grouping after later aliases are known. SQLite retains indexed lookup/grouping
state; unchanged document groups reuse verified prior results.

To save captures without updating the published tables:

```sh
raw-source-sync --capture-only --bucket congressional-tech-raw
```

This saves bodies, receipts and retry state. Its summary reports
`acquisition_status=completed` and `catalog_status=not_run`. Successful downloads
remain reusable by later capture runs before publication. `--inspect-bodies`
requires a rebuild and cannot be combined with `--capture-only`.

To refresh the derived tables independently of acquisition:

```sh
raw-source-sync --update-only --bucket congressional-tech-raw \
  --index-workers 2 --summary raw-update-summary.json
```

This mode requires `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID` and
`R2_SECRET_ACCESS_KEY`. It reads the R2 capture index and its retained receipts
and necessary bodies, validates both generated tables, and atomically selects
their immutable generation with a conditional manifest write. It skips acquisition,
the Rust fetcher, Zyte credentials, and all capture/download-state writes.
Optional `--seed` files supply already saved link metadata, including filenames
whose bodies have not been captured. Reading these files does not queue or fetch
URLs. `--plan-only` and `--local-mirror` cannot be combined with this mode.
Acquisition flags such as `--limit`, `--transport` and `--workers` do not limit
the rebuild. `--index-workers` controls filename interpretation.

Capture and rebuild commands print timestamped progress when stages change and
every 30 seconds while running. Updates include the current stage, completed and
total items where known, elapsed time, time since the last reported progress,
and cumulative retained-object reads and bytes. Stages cover source replay,
filename interpretation, content inspection, grouping, validation and publication.
Counts describe that stage, not an overall completion percentage or ETA.

The latest update is saved beside `--summary` with a `.progress.json` suffix.
Live R2 runs also update `status/raw-source-sync.json` every 30 seconds and at
exit. This small status object is separate from the data indexes; status-upload
failures do not fail the data operation. It includes the run ID and, in GitHub
Actions, the workflow run ID, attempt and code revision. Check that identity and
`updated_at` before treating a saved status as current. A hard kill can leave the
last status as `running`; the GitHub job result remains authoritative.
The local `document-filename-index` command uses the same reporting and saves
its latest update to `<archive>/status/document-index.json`, without uploading it.

In GitHub Actions, open **Capture sources or rebuild document tables** to follow the
live log. The final job summary and downloadable artifact retain the last local
progress file even when publication fails. Existing jobs keep the code they
started with, so new progress reporting begins with the next updated run.

Before either derived table is replaced, its previous bytes are retained under
`catalog-history/sha256/<digest>/<table>.parquet`. The summary reports
`previous_filenames_key` and `previous_documents_key`. This preserves old-only
columns and labels for audit without asserting that untraceable values came from
the publisher. A history-write failure stops publication. Literal publisher
types use `source_document_type_basis=publisher`; saved House parser labels use
`house_parser_inference`. Each claim keeps its own `source_occurrences` entry
and receipt locator. Missing source fields remain null; inferred labels never
receive a publisher basis.

The October 3 comparison's 26,107 shared filename rows with a type in R2 and none
locally were all reproduced from retained `house.json.gz` receipts. These include
the Elmendorf, Christie, Kemple, Ware and Zapote examples. The older House labels
must not be relabelled as native publisher types. Literal `WS` observations are
also retained where the saved XML evidence supplies them. This audit verifies
those missing types; it does not establish a full remote-corpus rebuild or a
production publication.

The tables retain filename readings separately from `source_*` assertions, even
when Congress or document types disagree. `publication_type` is the normalized
publication code; `publication_code` retains the filename spelling. The redundant
`publication_code_code` column is omitted when all its values are represented by
`publication_type`. Empty response bodies do not identify documents or merge
unrelated URLs. Known API summary and error endpoints retain their source-record
role instead of becoming document subjects.

A successful capture means retained bytes passed basic format checks, not verified substantive
content or a parsed document model. A captured HTML wrapper and its download links
have separate results. Failures retry after one day; 404/410 responses and HTML
without discovered files retry after seven days.

The filename table records how many capture rows its build consumed. Publication
uploads both immutable tables, validates their matching `catalog_id` values,
then conditionally selects the pair through `indexes/catalog.json`. Failed or
interrupted uploads leave the prior selected pair readable. A competing writer
cannot replace a newer selection using an older snapshot. Readers reject corrupt
selected files and mismatched IDs; they do not fall back to unselected root files.
Capture logs remain intact.
Rebuilds consume the capture-index snapshot read at startup. Concurrently added
captures remain intact and enter the next rebuild. Receipts not yet referenced
by that index still require the acquisition path's interrupted-run recovery.
Missing referenced receipts fail the rebuild; absent or oversized source bodies
leave the affected interpretations unavailable. Reads use the existing bounded,
digest-checked body reader. No full-corpus runtime or memory bound is established
by the focused tests.

Saved URLs are not periodically refreshed. Replaced files at the same URL need
an explicit refresh policy, separate from this missing-file backfill. Retained
bodies also obey the inspection size limit; oversized ones remain retained and
are recorded as `inspection_deferred`, without a source refetch. Normal table updates use receipt metadata and filenames. `--inspect-bodies`
explicitly enables retained XML/format and PDF-cover inspection; it does not
transcribe recordings or publish the dashboard. The published filename table
supplies reusable source context, without separate source or filename checkpoints.

Receipt batches checkpoint every 100 results and at normal shutdown. Interrupted
index publication recovers from those receipts on the next run. A hard stop can
repeat the uncheckpointed work. Conditional index writes reject competing writers;
the workflow also serializes its own runs. The initial mirror upload must finish
before this workflow starts, and local mirror indexes must not be uploaded over
newer CI indexes.

Install `packages/congress_api[archive]` for PyArrow, the S3 client and house-naming. GitHub Actions
requires `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `ZYTE_TOKEN` secrets; the
workflow supplies `CLOUDFLARE_ACCOUNT_ID`. The R2 credential needs object read/write
access only to `congressional-tech-raw`. The workflow becomes active after it reaches
`main`. Successful runs attach a JSON summary to the Actions log; failures remain
visible in the failed step and any published capture receipts.

Read-only planning against a local mirror:

```bash
python -m congress_api.cli.raw_sync --plan-only \
  --local-mirror .cache/congressional-tech-raw --summary raw-capture-plan.json
```

### 1. Congress.gov meeting mirror

```bash
congress-meetings --output-path congress_meetings.jsonl.gz --nthreads 5
```

Lists House, Senate, and joint meetings from the 112th Congress onward. Joint committees use chamber `nochamber`. Incremental runs use the newest stored `updateDate` with a two-day overlap. Failures are tracked in a sibling `.pending.json` file for retry; unparseable list pages are retained via `retention.rejected_pages.retain_rejected_page` (also used by `congress-committees`).

When a detail request exhausts retries with HTTP 500, or a successful response
cannot decode as JSON, the collector requests XML through the same paced gateway.
`meeting_from_xml` maps known fields to the meeting model and retains exact XML
bytes in `_source_xml`. Missing/refused/rate-limited endpoints do not trigger
XML recovery. Unusable XML retains the previous meeting, failed bytes and retry
URL; a recovered meeting must match the requested identity.

Default output path: `congress_shared` `DEFAULT_MEETINGS_FILE`.

### 2. Official committee snapshots

```bash
congress-committees --meetings-path congress_meetings.jsonl.gz --output-path committees.jsonl.gz
```

Optional `--gpo-path` adds GovInfo context. Refreshes the newest two Congresses
present in the inputs plus any missing Congress. Each snapshot retains the
Congress-specific `committee` list entry and a separate `detail` containing
history, website, linked counts, parent/subcommittee references and unknown
publisher fields. `detail_url` and `detail_retrieved_at` identify that observation.

The detail endpoint spans Congresses: its current status/type never replaces the
historical list values. Each endpoint is fetched once per run when missing or
represented in a refreshed Congress; other saved details are reused. A failed
detail request preserves the previous snapshot. Invalid detail JSON is retained
in the rejected-response sidecar. Writes gzip JSONL only after collection succeeds.

### 3. GovInfo hearing pipeline

```bash
gpo-fetch --output-path gpo_hearings.csv --nthreads 4
gpo-match --tinydb_dir DIR --meetings PATH --output-path gpo_hearing_videos.csv
gpo-transcripts --out-dir ~/transcripts --congress 118
```

`gpo-fetch` incrementally lists CHRG packages, parses MODS, and (113th+) reads transcript HTML for dates and title-page committee names. `--full-relist`, `--min-congress`, `--refresh-limit`, and `--evidence-path` control scope and retained bytes. `python -m congress_api.replay.gpo` backfills CSV columns from cached evidence without live requests.

`gpo-match` scores YouTube and offsite video candidates against meetings on disk. `gpo-transcripts` skips existing files and very short text unless the HTML still contains a complete proceeding.

### 4. Weekly chamber source readers + inventory

Run in order (see [meeting state](../../docs/youtube-coverage/meeting-state.md)):

1. **`house-committee-sites`** — requires `--committees`, `--state-dir`, `--output-dir`. Collects every discoverable event across all available history, with no native-meeting prerequisite or date cutoff. `--limit` bounds requests and saves the remaining queue; `--site` limits a run to named directory hosts.
2. **`house-meeting-records`** — requires `--gpo-path`, `--meetings`, `--state-dir`, `--output-dir`. Optional `--seed-cache`, `--offline`, `--as-of`, `--refresh-limit`, `--limit`, `--zyte`, `--threads`.
3. **`senate-meeting-records`** — same shared flags via `cli.common.source_args`; optional `--site`, `--since`, `--refresh-limit`, `--limit`.
4. **`meeting-inventory`** — joins meetings, GPO CSV, video match CSV, TinyDB/YouTube inputs, House/Senate CSVs from `--output-dir`, optional caption indexes (`--youtube-caption-index`, `--senate-caption-index`), and `--recordings`.

The House site collector uses `detail.committeeWebsiteUrl` from the retained
Congress.gov directory, including former committees. It follows literal event
links, pagination, offered archive-year filters, sitemaps and supported public
calendar APIs. Explicitly linked official minority/archived sites and official
homepage redirects retain their relationship to the directory entry. It does
not guess document filenames or traverse arbitrary external sites.

```bash
python -m congress_api.cli.house_sites \
  --committees pipeline-data/congress_committees.jsonl.gz \
  --state-dir pipeline-data/meeting-inventory --output-dir apps/committee_youtube/data \
  --limit 3000 --refresh-limit 450
```

`house-sites.json.gz` retains exact HTML/JSON, request receipts, parsed event
pages, discovered links and each site's pending queue. Its CSV views are
`house_site_events.csv` and `house_site_documents.csv`; the small
`house_site_coverage.csv` updates at each checkpoint. Unmatched pages and pages
with unrecognized dates remain in those outputs; an unknown date is never
replaced with an article publication date. Pagination compares actual listing
rows where available, so distinct bills can refer to the same hearing. Query
parameter order is normalized only for comparison; original URLs remain in
receipts and queue entries. Repeated records on different pages fail visibly.
404 links, unavailable optional indexes and failed requests have separate
coverage counts. A drained discovered queue does not prove the publisher has
exposed every historical event. `--offline` only reads saved state. After stopping
collection, `--offline --reparse` rebuilds parsed readings from the retained
original bodies without HTTP requests. It preserves receipts, request times and
pending work, and restores misclassified listing pages to discovery evidence.
Retries append request receipts, and resolved errors retain their earlier
diagnostics in `resolved_errors`.

The daily workflow refreshes the official directory before these readers and
continues up to 3,000 House site requests per run. The request limit is not a
historical cutoff. Existing event refreshes reuse the Senate age-based schedule.
A partial failure saves the queue and the last usable pages. Raw capture receives
this state as another seed; this collector itself downloads no linked files.

The XML reader's `--committees` argument enables its **retained-page fallback**.
It uses these same site observations when central documents are absent, the
repository check fails, or `--failed-urls PATH` identifies a failed document URL
(one URL per line). Matching requires the same official committee and page date,
plus an explicit House event link or the native title's subject words. Ambiguous
matches stay unassigned. Added links keep their page URL, digest and selector;
original XML links remain intact, and alternate URLs are not declared byte
identical. Complete unmatched site events remain available in the separate site
outputs and raw-source context; they are not fabricated Congress.gov meetings.

House and Senate share document-link/context readers, refresh scheduling, HTTP
pacing and state/bundle retention. The XML fallback performs no extra committee
HTTP requests. Energy & Commerce's Next.js event fields and browser-style JSON
POST calendar are supported explicitly, including embedded testimony links and
labeled attachment records. HTML opening statements qualify through their own
labels or event sections. Witness associations use the link's own card or
explicit witness line; navigation links and feeds are excluded. Listing-page
dates do not establish an event, and generic publication dates remain unknown.

Shared source flags (`source_args`): `--meetings`, `--state-dir`, `--output-dir`, `--seed-cache`, `--offline`, `--as-of`.

Outputs include `hearing_text_sources.csv`, `meetings_without_records.csv`, `meeting_completeness.csv`, and `meeting_witnesses.csv`. Caption probes, MODS/PDF witness parses, and Senate day checks live in `--state-dir/inventory.json.gz`.

The [offline behavior matrix](../../docs/congress-api-contracts.md#offline-behavior) explains saved-state requirements and failure behavior.

Offline replay (no HTTP): `python -m congress_api.replay.house`, `python -m congress_api.replay.senate`.

### 5. Transcripts

```bash
hearing-transcribe --gpo-package CHRG-118hhrg54254 --out-dir ~/out
hearing-transcribe --event-id 116xxx --video-id VIDEO_ID --out-dir ~/out
hearing-transcribe --senate-url "https://www.senate.gov/isvp/?comm=epw&filename=..." --event-id 116xxx --out-dir ~/out
hearing-transcribe --audio path/to/file.mp3 --event-id 116xxx --out-dir ~/out
```

`--gpo-package` alone parses the GovInfo print. Recording paths need `--event-id` or `--gpo-package` for roster context. Gemini (`gemini-3.8-flash`) transcribes 25-minute windows; outputs use `schema_version` `1.0` and retain optional capture metadata under `{out_dir}/source/`.

### 6. Senate captions

```bash
senate-captions --out-dir ~/hearing-text/senate --urls-file links.txt
```

Downloads English WebVTT from ISVP HLS (archive and live paths). URL helpers live in `parsers.senate_player` (`COMM`, `STREAM`, `LIVE_ID`, `archive_url`, `live_url`).

### 7. Filename analysis (separate package)

Use [house-naming](../house-naming/FILENAME_PATTERNS.md) for literal filename
extraction, typed results and corpus analysis. `congress_api` supplies no filename
parser or bill-code facade.

When surname context is needed, prepare it from the source legislator model:

```python
import json
from pathlib import Path
from congress_api.models.legislators import member_surnames_by_congress
from congress_api.parsers.legislators import parse_legislators

members = parse_legislators(Path("legislators.json").read_bytes())
Path("member-surnames.json").write_text(json.dumps(member_surnames_by_congress(members)))
```

Pass that JSON to `house-naming extract --member-surnames` or
`house-naming-corpus --member-surnames`. The naming package never imports the raw
legislator reader.

### Retired exploration tools

The unused Congress TinyDB commands and aliases were removed after an
[intent audit](../../docs/legacy-congress-removal.md). XML meeting recovery and
full committee detail/history capture now belong to the production collectors.
The independent YouTube collectors remain active.

`adapters/` modules translate retained sources into [`committee-meeting`](../committee_meeting/README.md) records with provenance. The [`committee_explorer` exporter](../../apps/committee_youtube/README.md) publishes browser data; collectors do not publish the site directly.

## Default paths

From `congress_shared.globals` (package-relative, not cwd-relative):

| Constant | Relative path |
| --- | --- |
| `DEFAULT_GPO_HEARINGS_FILE` | `data/gpo_hearings.csv` |
| `DEFAULT_MEETINGS_FILE` | `data/congress_meetings.jsonl.gz` |
| `DEFAULT_HEARING_VIDEOS_FILE` | `data/gpo_hearing_videos.csv` |
| `DEFAULT_TINYDB_DIR` | `data/` |
| `DEFAULT_CHANNELS_CSV` | `youtube/youtube-accounts.csv` |

## Module reference

### Shared clients and utilities

- `transport.http` / `transport.zyte` provide retries, pacing and optional Zyte access.
- `parsers.congress` parses typed Congress.gov XML; `meeting_from_xml` retains the original bytes.
- `parsers.xml` owns BOM-safe XML reading and ordered typed XML conversion.
- `parsers.witness_names` and `parsers.speaker_names` read person-name tokens for source and transcript interpretation.
- `matching.committees` owns `parent_code`, `codes_of` and recording aliases.
- `matching.meetings` owns meeting type, access, hearing eligibility and inventory scope, including the source field behind each classification.

### Filename parsing

Filename extraction, GovInfo vocabulary, typed results and corpus tooling belong
to [house-naming](../house-naming/README.md). This package only prepares the
optional Congress-keyed surname vocabulary from raw legislator records.

### `models/`

`models/__init__.py` exports **`SourceModel`**. Submodule map: [SOURCE_MODELS.md](SOURCE_MODELS.md). Highlights:

| Module | Role |
| --- | --- |
| `base`, `content`, `xml` | Shared strict Pydantic base, raw bytes, XML tree |
| `congress`, `congress_xml` | Congress.gov JSON/XML API shapes |
| `gpo` | MODS, listings, evidence, METS manifest |
| `house`, `senate` | Chamber site parse results |
| `documents` | Witness-list PDF/MODS readings |
| `media` | Senate player, HLS, WebVTT, caption receipts |
| `legislators` | unitedstates/congress-legislators JSON |
| `transcription` | Shared `Transcript`, Gemini/YouTube capture models |
| `transport` | Zyte API response envelope |

### `adapters/` (offline)

Each adapter exposes a **`records(...)`** (or domain-specific) entry that returns normalized structures for the explorer pipeline:

| Module | Source |
| --- | --- |
| `common` | `AdapterContext`, digests, material helpers |
| `meetings` | Full Congress.gov meeting payloads |
| `committees`, `committee_metadata`, `committee_adjustments` | Committee hierarchy and curated overrides |
| `house`, `senate`, `gpo` | Retained chamber/GovInfo payloads |
| `inventory`, `findings`, `video_matches`, `recordings`, `transcripts` | Inventory observations, print links, manual associations, supplied transcript JSON bytes |

### Provider-specific readers and recovery

| Source | Interpret supplied data | Acquire and retain | Reprocess saved inputs |
| --- | --- | --- | --- |
| Congress.gov | `parsers.congress`; models under `models.congress` / `models.congress_xml` | `acquisition.meetings`, `acquisition.committees`, `retention.meetings`, `retention.rejected_pages` | Existing retained JSON/XML is consumed by the adapters |
| House | `parsers.house_xml`, `parsers.house_documents`, `parsers.house_evidence`, `parsers.house` | `acquisition.house`, `retention.house`, `retention.tables` | `replay.house` |
| Senate pages | `parsers.senate_page`, `parsers.senate`; associations in `matching.senate` / `matching.senate_pages` | `acquisition.senate`, `retention.senate`, `retention.tables` | `replay.senate` |
| GovInfo | `parsers.gpo`, `parsers.gpo_hearings`; corrections in `matching.gpo_committees` / `matching.reviewed_committees` | `acquisition.gpo`, `retention.gpo` | `replay.gpo` |
| Witness lists | `parsers.witness_pdf`; digest-keyed manual readings in `parsers.reviewed_witness_lists` | `acquisition.gaps`, `retention.tables` | Retained observations feed `matching.completeness` |
| Captions | `parsers.senate_player`, `parsers.captions`; availability in `matching.captions` | `transcripts.senate`, `transport.senate`, `retention.captions` | Retained timed segments remain available to parsers |
| Published/generated transcripts | `parsers.gpo_text`, `parsers.gemini`; shared types in `models.transcription` | `transcripts.gpo`, `transcripts.generate`, `transcripts.context`; media/model access in `transport.audio` / `transport.gemini` | Supplied transcript bytes feed `adapters.transcripts` |

`retention.rejected_pages.retain_rejected_page` preserves rejected listing/detail
JSON without replacing a valid snapshot. GPO CSV rows remain summaries; complete
native MODS models and retained bodies carry source evidence. Transcript rendering
lives in `transcripts.render`; generated responses are retained before interpretation.

## Import fences

`[tool.congress-api.import-fences]` in `pyproject.toml` lists which responsibility
folders each folder may import. `tests/test_congress_api_imports.py` enforces the
list in the normal test/CI run, including absolute, relative, aliased and
function-local imports. A new folder requires an explicit policy.

Models depend only on models. Parsers may also use models, and matching may use
parsers and models. Adapters can use these three groups and `committee_meeting`,
but cannot fetch data or read retention modules. Collection and transcript
workflows can use storage and transports. Command wiring lives at the outside
of these dependencies. No source module may depend on the explorer application.

Run the focused boundary checks with:

```bash
python -m pytest tests/test_congress_api_imports.py tests/test_congress_api_boundaries.py -q
```

## Tests

Install the optional extra, then run targeted suites (paths from package docs):

```bash
uv pip install -e "packages/congress_api[test]"
uv pip install -e "packages/house-naming[test]"
python -m pytest packages/house-naming/tests tests/test_filename_patterns.py -q
python -m pytest tests packages/committee_meeting/tests -q
```

See [source verification](SOURCE_MODELS.md#verification-and-limits) for fixture coverage,
known limits and retained evaluation evidence. Run the suites above for current results.

## Package root files

- **`pyproject.toml`** — dependencies, uv path sources, `[project.scripts]`.
- **`package.json`** / **`turbo.json`** — monorepo workspace only.
- Editable installs may create `src/congress_api*.egg-info/` (gitignored); `entry_points.txt` mirrors console scripts.
