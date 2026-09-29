# congress-api

`congress-api` collects congressional hearing records and writes them to local files. The package talks to Congress.gov, GovInfo, and the Senate ISVP player, and it reads committee YouTube archives through `youtube-api`. Twelve console scripts are the interface. The modules under `src/congress_api/` implement those scripts.

The monorepo package name is `@ct/congress-api`. The Python package name is `congress-api`. It requires Python 3.12 or newer.

Canonical Pydantic [source models](SOURCE_MODELS.md) preserve publisher records
before normalization. Parsers return source models independently of CSV or
Parquet storage; normalization remains in `adapters/`.

## Install

From the repository root:

```bash
uv pip install -e packages/committee_meeting -e packages/congress_shared \
  -e packages/youtube_api -e packages/congress_api
```

`pyproject.toml` declares `committee-meeting`, `congress-shared`, `youtube-api`, `pydantic`, `lxml`, `requests`, `pypdf[fonts]`, `tinydb`, `google-genai`, and `yt-dlp`. The editable install above resolves the three sibling packages from this checkout.

`congress-shared` loads the data.gov API key, default file paths, and `congress_metadata.json`. `youtube-api` opens committee YouTube TinyDB files and maps a committee `systemCode` to a channel.

`hearing-transcribe` also needs `ffmpeg` and `ffprobe` on `PATH`. YouTube downloads go through `yt-dlp`.

## Credentials

Congress.gov and the GovInfo collection API share one data.gov key. `congress_shared.auth.load_congress_api_key` checks, in order:

1. `--congress-api-key`
2. the `DATA_GOV_API_KEY` environment variable
3. `~/.data.gov.api.key`, then `~/.data.gov.key`

`hearing-transcribe` reads `GEMINI_API_KEY` for Gemini. When `YOUTUBE_API_KEY` is set, video length comes from the YouTube Data API. Otherwise length comes from `yt-dlp`. `--proxy` is forwarded to `yt-dlp`.

## Commands

| Script | Module | What it writes |
| --- | --- | --- |
| `congress-committees` | `congress_api.committee_metadata` | Congress-scoped committee JSONL at `--output-path` |
| `house-meeting-records` | `congress_api.house.records` | House documents, witnesses and amendments CSVs; retained parsed state |
| `senate-meeting-records` | `congress_api.senate.records` | Senate pages, documents and witnesses CSVs; retained parsed state |
| `meeting-inventory` | `congress_api.inventory.main` | Text-source, completeness, missing-record and witness CSVs |
| `congress-meetings` | `congress_api.meetings` | `congress_meetings.jsonl.gz` |
| `congress-fetch` | `congress_api.fetch.main` | committee TinyDB files, plus an in-memory meeting-URL list |
| `congress-analyze` | `congress_api.analyze.main` | stdout: YouTube TinyDB handles for committees that have events |
| `gpo-fetch` | `congress_api.gpo.fetch` | `gpo_hearings.csv` |
| `gpo-transcripts` | `congress_api.gpo.transcripts` | one `.txt` per hearing |
| `gpo-match` | `congress_api.gpo.match` | `gpo_hearing_videos.csv` and a coverage CSV |
| `senate-captions` | `congress_api.senate.captions` | caption text plus `captions_index.csv` |
| `hearing-transcribe` | `congress_api.transcribe.main` | `{stem}.json` and `{stem}.gpo.txt` |

`congress_shared.globals.add_global_args` adds `--tinydb_dir`. `load_congress_api_key` reads `--congress-api-key` from the process arguments on its own. Commands that call `parse_known_args` leave that flag in place for the key loader.

### Committee meetings

`congress-meetings` keeps a gzip JSONL of House, Senate, and joint committee meeting detail records from `https://api.congress.gov/v3`. Joint committees use the chamber name `nochamber`. Each line is one meeting: event id, date, committees, title, type, status, witnesses, and official `videos` links. The file is sorted and keyed by the detail URL.

```bash
congress-meetings --output-path congress_meetings.jsonl.gz --nthreads 5
```

The first run lists meetings from the 112th Congress on (about 13,600 detail calls). Later runs fetch meetings Congress.gov updated since the newest `updateDate` on file, with a two-day overlap. The default path is `congress_shared`'s `data/congress_meetings.jsonl.gz`. A failed detail fetch exits 1.

