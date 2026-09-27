# youtube-api

`youtube-api` stores committee YouTube channels and downloads their caption tracks. `youtube-fetch` pulls channel and video metadata from the YouTube Data API into per-committee TinyDB files. `youtube-analyze` reports, for each congress, how many of those videos name an event id and how many have a published caption flag. `youtube-captions` saves the English caption track of specific videos as plain text.

The monorepo package name is `@ct/youtube-api`. The Python package name is `youtube-api`, version `0.1.0`. It requires Python 3.12 or newer. `import youtube_api` exports nothing. Import a submodule, or run a console script.

## Install

From the repository root:

```bash
uv pip install -e packages/youtube_api
```

`pyproject.toml` declares `congress-shared`, `google-api-python-client`, `tinydb`, `yt-dlp`, and `curl_cffi`. `[tool.uv.sources]` points `congress-shared` at `../congress_shared`. `curl_cffi` lets `yt-dlp` impersonate a browser, which YouTube's bot check usually accepts.

`congress-shared` supplies the channel CSV, the default TinyDB directory, congress date ranges, and YouTube API-key loading.

## Credentials

`youtube-fetch` loads a YouTube Data API key through `congress_shared.auth.load_youtube_api_key`, in this order:

1. `--youtube-api-key`
2. the `YOUTUBE_API_KEY` environment variable
3. `~/.youtube.api.key`

`youtube-fetch` and `youtube-analyze` call `parse_known_args`, so `--youtube-api-key` can sit on the same command line. `youtube-captions` uses `yt-dlp` and takes no API key. `--proxy` on that command is for when YouTube asks for a sign-in.

## Commands

| Script | Module | What it writes |
| --- | --- | --- |
| `youtube-fetch` | `youtube_api.fetch.main` | `{tinydb_dir}/youtube_{index:02d}.json` |
| `youtube-analyze` | `youtube_api.analyze.main` | `youtube_event_id_report.csv` |
| `youtube-captions` | `youtube_api.captions.main` | `{videoId}.txt` and `captions_index.csv` |

`congress_shared.globals.add_global_args` adds `--tinydb_dir`. `add_youtube_args` adds `--channels-csv-path`.

### Channel and video metadata

`youtube-fetch` reads `youtube-accounts.csv` and, for every committee handle, stores the channel and its uploads.

```bash
youtube-fetch
youtube-fetch --committee-name "House Committee on the Judiciary"
youtube-fetch -i 0 --tinydb_dir /path/to/tinydb
```

`-n` / `--committee-name` and `-i` / `--committee-index` are mutually exclusive. Omit both to process every row. The index is the 0-based row order of the CSV after load. An unknown name raises `IndexError`. An index outside `0` … `len(rows)-1` raises `ValueError`.

Each committee lands in `{tinydb_dir}/youtube_{index:02d}.json`. The default directory is `congress_shared`'s `data/`. Inside the file:

- table `youtube_channels` holds handle, snippet fields, and the uploads playlist id
- table `youtube_videos_{handle}` holds `title`, `description`, `publishedAt`, `videoId`, and later `caption` and `duration`

The handle in the table name is the literal CSV string, including `@`.

The fetch walks three YouTube Data API v3 calls:

1. `channels.list` with `forHandle`, parts `snippet` and `contentDetails`
2. `playlistItems.list` on the uploads playlist, 50 items per page, snippet only. A 404 on the first page means the channel has no public uploads.
3. `videos.list` with `part=contentDetails`, up to 50 ids per call, for `caption` and `duration`. The module docstring counts that call as one quota unit per 50 videos.

Later runs stop paging a playlist when they hit a `videoId` already stored. Videos missing `caption` or `duration`, and videos with `caption` false published within the last 30 days (`CAPTION_RECHECK_DAYS`), are sent through `videos.list` again. A failed channel is logged and the command continues. The process exits 1 if any channel failed.

