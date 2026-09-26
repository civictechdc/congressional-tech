# congress_youtube: Link Congressional Events to YouTube Recordings

This tool fetches and processes Congressional committee meeting metadata from Congress.gov and links it to YouTube recordings.

## Features

- [x] Scrapes congressional committee event data using the Congress.gov API
- [x] Caches results to avoid spamming API and getting banned

## TODO
- [ ] Scrapes congressional committee YouTube channels for all videos
- [ ] Links congressional committee events to their corresponding youtube recordings
- [ ] Counts how many youtube videos correctly link to the congressional committee eventid
- [ ] Produces a visual so that it's easy to track which committees are doing better than others

## Setup

You need:

- Python 3.12+
- A Data.gov API key and a YouTube API key
- (optional) conda

### Create a virtual environment (using conda or venv)

With conda:

```bash
conda create -n committee-youtube python=3.12
conda activate committee-youtube
```

Or with Python’s built-in venv:

```bash
python3.12 -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
```

### Install dependencies

```bash
pip install .
```

## API Keys

You need to supply:

- `DATA_GOV_API_KEY`: for Data.gov
- `YOUTUBE_API_KEY`: for YouTube API

These can be passed in one of three ways:
1. Via command-line arguments: `--congress-api-key` and `--youtube-api-key`
2. Via environment variables: `DATA_GOV_API_KEY` and `YOUTUBE_API_KEY`
3. As files:
   - `~/.data.gov.api.key`
   - `~/.youtube.api.key`

## Running the Scraper

To fetch congressional events and YouTube videos using the installed CLI commands (provided by `pyproject.toml`):

```bash
congress-fetch --congress-api-key YOUR_KEY
youtube-fetch --youtube-api-key YOUR_YT_KEY
```

To rely on keys from environment variables or files:

```bash
congress-fetch
youtube-fetch
```

## Outputs

- Cached event data will be stored in either JSON or Pickle format in the directory you ran the command from.
- Log messages will show what was fetched and where files were written

## Official GPO Hearing Transcripts

`gpo-fetch` lists the official printed hearing transcripts on GovInfo (the "Congressional Hearings" collection, `CHRG`) and writes one row per House hearing since the 106th Congress to `data/gpo_hearings.csv`. It uses the same `DATA_GOV_API_KEY` as `congress-fetch`.

```bash
gpo-fetch --output-path data/gpo_hearings.csv            # House only (default)
gpo-fetch --output-path data/gpo_hearings.csv --chambers hsj   # plus Senate and joint
```

The transcripts themselves aren't downloaded: `html_url` (plain text) and `pdf_url` link to them on govinfo.gov. The CSV is also the cache, so later runs only fetch hearings GovInfo added or changed. `.github/workflows/update-gpo-hearings.yml` runs it weekly.

Columns worth knowing:

- `committee_code`: the committee's system code (e.g. `hsvr00`), the same codes as `youtube-accounts.csv`.
- `event_id`: the Congress.gov event ID, the same ID committees put in YouTube descriptions. GPO only started recording it around the 114th Congress, and not for every hearing since.
- `days_to_govinfo`: days from the hearing to when GovInfo added the transcript. Before about the 111th Congress this reflects when GPO digitized old records, not when the transcript first came out.

## Useful Reference Links

- [Congress.gov event search](https://www.congress.gov/search?q=%7B%22source%22%3A%5B%22committee-meetings%22%5D%2C%22congress%22%3A%22119%22%7D&pageSize=250#) — downloadable event list
- [Congress API committee meeting detail](https://api.congress.gov/#/committee-meeting/committee_meeting_detail) — full API access
- [House Committee Calendar by Day](https://docs.house.gov/Committee/Calendar/ByDay.aspx?DayID=06192014)
- [Congressional Committee Video Archive](https://www.congress.gov/committees/video) — supposedly complete for 2025

## License

MIT or public domain depending on underlying sources.