`meetings.py` uses its own HTTP client, with retries on HTTP 429 and 5xx. `api.py` is the client for the TinyDB fetch and analyze path below.

### Official committee metadata and source records

`congress-committees` retains official committee lists for Congresses present in
`--meetings-path` and optional `--gpo-path`. It refreshes the newest two Congresses
and any missing Congresses, writing gzip JSONL to `--output-path` only after the
collection succeeds. Each row preserves the Congress, committee object, source
URL and retrieval time. Use `DATA_GOV_API_KEY` or the key file for this command.

The weekly source commands run in order: `house-meeting-records`,
`senate-meeting-records`, then `meeting-inventory`. All accept `--meetings`,
`--state-dir` and `--output-dir`; `--offline` requires retained results and makes
no requests. Parsed state lives on `pipeline-data`, separate from the small CSV
outputs. See [meeting state and refresh rules](../../docs/youtube-coverage/meeting-state.md)
and each command's `--help` for its additional inputs.

The `adapters/` modules translate retained source records into the
[`committee-meeting` model](../committee_meeting/README.md), preserving source
citations and native payloads. The application-owned
[`committee_explorer` exporter](../../apps/committee_youtube/README.md)
publishes the browser data. Collectors and adapters do not publish the site.

### Legacy TinyDB committees and events

`congress-fetch` runs two steps.

1. It lists committees at `committee/{chamber}` and inserts new rows in `{tinydb_dir}/committee-summaries.json` (table `committees`). It then calls `Committee.get_details` for each row. That call caches and stores details through `CommitteeDetails.store` defaults, so the file is `house-committee-details.json` in the `congress_shared` data directory, for every chamber. `store(tinydb_dir=..., chamber=...)` can write `{chamber}-committee-details.json` when a caller passes those arguments. `from_system_code` reads only the house file in that default directory.
2. It lists meetings at `committee-meeting/{congress}/{chamber}` and stores `eventId` → URL on `CongressEventFetcher.event_urls`.

```bash
congress-fetch --chamber house --congress_number 119 --tinydb_dir /path/to/tinydb
```

`--chamber` accepts `house`, `senate`, or `nochamber` (default `house`). `--congress_number` accepts 100 through 119 (default 119). The committee list function accepts `house` and `senate`; `nochamber` raises `ValueError` there. The meeting list accepts all three chambers.

Full meeting documents land in `{tinydb_dir}/events.json` (table `committee_meetings`, document id = `eventId`) when `CongressEventFetcher.process_events()` runs. `congress-fetch` stops after the URL list. `process_events` skips ids already stored, stops the batch on HTTP 429, and retries HTTP 500 once before trying the XML form of the same URL.

`congress-analyze` opens the same TinyDB files with an empty API key, attaches stored events to committees by `systemCode`, and prints `committee.youtube` for every committee that has at least one event. `--chamber` and `--congress_number` are accepted and left unused inside `main`. YouTube handles come from `youtube_api.tables.map_system_code_committee_handles`. A subcommittee uses its parent `systemCode` for that lookup.

### GovInfo hearings

`gpo-fetch` maintains `gpo_hearings.csv`, one row per CHRG package. It lists `https://api.govinfo.gov/collections/CHRG/{since}` (data.gov key required), reads public MODS at `https://www.govinfo.gov/metadata/pkg/{package_id}/mods.xml`, and, from the 113th Congress on, reads the HTML transcript once for day headers and a title-page committee name. The CSV is the cache. Later runs start from the newest `last_modified`, minus two days. `--full-relist` lists from `1990-01-01`. `--chambers` defaults to `hsj` (House, Senate, joint). Package ids look like `CHRG-118hhrg54254`.

```bash
gpo-fetch --output-path gpo_hearings.csv --nthreads 4
```

`gpo-transcripts` reads that CSV and writes `{out_dir}/{package_id}.txt`. Files already present are skipped. Stripped text shorter than 10,000 characters is a title page (often a scanned PDF) and is skipped. House and joint hearings since 2013 are about 2 GB, so the output belongs in a local directory.

