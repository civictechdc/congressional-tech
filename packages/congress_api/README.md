# congress-api

`congress-api` collects congressional committee hearing metadata from Congress.gov, GovInfo, chamber committee sites, and Senate ISVP video. It retains publisher-shaped source records, joins them into meeting inventories, and can produce normalized transcripts. Twelve console scripts are the primary interface; library code under `src/congress_api/` backs those commands and the [`committee-meeting`](../committee_meeting/README.md) adapters.

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
| [SOURCE_MODELS.md](SOURCE_MODELS.md) | Pydantic source models, parsers, and the path to `adapters/` |
| [SOURCE_MODEL_REVIEW.md](SOURCE_MODEL_REVIEW.md) | September 2026 manual review log and test counts |
| [Filename tooling](../house-naming/FILENAME_PATTERNS.md) | Regex filename parsing, corpus audits, residuals |
| [WITNESS_PDF_DATASET.md](WITNESS_PDF_DATASET.md) | House witness-list XML ↔ PDF pairing inventory |
| [PDF_EXTRACTOR_COMPARISON.md](PDF_EXTRACTOR_COMPARISON.md) | Witness-list PDF extractor benchmark (keeps `pypdf`) |
| [committee-meeting](../committee_meeting/README.md) | Canonical normalized meeting model |
| [Meeting state & refresh](../../docs/youtube-coverage/meeting-state.md) | Pipeline state directories and refresh rules |
| [REFACTORING_PLAN.md](REFACTORING_PLAN.md) | Refactor scope, sequence and completion evidence |
| [Compatibility and maintenance](../../docs/congress-api-contracts.md) | Stable commands/artifacts, CI, versions, offline behavior, identity and replay safeguards |

## Install

From the repository root:

```bash
uv pip install -e packages/committee_meeting -e packages/congress_shared \
  -e packages/youtube_api -e packages/congress_api
```

Optional tests: `uv pip install -e "packages/congress_api[test]"` (adds `pytest>=9,<10`).

Runtime dependencies include `committee-meeting`, `congress-shared`, `youtube-api`, `pydantic`, `lxml`, `requests`, `pypdf[fonts]`, `tinydb`, `google-genai`, and `yt-dlp`. Sibling packages resolve through `[tool.uv.sources]` in `pyproject.toml`.

`congress-shared` supplies API key loading, default data paths, and `congress_metadata.json`. `youtube-api` opens committee YouTube TinyDB files and maps `systemCode` to channel handles.

`hearing-transcribe` expects `ffmpeg` and `ffprobe` on `PATH`. YouTube and Senate audio paths use `yt-dlp`.

Filename parsing and corpus tooling live in the independent [house-naming package](../house-naming/README.md); they are not congress-api runtime dependencies.

## Credentials and environment

