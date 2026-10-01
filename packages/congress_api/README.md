# congress-api

`congress-api` collects congressional committee hearing metadata from Congress.gov, GovInfo, chamber committee sites, and Senate ISVP video. It retains publisher-shaped source records, joins them into meeting inventories, and can produce normalized transcripts. Ten console scripts are the primary interface; library code under `src/congress_api/` backs those commands and the [`committee-meeting`](../committee_meeting/README.md) adapters.

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

Runtime dependencies include `committee-meeting`, `congress-shared`, `pydantic`, `lxml`, `requests`, `pypdf[fonts]`, `google-genai`, and `yt-dlp`. Sibling packages resolve through `[tool.uv.sources]` in `pyproject.toml`.

`congress-shared` supplies API key loading, default data paths, and `congress_metadata.json`. The separate `youtube-api` package collects YouTube data. These commands read its saved JSON with the standard library; TinyDB is not a congress-api dependency.

`hearing-transcribe` expects `ffmpeg` and `ffprobe` on `PATH`. YouTube and Senate audio paths use `yt-dlp`.

Filename rules and corpus tooling live in the independent [house-naming package](../house-naming/README.md).
The optional `archive` dependency group uses that package to build document tables;
ordinary source collectors do not require it.

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
runs every six hours and after `Update committee data` completes. It reads the
R2 mirror's capture and filename indexes plus available native records on
`pipeline-data`. It downloads missing URLs, follows explicit document and subtitle
links, and scans already retained bodies without refetching them. It does not
crawl site navigation or archive full video/audio files. Authenticated Congress.gov,
GovInfo collection and YouTube API requests remain with their existing collectors.

Production uses the Rust `source-fetch` reqwest worker, with **direct requests
first and one Zyte fallback when capture fails**. It starts at most **40 HTTP
requests per second** across direct requests, redirects, and fallbacks, with up
to **80 concurrent source tasks**. The rate is a shared ceiling; source latency,
archive writes, and catalog work can lower completed captures per second.
The run still limits work to 5,000 downloads or retained-body scans and 90 minutes
of collection. Manual `direct` and `zyte` modes remain available. The default
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
`indexes/captures.parquet` gains new receipt references. After saving captures, the
same run rebuilds `indexes/document-filenames.parquet` and `indexes/documents.parquet`.
The shared builder in `retention/document_index.py` reads existing source columns,
new durable receipts and current pipeline links. It retains unfetched filenames,
response-header names, redirects and parent committee/meeting metadata. New names
pass through `house_naming.Engine.extract`; unchanged names reuse saved results.
A fingerprint of the parser code and catalog invalidates that reuse when rules change.
Rebuilding tables never downloads document bodies.

A successful capture means retained bytes passed basic format checks, not verified substantive
content or a parsed document model. A captured HTML wrapper and its download links
have separate results. Failures retry after one day; 404/410 responses and HTML
without discovered files retry after seven days.

The filename table records how many capture rows its build consumed and publishes
after the document table. If either upload fails, the next run repeats that delta
even when no new downloads are needed. Both tables carry the same `catalog_id`;
readers must reject mismatched IDs (the local viewer already does). These two object
writes are not atomic: an interrupted publication can temporarily make the pair
unavailable until the next successful rebuild. Capture logs remain intact.

Saved URLs are not periodically refreshed. Replaced files at the same URL need
an explicit refresh policy, separate from this missing-file backfill. Retained
bodies also obey the inspection size limit; oversized ones remain retained and
are recorded as `inspection_deferred`, without a source refetch. This job does not
extract PDF text or publish the dashboard.

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

1. **`house-meeting-records`** — requires `--gpo-path`, `--meetings`, `--state-dir`, `--output-dir`. Optional `--seed-cache`, `--offline`, `--as-of`, `--refresh-limit`, `--limit`, `--zyte`, `--threads`.
2. **`senate-meeting-records`** — same shared flags via `cli.common.source_args`; optional `--site`, `--since`, `--refresh-limit`, `--limit`.
3. **`meeting-inventory`** — joins meetings, GPO CSV, video match CSV, TinyDB/YouTube inputs, House/Senate CSVs from `--output-dir`, optional caption indexes (`--youtube-caption-index`, `--senate-caption-index`), and `--recordings`.

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