```bash
gpo-transcripts --out-dir ~/transcripts --congress 118 --committee hsvr00
```

`gpo-match` joins each hearing row to committee YouTube videos and to Congress.gov meeting records already on disk. It reads `gpo_hearings.csv`, `youtube-accounts.csv`, `congress_meetings.jsonl.gz`, and `hearing_video_overrides.csv` in the `congress_shared` data directory. For row `i` of the channel CSV it opens `{tinydb_dir}/youtube_{i:02d}.json` when that file exists, and it reads tables named `youtube_videos_*`. It writes `gpo_hearing_videos.csv` and `gpo_hearing_video_coverage.csv` beside that output. Scores run from 100 (Congress.gov links the video on the meeting with this event id) down through date and title evidence. `--no-overrides` keeps automatic scores only. Status values include `full_recording`, `clips_only`, `no_video_found`, `before_channel`, `committee_not_tracked`, `not_public`, and `full_recording_offsite`.

```bash
gpo-match --tinydb_dir DIR --meetings PATH --output-path gpo_hearing_videos.csv
```

### Senate captions

`senate-captions` downloads English WebVTT from the live Senate HLS path and writes `{filename}.txt`, `{filename}.cues.txt`, and `captions_index.csv`. Index columns are `filename`, `comm`, `kind`, and `characters`. `kind` is `webvtt` or `none`. Filenames already in the index are skipped.

```bash
senate-captions --out-dir ~/hearing-text/senate \
  --urls "https://www.senate.gov/isvp/?comm=epw&filename=epw120623"
```

Recordings since about mid-2023 use the live path and carry a WebVTT track. Older archive recordings keep captions inside the video stream. This command indexes those as `none`. URL templates and the committee tables live in `senate/isvp.py`: player `comm` values (`COMM`), archive folder names (`STREAM`), and live stream ids (`LIVE_ID`).

### Transcripts

`hearing-transcribe` writes `{stem}.json` and `{stem}.gpo.txt` in the same schema, so a GovInfo print and a machine transcript can be diffed.

```bash
hearing-transcribe --event-id 116xxx --out-dir ~/hearing-text/transcripts
hearing-transcribe --video-id VIDEO_ID --event-id 116xxx --out-dir ~/hearing-text/transcripts
hearing-transcribe --senate-url "https://www.senate.gov/isvp/?comm=epw&filename=epw120623" --event-id 116xxx --out-dir ~/hearing-text/transcripts
hearing-transcribe --gpo-package CHRG-118hhrg54254 --out-dir ~/hearing-text/transcripts
```

`--gpo-package` alone fetches the GovInfo HTML and parses the print. Any recording path needs `--event-id` or `--gpo-package` so the roster is known. Gemini (`gemini-3.8-flash`) transcribes in 25-minute windows. A YouTube id is sent as video. A Senate URL or a local file is converted to 16 kHz mono MP3, chunked, and uploaded. The roster comes from the meetings JSONL, GovInfo MODS, the committee's nearest printed hearing in the same Congress, and `legislators-current.json`.

JSON `schema_version` is `1.0`. `Source.kind` on these outputs is `gpo_print` or `gemini_transcription`.

## Default paths

`congress_shared.globals` resolves these from the installed `congress_shared` package, independent of the working directory:

| Setting | Location under `congress_shared` |
| --- | --- |
| `DEFAULT_GPO_HEARINGS_FILE` | `data/gpo_hearings.csv` |
| `DEFAULT_MEETINGS_FILE` | `data/congress_meetings.jsonl.gz` |
| `DEFAULT_HEARING_VIDEOS_FILE` | `data/gpo_hearing_videos.csv` |
| `DEFAULT_TINYDB_DIR` | `data/` |
| `DEFAULT_CHANNELS_CSV` | `youtube/youtube-accounts.csv` |

## Files

`import congress_api` exports nothing. Import a submodule, or run a console script. Empty `__init__.py` files mark packages and define no API.

### Package root

- `pyproject.toml` defines the package, the dependency list, the uv path sources, and the console scripts. `readme = "README.md"` points here.
- `package.json` names the workspace package `@ct/congress-api`. It has no npm scripts. Python packaging is authoritative.
- `turbo.json` extends the repo Turborepo config and defines no local tasks.
- `main.py` (package root, beside `pyproject.toml`) prints `Hello from congress-api!` when run as a script. The installed commands are the console scripts in `pyproject.toml`.