Congress.gov and the GovInfo collection API share one [data.gov](https://api.data.gov) key. `congress_shared.auth.load_congress_api_key` checks, in order:

1. `--congress-api-key` (via `parse_known_args`, even when the command did not declare the flag)
2. `DATA_GOV_API_KEY`
3. `~/.data.gov.api.key`, then `~/.data.gov.key`

| Variable / flag | Used by |
| --- | --- |
| `DATA_GOV_API_KEY` / `--congress-api-key` | `congress-meetings`, `congress-committees`, `congress-fetch`, `gpo-fetch`, … |
| `GEMINI_API_KEY` | `hearing-transcribe` (Gemini windows) |
| `YOUTUBE_API_KEY` | Optional video duration in `hearing-transcribe` (else `yt-dlp`) |
| `ZYTE_TOKEN` | `congress_api.zyte` / `http.get_with_retry` for bot-challenged hosts; `house-meeting-records --zyte` |

`hearing-transcribe --proxy` is forwarded to `yt-dlp`.

## HTTP policy

This is the authoritative policy matrix. No clients are merged by the refactor.

| Call path / hosts | Pacing, retries and timeout | Zyte and metadata |
| --- | --- | --- |
| `http.get_with_retry`: House repository, GovInfo, Congress.gov and committee sites | Direct starts: 1.2 s for `docs.house.gov`, 0.2 s elsewhere; 3 attempts, 60 s timeout. Retry 202/403/408/429/500/502/503/504/520 and request exceptions; other unallowed statuses stop. Next-start backoff is 2^(attempt+1) s; direct House 403 waits 60 s. `allowed` defines caller-confirmed statuses | Explicit `through_zyte=True`, not automatic fallback. Zyte skips local pacing; returned response is synthetic. `response_metadata` retains all available parsed header fields and states fidelity; callers retain metadata separately |
| `meetings.get` and committee snapshot collection: Congress.gov | Delegates to the same gateway with **5 attempts**, injects API key/JSON format, decodes JSON | No Zyte option on this wrapper; safe gateway errors omit query secrets |
| `api.request_source`: legacy Congress.gov JSON/XML client | One bare `requests.get`; no explicit timeout, pacing or retry. `raise_for_status`, JSON first, XML fallback on JSON decode failure | No Zyte. Returns a source model, not a transport receipt; compatibility dictionaries retain original XML |
| `senate.captions.sess`: ISVP playlists and WebVTT | Module-level `requests.Session`, HTTPS `pool_maxsize=32`; default 3 immediate attempts, 30 s timeout. 404 is absence, empty 200 retries, exhausted failures raise | No Zyte. Typed media captures retain status/text/raw body; not gateway response-header metadata |
| `transcribe.main`: GPO HTML and YouTube duration | Direct requests: 60 s for GPO HTML, 30 s for YouTube JSON; no shared retry/pacing. yt-dlp is the duration fallback | No Zyte; GPO HTML is retained separately |
| `transcribe.metadata`: GovInfo MODS and unitedstates GitHub Pages legislators | `urllib.request.urlopen`, 60 s timeout, explicit User-Agent; legislators cached in memory, MODS fetched on demand; no gateway retries | No Zyte; source bytes/models retained by the metadata path |
| Audio / Gemini | yt-dlp/ffmpeg and google-genai own their transports; Gemini has its existing application retry loop | Not part of the shared HTTP gateway |

A 200 challenge page is not automatically successful source parsing. Collector
validation decides usability. Failed checks remain failures; they must not
become empty source records. Host locks control request starts, not in-flight
completion. A supplied session is used directly; `session=None` uses a thread-local
session. See `tests/test_http_policy.py`, `test_http_response_metadata.py`,
`test_zyte_capture.py`, and caption source tests.

## Package layout

```
packages/congress_api/
├── README.md                 # This file
├── pyproject.toml            # Metadata, dependencies, console scripts
├── package.json              # @ct/congress-api workspace marker
├── turbo.json                # Extends repo Turborepo config
├── *.md                      # Source-model specs (see table above)
└── src/congress_api/
    ├── api.py                # Congress.gov v3 client (TinyDB fetch path)
    ├── meetings.py           # congress-meetings → gzip JSONL
    ├── committee_metadata.py # congress-committees → committee snapshots
    ├── congress_source.py    # Parse Congress.gov JSON/XML bodies
    ├── http.py, zyte.py      # Retries, pacing, optional Zyte
    ├── committees.py, witnesses.py
    ├── xml.py, xml_to_dict.py
    ├── adapters/             # Offline source → committee-meeting records
    ├── retention/            # Production rejected-page retention
    ├── legacy/               # Optional TinyDB fetch/analyze and conversion
    ├── analyze/, fetch/      # Compatibility imports for legacy code
    ├── house/                # docs.house.gov gap fill
    ├── senate/               # Committee sites + ISVP captions
    ├── gpo/                  # GovInfo CHRG packages
    ├── inventory/            # Weekly meeting join
    ├── transcribe/           # GPO print parse + Gemini transcription
    └── models/               # Pydantic source models (see SOURCE_MODELS.md)
```

Packages with an `__init__.py`: `adapters`, `house`, `senate`, `inventory`, `transcribe`, `models`. Other directories are regular Python packages via setuptools `src` layout.

## Console scripts

| Script | Module | Primary output |
| --- | --- | --- |
| `congress-committees` | `committee_metadata` | Gzip JSONL of `CommitteeSnapshot` rows |
| `congress-meetings` | `meetings` | `congress_meetings.jsonl.gz` |
| `congress-fetch` | `legacy.fetch.main` | TinyDB committee summaries + in-memory meeting URL list |
| `congress-analyze` | `legacy.analyze.main` | stdout: YouTube handles for committees with events |
| `house-meeting-records` | `house.records` | House CSVs + `house.json.gz` state |
| `senate-meeting-records` | `senate.records` | Senate CSVs + `senate.json.gz` state |
| `meeting-inventory` | `inventory.main` | Inventory CSVs + `inventory.json.gz` |
| `gpo-fetch` | `gpo.fetch` | `gpo_hearings.csv` (+ optional evidence store) |
| `gpo-transcripts` | `gpo.transcripts` | One `.txt` per package under `--out-dir` |
| `gpo-match` | `gpo.match` | `gpo_hearing_videos.csv` + coverage CSV |
| `senate-captions` | `senate.captions` | WebVTT text, receipts, `captions_index.csv` |
| `hearing-transcribe` | `transcribe.main` | `{stem}.json` + `{stem}.gpo.txt` |

`congress_shared.globals.add_global_args` adds `--tinydb_dir` where used. Commands that call `parse_known_args` leave `--congress-api-key` available for the key loader.

### Module-only CLIs

| Invocation | Role |
| --- | --- |
| `python -m congress_api.house.replay` | Upgrade retained House evidence from cache (no network) |
| `python -m congress_api.senate.replay` | Upgrade retained Senate pages from cache |
| `python -m congress_api.gpo.replay` | Merge cached MODS/HTML into GPO CSV and evidence |
| `python -m congress_api.senate.captions` | Same as `senate-captions` |
| `python -m congress_api.json_to_tinydb` | Legacy one-off TinyDB loader (hard-coded paths; not in `[project.scripts]`) |

## Common workflows

### 1. Congress.gov meeting mirror

```bash
congress-meetings --output-path congress_meetings.jsonl.gz --nthreads 5
```

Lists House, Senate, and joint meetings from the 112th Congress onward. Joint committees use chamber `nochamber`. Incremental runs use the newest stored `updateDate` with a two-day overlap. Failures are tracked in a sibling `.pending.json` file for retry; unparseable list pages are retained via `retention.rejected_pages.retain_rejected_page` (also used by `congress-committees`).

Default output path: `congress_shared` `DEFAULT_MEETINGS_FILE`.

### 2. Official committee snapshots

```bash
congress-committees --meetings-path congress_meetings.jsonl.gz --output-path committees.jsonl.gz
```

Optional `--gpo-path` adds GovInfo context. Refreshes the newest two Congresses present in the meetings file plus any missing Congress. Writes gzip JSONL only after a successful collection.

### 3. GovInfo hearing pipeline

```bash
gpo-fetch --output-path gpo_hearings.csv --nthreads 4
gpo-match --tinydb_dir DIR --meetings PATH --output-path gpo_hearing_videos.csv
gpo-transcripts --out-dir ~/transcripts --congress 118
```

`gpo-fetch` incrementally lists CHRG packages, parses MODS, and (113th+) reads transcript HTML for dates and title-page committee names. `--full-relist`, `--min-congress`, `--refresh-limit`, and `--evidence-path` control scope and retained bytes. `python -m congress_api.gpo.replay` backfills CSV columns from cached evidence without live requests.

`gpo-match` scores YouTube and offsite video candidates against meetings on disk. `gpo-transcripts` skips existing files and very short text unless the HTML still contains a complete proceeding.

### 4. Weekly chamber source readers + inventory

Run in order (see [meeting state](../../docs/youtube-coverage/meeting-state.md)):

1. **`house-meeting-records`** — requires `--gpo-path`, `--meetings`, `--state-dir`, `--output-dir`. Optional `--seed-cache`, `--offline`, `--as-of`, `--refresh-limit`, `--limit`, `--zyte`, `--threads`.
2. **`senate-meeting-records`** — same shared flags via `inventory.common.source_args`; optional `--site`, `--since`, `--refresh-limit`, `--limit`.
3. **`meeting-inventory`** — joins meetings, GPO CSV, video match CSV, TinyDB/YouTube inputs, House/Senate CSVs from `--output-dir`, optional caption indexes (`--youtube-caption-index`, `--senate-caption-index`), and `--recordings`.

Shared source flags (`source_args`): `--meetings`, `--state-dir`, `--output-dir`, `--seed-cache`, `--offline`, `--as-of`.

Outputs include `hearing_text_sources.csv`, `meetings_without_records.csv`, `meeting_completeness.csv`, and `meeting_witnesses.csv`. Caption probes, MODS/PDF witness parses, and Senate day checks live in `--state-dir/inventory.json.gz`.

The [offline behavior matrix](../../docs/congress-api-contracts.md#offline-behavior) explains saved-state requirements and failure behavior.

Offline replay (no HTTP): `python -m congress_api.house.replay`, `python -m congress_api.senate.replay`.

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

Downloads English WebVTT from ISVP HLS (archive and live paths). URL helpers live in `senate/isvp.py` (`COMM`, `STREAM`, `LIVE_ID`, `archive_url`, `live_url`).

### 7. Filename analysis (separate package)

Use [house-naming](../house-naming/FILENAME_PATTERNS.md) for literal filename
extraction, typed results and corpus analysis. `congress_api` supplies no filename
parser or bill-code facade.

When surname context is needed, prepare it from the source legislator model:

```python
import json
from pathlib import Path
from congress_api.models.legislators import parse_legislators, member_surnames_by_congress

members = parse_legislators(Path("legislators.json").read_bytes())
Path("member-surnames.json").write_text(json.dumps(member_surnames_by_congress(members)))
```

Pass that JSON to `house-naming extract --member-surnames` or
`house-naming-corpus --member-surnames`. The naming package never imports the raw
legislator reader.

### 8. Legacy TinyDB explore path

```bash
congress-fetch --chamber house --congress_number 119 --tinydb_dir /path/to/tinydb
congress-analyze --chamber house --congress_number 119 --tinydb_dir /path/to/tinydb
```

`congress-fetch` caches committee summaries and details, then lists meeting URLs (it does not call `CongressEventFetcher.process_events()`). Full meeting documents require a separate `process_events()` call on `CongressEventFetcher`. `congress-analyze` joins cached events to committees and prints YouTube TinyDB handles.

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

- **`api.py`** — `congress_api_get`, `generic_request`, `request_source` for the TinyDB fetch/analyze path (JSON preferred; XML via `xml_to_dict`).
- **`meetings.py`** — `congress-meetings`; thin wrapper over `http.get_with_retry`, with five attempts (the gateway defaults to three).
- **`congress_source.py`** — `parse_congress_xml`, `parse_response` → typed Congress.gov models.
- **`http.py` / `zyte.py`** — `get_with_retry`, optional Zyte extract for rate-limited hosts.
- **`committees.py`** — `parent_code`, `codes_of`, recording aliases.
- **`witnesses.py`** — `witness`, `person_key`, `is_name` for GPO and page lines.
- **`committee_metadata.py`** — `collect`, `congress-committees`.
- **`xml.py` / `xml_to_dict.py`** — BOM-safe parse, MODS helpers, legacy XML→dict.
- **`json_to_tinydb.py`** — ad-hoc migration script.

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
| `inventory`, `findings`, `video_matches`, `recordings`, `transcripts` | Inventory observations, print links, manual associations, on-disk transcript JSON |

### `legacy/` and compatibility imports

- **`legacy/fetch/`** — TinyDB committee/event fetchers and `congress-fetch`.
- **`legacy/analyze/main.py`** — `congress-analyze`.
- **`legacy/committee*.py`** — shared committee objects and TinyDB details; neither command owns them.
- **`legacy/json_to_tinydb.py`** — ad-hoc conversion with existing hard-coded paths.
- **`fetch/`, `analyze/`, `json_to_tinydb.py`** — compatibility aliases to those implementations, preserving shared module state.
- **`retention/rejected_pages.py`** — production `retain_rejected_page`; `fetch.rejected` keeps its old import available.

These explore tools have no scheduled removal and receive no new features.
See the [legacy decision](../../docs/adr/tinydb-explore-sunset.md).

### `house/`

- **`records`** — `house-meeting-records` (`parse_args_and_run`).
- **`source`** — XML → `HouseMeetingXML` / `HouseWitnessListXML`.
- **`repository`** — URL and witness extraction from XML/HTML (no HTTP).
- **`evidence`** — retained `HouseEvidence` (schema 1.1).
- **`replay`** — offline evidence upgrade.

### `senate/`

- **`records`** — `senate-meeting-records`.
- **`pages`** — HTML layouts, witnesses, documents, listing constants.
- **`matching`** — GPO package / bill-id association to native meetings.
- **`corrections`** — curated date overrides (`selected_date`).
- **`isvp`** — player URL parse/build, HLS URLs.
- **`captions`** — `senate-captions`, WebVTT merge and index.
- **`replay`** — offline parser upgrades.

### `gpo/`

- **`fetch`** — `gpo-fetch`, `GpoHearing` rows, `PARSER_VERSION` `"3"`.
- **`source`** — bytes → `ModsDocument`, transcript HTML, manifest.
- **`evidence`** — gzip JSONL upstream retention.
- **`transcripts`** — `gpo-transcripts`.
- **`match`** — `gpo-match`, scoring and overrides.
- **`reviewed_committees`** — curated committee codes when MODS lacks authority IDs.
- **`replay`** — offline CSV/evidence merge.

### `inventory/`

- **`main`** — `meeting-inventory` orchestrator.
- **`common`** — CSV/state I/O, `source_args`, refresh scheduling.
- **`text_sources`** — per-meeting text and video index.
- **`prints`** — GPO print ↔ meeting ownership rules.
- **`captions`** — caption availability and saved observation imports; old probe entry delegates to acquisition.
- **`completeness`** — witness and completeness rows.
- **`acquisition`** — MODS/PDF capture, Senate HEAD probes and day scheduling; defaulted `get=` for tests.
- **`witness_lists`** — byte-only MODS/PDF parsing (`parse_pdf_observation`, `parse_mods_observation`); old acquisition entry delegates.
- **`reviewed_witness_lists`** — digest-keyed manual PDF readings.

### `transcribe/`

- **`main`** — `hearing-transcribe`, `from_gpo`, Gemini orchestration.
- **`schema`** — GPO layout render (`render_gpo`); types in `models/transcription`.
- **`gpo_parse`** — plain-text GPO → `Transcript`.
- **`metadata`** — `HearingContext`, roster from meetings/GPO/legislators.
- **`audio`** — ffmpeg/yt-dlp/Senate HLS → chunked MP3.
- **`gemini`** — windowed Gemini calls, split/retry on truncation.
- **`names`** — token/surname matching for roster placement.

## Tests

Install the optional extra, then run targeted suites (paths from package docs):

```bash
uv pip install -e "packages/congress_api[test]"
uv pip install -e "packages/house-naming[test]"
python -m pytest packages/house-naming/tests tests/test_filename_patterns.py -q
python -m pytest tests packages/committee_meeting/tests -q
```

See [SOURCE_MODEL_REVIEW.md](SOURCE_MODEL_REVIEW.md) for the combined regression count and focused HTTP/caption suites.

## Package root files

- **`pyproject.toml`** — dependencies, uv path sources, `[project.scripts]`.
- **`package.json`** / **`turbo.json`** — monorepo workspace only.
- Editable installs may create `src/congress_api*.egg-info/` (gitignored); `entry_points.txt` mirrors console scripts.
