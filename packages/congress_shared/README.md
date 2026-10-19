# congress-shared

`congress-shared` is the shared library for the Congress and YouTube tooling. It loads API keys, defines the default file paths, and ships the committee YouTube list and the congress date table. It has no console scripts. `congress-api` and `youtube-api` import it.

The install name is `congress-shared`. The import name is `congress_shared`. Version `0.1.0`. Python 3.12 or newer. `[project].dependencies` is empty. `import congress_shared` exports nothing. Use `congress_shared.auth` for credentials, `resources` for bundled data, `paths` for output defaults, and `cli` for command setup. `globals` retains the existing public imports for compatibility.

## Install

From the repository root:

```bash
uv pip install -e packages/congress_shared
```

`congress-api` and `youtube-api` depend on this package through `[tool.uv.sources]`, each pointing at `../congress_shared`. Installing either of those editable packages installs this one beside it.

`pyproject.toml` ships package data matching `data/*.json` and `youtube/*.csv`.

## API keys

`congress_shared.auth` reads a key from the process arguments, then the environment, then a file in the home directory.

| Function | Flag | Environment | Home file |
| --- | --- | --- | --- |
| `load_congress_api_key` | `--congress-api-key` | `DATA_GOV_API_KEY` | `~/.data.gov.api.key`, then `~/.data.gov.key` |
| `load_youtube_api_key` | `--youtube-api-key` | `YOUTUBE_API_KEY` | `~/.youtube.api.key` |

Each loader builds its own `ArgumentParser` and calls `parse_known_args`, so the flag can sit on a command that never declared it. A missing key raises `RuntimeError`. The Congress error names only `~/.data.gov.api.key`, even though `~/.data.gov.key` is also checked.

Callers: `congress-committees`, `gpo-fetch`, and `congress-meetings` use `load_congress_api_key`. `youtube-fetch` uses `load_youtube_api_key`.

## Paths

`congress_shared.resources` resolves bundled reference paths from the installed package directory. `congress_shared.paths` defines default writable locations from the same directory, preserving every historical location. Neither module creates directories or files.

`PACKAGE_DIR` is the `congress_shared` package directory. `resources.RESOURCE_DATA_DIR` and `paths.DEFAULT_OUTPUT_DIR` both currently equal `PACKAGE_DIR / "data"`. They name separate uses of the existing location; no stored data moves. The compatibility name `globals.DATA_DIR` retains that path.

| Constant | Path | What lives there |
| --- | --- | --- |
| `DEFAULT_CHANNELS_CSV` | `youtube/youtube-accounts.csv` | Bundled. The committee YouTube list. |
| `DEFAULT_TINYDB_DIR` | `data/` | Default directory for TinyDB JSON. |
| `CONGRESS_METADATA` | `data/congress_metadata.json` | Bundled. Loaded into this name at import. |
| `DEFAULT_GPO_HEARINGS_FILE` | `data/gpo_hearings.csv` | Default output of `gpo-fetch`. |
| `DEFAULT_MEETINGS_FILE` | `data/congress_meetings.jsonl.gz` | Default output of `congress-meetings`. |
| `DEFAULT_HEARING_VIDEOS_FILE` | `data/gpo_hearing_videos.csv` | Default output of `gpo-match`. |
| `DEFAULT_YOUTUBE_REPORT_FILE` | `data/youtube_event_id_report.csv` | Default output of `youtube-analyze`. |

The two bundled files are `congress_metadata.json` and `youtube-accounts.csv`. The CSV and gzip paths above are where the other packages write. They are not in this package's tree until a command creates them.

`congress_shared.cli.add_global_args` adds `--tinydb_dir` (a resolved `Path`, default `DEFAULT_TINYDB_DIR`). `add_youtube_args` adds `--channels-csv-path` (destination `channels_csv_path`). That flag's type is `str` and its default is a `Path`, so an explicit value arrives as a string and the default arrives as a `Path`.

`youtube-fetch`, `youtube-analyze`, and `gpo-match` call `add_global_args`. The two YouTube commands also call `add_youtube_args`. `gpo-match` declares its own `--channels-csv-path` as a `Path` instead.

Imports leave root logging unchanged and create no files. `resources` reads `congress_metadata.json`; a missing or invalid JSON file still fails the import. The compatibility module `globals` reexports the same metadata object, paths, and argument helpers.