### Shared client

- `src/congress_api/__init__.py` is empty.
- `src/congress_api/api.py` is the Congress.gov v3 helper. `congress_api_get` GETs `https://api.congress.gov/v3/{endpoint}` with a caller-supplied `api_key`, default `limit` 250, and follows `pagination.next`. `generic_request` GETs an absolute URL. JSON is preferred; a non-JSON body goes through `parse_xml_string`. Fetchers and `CommitteeDetails` use this module. `meetings.py` does its own requests.
- `src/congress_api/xml_to_dict.py` turns an XML string into a nested dict. Repeated child tags become lists. `api.py` calls `parse_xml_string` on XML responses.
- `src/congress_api/json_to_tinydb.py` is a one-off loader. Run it as `python -m congress_api.json_to_tinydb`. It reads `./congress_events_output.json` and inserts missing rows into `./congress_youtube_db.json`, table `committee_meetings`. `pyproject.toml` leaves it unregistered.
- `src/congress_api/meetings.py` is the `congress-meetings` implementation described above.
- `src/congress_api/committee_metadata.py` retains Congress-scoped committee lists.
- `src/congress_api/http.py` provides retry and host pacing for source readers; `zyte.py` supplies the optional metered fetch path.
- `src/congress_api/xml.py`, `witnesses.py`, and `committees.py` share XML, witness-name and committee-code handling across collectors and the transcriber.
- `src/congress_api/house/`, `senate/records.py`, and `inventory/` implement the weekly source commands.
- `src/congress_api/adapters/` contains the source-to-model adapters, including curated committee adjustments.

### `fetch/`

- `src/congress_api/fetch/__init__.py` is empty.
- `src/congress_api/fetch/main.py` is `congress-fetch`: `fetch_committees`, then `fetch_events` (the URL list only).
- `src/congress_api/fetch/congress_committee_fetcher.py` owns `{tinydb_dir}/committee-summaries.json`. `get_committees` calls `committee/{chamber}`. `fetch_all_committees` inserts rows whose `systemCode` is new. `return_system_code_committees_mapping` rebuilds `Committee` objects from the table and loads cached details with an empty API key.
- `src/congress_api/fetch/congress_event_fetcher.py` owns `{tinydb_dir}/events.json`. `get_committee_meetings` calls `committee-meeting/{congress}/{chamber}`. `fetch_event_list` fills the class-level `event_urls` dict. `process_events` downloads each detail. `return_eventid_event_mapping` returns stored rows. `event_urls` is shared across instances.

### `analyze/`

These modules are dataclasses and TinyDB caches for committee records.

- `src/congress_api/analyze/__init__.py` is empty.
- `src/congress_api/analyze/main.py` is `congress-analyze`, the YouTube-handle printer described above.
- `src/congress_api/analyze/committee_summary.py` is the committee-list dataclass: chamber, type code, name, `systemCode`, URL, and `updateDate`, plus parent and child links. `from_dict` / `from_dicts` dedupe through the module-global `INDEX`, keyed by `systemCode`.
- `src/congress_api/analyze/committee_details.py` is the detail record (counts and URLs for bills, communications, and reports; history; membership flags; parent; subcommittees). The TinyDB file name is `{chamber}-committee-details.json`. `from_spec` looks up the cache with `from_system_code`, which opens `house-committee-details.json` under `DEFAULT_TINYDB_DIR`. On a miss, or when `force_fetch` is true, it GETs `committee/{chamber}/{system_code}` and calls `store()` with the defaults (`house`, default data directory). `to_dict` renames the internal field `ctype` to `type`.
- `src/congress_api/analyze/committee.py` joins a `CommitteeSummary`, lazy `CommitteeDetails`, a YouTube TinyDB, and an `events` list. `Committee.from_summary` opens the YouTube database. `get_details` calls `CommitteeDetails.from_spec`. `congress-fetch` uses this class while it enriches every committee.

### `gpo/`