Handles include the primary channel, semicolon-separated `secondary` channels, and semicolon-separated `member_channels`. Member channels are personal channels of chairs who post a committee's hearings. `YoutubeEventFetcher.force` truncates stored channels and videos before a refetch. The CLI does not set it.

### Event-id report

`youtube-analyze` reads those TinyDB files and writes one row per committee handle per congress.

```bash
youtube-analyze --output-path youtube_event_id_report.csv --nthreads 4
```

The default output is `congress_shared`'s `data/youtube_event_id_report.csv`. `--nthreads` defaults to the CPU count (`None` in argparse, then `multiprocessing.cpu_count()`). The work runs in a process pool. The command requires an existing `youtube_{index:02d}.json` for each committee (`assert_exists=True`).

CSV columns, from `EventIdReport`: `committee_name`, `handle`, `total_videos`, `missing_event_id`, `congress_number`, `control`, `chamber`, `with_captions`.

A video counts for a congress when `publishedAt` falls in that congress's date range from `congress_metadata.json`. An end date of `present` is treated as `9999-12-31`. An event id is present when the title or description matches `.*(\d{6}|eventid).*`, case insensitive. `missing_event_id` is the videos in range that fail that test. `with_captions` counts stored records whose `caption` field is `True` (YouTube's `contentDetails.caption` at fetch time). `chamber` comes from the first character of the `systemCode` (`h` house, `j` joint, `s` senate). `control` is the chamber's control string from the congress metadata.

This command calls `get_all_committee_handless` with member channels off, so personal chair channels are in the TinyDB after `youtube-fetch` and stay out of this report. Videos whose `publishedAt` falls outside every congress range are left out of the counts. The CSV is still written when some committees fail or when videos fall outside the ranges. The process then exits 1.

### Caption text

`youtube-captions` downloads English caption tracks with `yt-dlp` and does not download the video.

```bash
youtube-captions --out-dir ~/hearing-text/youtube --video-ids dQw4w9WgXcQ
youtube-captions --out-dir ~/hearing-text/youtube --ids-file videos.txt
```

A video with an English track becomes `{out_dir}/{videoId}.txt`. `vtt_to_text` drops consecutive duplicate lines, which is how YouTube's automatic captions scroll. The index `{out_dir}/captions_index.csv` has columns `video_id`, `kind`, and `characters`. `kind` is `manual` (uploader English subtitles are listed), `auto` (only automatic captions), or `none` (no English track, and no `.txt` file). Automatic captions are unpunctuated speech recognition. IDs already in the index are skipped. A `DownloadError` whose message contains `not a bot`, `429`, or `HTTP Error 5` is kind `error` and stays out of the index so the next run retries it. Any other `DownloadError` is indexed as `none`. `--nthreads` defaults to 3. `--proxy` sets yt-dlp's proxy and `nocheckcertificate`. `--sleep` sets `sleep_interval_requests` when it is greater than 0.

## Channel CSV

The default file is `congress_shared`'s `youtube/youtube-accounts.csv`, overridable with `--channels-csv-path`. Columns:

| Column | Role |
| --- | --- |
| `committee` | Display name. `--committee-name` must match it exactly. |
| `systemCode` | Congress.gov committee code. `map_system_code_committee_handles` keys on this. |
| `handle` | Primary YouTube handle. |
| `secondary` | Extra handles, separated by semicolons. |
| `member_channels` | Chair channels, separated by semicolons. Fetched, and omitted from `youtube-analyze`. |

Row order is the TinyDB index. `youtube_00.json` is the first data row.

## Default paths

`congress_shared.globals` resolves these from the installed `congress_shared` package:

| Setting | Location under `congress_shared` |
| --- | --- |
| `DEFAULT_CHANNELS_CSV` | `youtube/youtube-accounts.csv` |
| `DEFAULT_TINYDB_DIR` | `data/` |
| `DEFAULT_YOUTUBE_REPORT_FILE` | `data/youtube_event_id_report.csv` |

## Files

Empty `__init__.py` files mark packages and define no API.

### Package root