The command entrypoints for `youtube-fetch`, `youtube-analyze`, `congress-meetings`, `congress-committees`, `gpo-fetch`, `gpo-match`, `gpo-transcripts`, `meeting-inventory`, and `hearing-transcribe` explicitly call `cli.configure_logging()`. This retains INFO logging to stdout with `%(levelname)s %(asctime)s : [%(name)s.%(funcName)s] %(message)s`. Existing root handlers still take precedence. Library callers choose their own logging setup.

## Congress metadata

`data/congress_metadata.json` has 14 objects, keys `"106"` through `"119"` (strings). Each object has `start`, `end`, `senate`, `house`, and `sessions`. Dates are `YYYY-MM-DD`. The 106th Congress starts `1999-01-03`. The 119th runs `2025-01-03` to `2027-01-03`.

`senate` and `house` are control labels: `Republican`, `Democratic`, or, for the 107th Senate, `Democratic / Republican / Democratic`. A session object has `name`, `start`, and `end`. Congresses 106–118 have two sessions. The 119th has one session so far, and that session's `end` is `present`. Only the 107th sessions also carry their own `senate` field.

`youtube-analyze` bins videos with the congress-level `start` and `end`, and reads `control` from `senate` or `house`. Joint committees have no matching key, so `control` is empty. `congress-meetings` takes the newest congress as `max` of the keys. `gpo-fetch` takes the oldest as `min` of the keys when `--min-congress` is omitted. The analyzer treats a congress-level `end` of `present` as `9999-12-31`. In this file, `present` is the 119th session's `end`. The 119th congress `end` is `2027-01-03`.

## YouTube accounts

`youtube/youtube-accounts.csv` is the default channel list (`DEFAULT_CHANNELS_CSV`). It has 52 data rows. Columns, in order:

| Column | Role |
| --- | --- |
| `committee` | Display name. `youtube-fetch --committee-name` must match it exactly. |
| `systemCode` | Congress.gov committee code. `map_system_code_committee_handles` keys on this. |
| `handle` | Primary YouTube handle. Every row has one, and each starts with `@`. |
| `secondary` | Extra handles in one cell, separated by `;`. 34 rows have at least one. |
| `member_channels` | Chair channels, same `;` format. Two rows: `@Tgowdysc` (Benghazi) and `@senatormarkey` (Energy Independence and Global Warming). |

`systemCode` prefixes: 30 `h` (House), 16 `s` (Senate), 6 `j` (joint). One committee name is stored as `Science,Space,and Technology`.

Row order is the TinyDB index. The first data row is `youtube_00.json`. Append new committees. Inserting a row in the middle renumbers every file after it. `youtube-fetch` includes `member_channels`. `youtube-analyze` does not.

## Files

### Package root

- `pyproject.toml` defines `congress-shared` 0.1.0, Python `>=3.12`, an empty dependency list, setuptools package discovery under `src`, and package data `data/*.json` and `youtube/*.csv`. It declares no console scripts.
- `src/congress_shared/__init__.py` is empty.

### Library

- `src/congress_shared/auth.py` is the two key loaders above. `_load_api_key` is the shared helper.
- `src/congress_shared/resources.py` locates bundled references and loads `CONGRESS_METADATA`.
- `src/congress_shared/paths.py` defines the existing default output and cache locations.
- `src/congress_shared/cli.py` owns argument helpers and explicit logging setup.
- `src/congress_shared/globals.py` reexports existing public names for compatibility.

### Bundled data

- `src/congress_shared/data/congress_metadata.json` is the congress table described above.
- `src/congress_shared/youtube/youtube-accounts.csv` is the channel list described above.

## Retained YouTube cache format

`congress_shared.youtube_cache.decode_cache` reads the TinyDB table layout shared
by inventory, GPO matching and Explorer. It accepts JSON bytes/text or decoded
tables. `videos()` yields `(literal_table_handle, unchanged_video_row)` pairs;
`channels()` yields unchanged channel metadata. Both preserve insertion order,
including repeated video IDs. Video-only readers do not inspect channel tables.

The module uses only the standard library. It performs no file or network access,
does not load configuration or collectors, and does not repair malformed inputs.
Callers retain file selection, missing-file behavior, byte snapshots and matching
or export policies. Both source packages already depend on `congress-shared`;
the decoder adds no installation dependencies.