- `src/congress_api/gpo/__init__.py` is empty.
- `src/congress_api/gpo/fetch.py` is `gpo-fetch`. `GpoHearing` is the CSV row. `list_collection`, `parse_mods`, `read_transcript`, and `hearing_days` implement the three GovInfo requests. `get_with_retry` is shared with `gpo-transcripts`. `is_multi_hearing_volume` is shared with `gpo-match`.
- `src/congress_api/gpo/transcripts.py` is `gpo-transcripts`. `to_text` strips the GovInfo HTML. Downloads run on a thread pool (`--nthreads`, default 4).
- `src/congress_api/gpo/match.py` is `gpo-match`. It scores the local files listed above. `hearing_video_overrides.csv` supplies curated `package_id` rows (`verdict`, `video_ids`, `channel`, `lock`, `note`).

### `senate/`

- `src/congress_api/senate/__init__.py` is empty.
- `src/congress_api/senate/isvp.py` builds and parses Senate player URLs. `parse_player_url` returns `(comm, filename)`. `player_url`, `archive_url`, and `live_url` fill the player page, the Akamai archive `master.m3u8`, and the live `master.m3u8`. `captions.py` uses `STREAM`, `live_url`, and `parse_player_url`. `transcribe/audio.py` uses `archive_url` and `live_url` when it pulls audio with ffmpeg.
- `src/congress_api/senate/captions.py` is `senate-captions`. `cues` parses WebVTT. `merge_rollup` collapses the Senate's rolling captions into plain text. Segment downloads use their own pool (16 threads). `--nthreads` (default 4) is the pool over player URLs.

### `transcribe/`

- `src/congress_api/transcribe/__init__.py` is empty.
- `src/congress_api/transcribe/main.py` is `hearing-transcribe`. `from_gpo` parses a print. `transcribe` runs Gemini windows, `place` resolves speaker strings onto the roster, and `merge_turns` stitches windows. The stem of the output files is the YouTube id, the Senate filename, the local file stem, or the GPO package id.
- `src/congress_api/transcribe/schema.py` is the shared transcript model: `Transcript`, `Header`, `Person`, `Turn`, `Insert`, and `Source`. `SCHEMA_VERSION` is `"1.0"`. `to_json` / `from_json` round-trip the document. `render_gpo` produces the `.gpo.txt` layout. `TRANSCRIPT_JSON_SCHEMA` is the JSON Schema. `Source.kind` also names `youtube_captions` and `senate_captions` for other producers; this package's writer emits `gpo_print` and `gemini_transcription`.
- `src/congress_api/transcribe/gemini.py` calls `google-genai` with model `gemini-3.8-flash`, `WINDOW_SECONDS` of 25 minutes, temperature 0.2, and a JSON schema of `turns` and `events`. Video uses a YouTube file URI and time offsets. Audio is uploaded. Empty, recitation, or truncated windows longer than 10 minutes are split and retried. `GEMINI_API_KEY` is required.
- `src/congress_api/transcribe/audio.py` makes 16 kHz mono MP3 (`libmp3lame`, 48 kbps) with ffmpeg: YouTube via `yt-dlp`, Senate via `archive_url` / `live_url`, or a local file. `chunks` splits that file. `cut` extracts a Gemini retry window. Output goes under `{out_dir}/audio/`.
- `src/congress_api/transcribe/metadata.py` builds `HearingContext`: header, participants, YouTube ids, Senate URLs, and scheduled Eastern time. `context_for_event` is the entry. `mods_people` reads `https://www.govinfo.gov/metadata/pkg/{pkg}/mods.xml`. `legislators_current` reads `https://unitedstates.github.io/congress-legislators/legislators-current.json`. Paths default to `gpo_hearings.csv` and `congress_meetings.jsonl.gz`; `--gpo-path` and `--meetings` override them.
- `src/congress_api/transcribe/gpo_parse.py` parses plain-text GPO prints into a `Transcript`: indent, learned attributions, roster, convening, members present, adjournment, and inserts. `parse_gpo_text` is the entry. `from_gpo` in `main.py` strips the HTML before calling it.
- `src/congress_api/transcribe/names.py` matches a spoken or printed name ("Mr. Van Drew", "Jackson Lee") to a `Person` key by surname tokens. `gpo_parse`, `main.place`, and the metadata roster use `match` and `surname`.