- `pyproject.toml` defines `youtube-api` 0.1.0, the dependency list, the uv path source, and the three console scripts.
- `package.json` names the workspace package `@ct/youtube-api`, version `0.1.0`, private, with no npm scripts.
- `turbo.json` extends the repo Turborepo config and defines no local tasks.
- `uv.lock` is a uv lockfile, and the repo gitignore excludes `**/uv.lock`. This copy requires Python `>=3.13` and pins `youtube-api` to `google-api-python-client` 2.187.0 only, plus that client's stack (`google-api-core`, `google-auth`, `google-auth-httplib2`, `googleapis-common-protos`, `httplib2`, `cachetools`, `certifi`, `charset-normalizer`, `idna`, `proto-plus`, `protobuf`, `pyasn1`, `pyasn1-modules`, `pyparsing`, `requests`, `rsa`, `uritemplate`, `urllib3`). `congress-shared`, `tinydb`, `yt-dlp`, and `curl_cffi` are absent. `pyproject.toml` is the dependency list.
- `src/youtube_api.egg-info/` is setuptools metadata from an editable install, and `*.egg-info/` is gitignored. `PKG-INFO` records the name, version `0.1.0`, the summary "YouTube API Client for Congressional Tech", Python `>=3.12`, and `Requires-Dist` lines for `congress-shared`, `google-api-python-client`, `tinydb`, and `yt-dlp`. `requires.txt` lists those same four. `curl_cffi` is absent from both. `entry_points.txt` lists the three console scripts. `top_level.txt` contains `youtube_api`. `SOURCES.txt` lists the modules setuptools saw. `dependency_links.txt` is empty.
- `src/youtube_api/__init__.py` is empty.

### Shared tables

- `src/youtube_api/tables.py` reads the channel CSV and opens TinyDB files. `map_system_code_committee_handles` returns `systemCode` → `name`, `handles`, and `member_handles`. `get_all_committee_handless` lists those handles, with member channels only when asked. `get_all_commitee_names` lists committee names, optionally with the row index. `get_committee_index` returns that index and raises `IndexError` when the name is missing. `open_tinydb_for_committee` opens `youtube_{index:02d}.json`, creating it unless `assert_exists=True`. `congress_api` uses `map_system_code_committee_handles` and `open_tinydb_for_committee` to attach a committee's YouTube database. The public names `get_all_commitee_names` and `get_all_committee_handless` are spelled that way in the source.

### `fetch/`

- `src/youtube_api/fetch/__init__.py` is empty.
- `src/youtube_api/fetch/main.py` is `youtube-fetch`. It loads the API key, selects committees, and for each handle calls `get_channel`, `get_all_channel_videos`, and `update_video_details`. Member channels are included.
- `src/youtube_api/fetch/youtube_event_fetcher.py` is the YouTube Data API client. `YoutubeEventFetcher` builds a `googleapiclient` client for service `youtube` version `v3`. `parse_channel_details`, `parse_video_details`, `parse_iso8601_duration`, and `insert_videos_into_tb` shape the TinyDB rows. `CAPTION_RECHECK_DAYS` is 30. `force` is a class attribute the CLI leaves false.

### `analyze/`

- `src/youtube_api/analyze/__init__.py` is empty.
- `src/youtube_api/analyze/main.py` is `youtube-analyze`. `EventIdReport` is one CSV row. `generate_report_for_congress_number` counts videos, missing event ids, and caption flags for one handle and one congress. `write_to_csv` writes the report. `EVENT_ID_REGEX` is `.*(\d{6}|eventid).*`. `CHAMBER_BY_CODE_PREFIX` maps `h`, `j`, and `s`.

### `captions/`

- `src/youtube_api/captions/__init__.py` is empty.
- `src/youtube_api/captions/main.py` is `youtube-captions`. `fetch_one` returns `(video_id, kind, characters)`. `vtt_to_text` strips the WebVTT. `YDL_OPTS` holds the proxy and sleep settings for the run. The command imports neither `tables.py` nor `congress_shared`.
