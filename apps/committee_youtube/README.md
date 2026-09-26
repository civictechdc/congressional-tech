# committee_youtube: congressional hearings and their YouTube recordings

This pipeline tracks every official House, Senate and joint committee YouTube channel. It also tracks every official GPO hearing transcript, and works out which video records which hearing. Findings from the first full analysis are in [`docs/youtube-coverage/findings.md`](../../docs/youtube-coverage/findings.md).

## What runs every week

`.github/workflows/update-data.yml` runs every Sunday. It has two jobs.

**`youtube` job:**

| Step | Command | Output |
|---|---|---|
| Fetch every channel's videos, with caption flag and length | `youtube-fetch` | raw caches, `pipeline-data` branch |
| Report videos and event-ID coverage per channel and Congress | `youtube-analyze` | `data/youtube_event_id_report.csv`, plus the dashboard's copy in `apps/site/public/data/youtube/` |

**`congress` job:**

| Step | Command | Output |
|---|---|---|
| List GPO's official hearing transcripts | `gpo-fetch` | `data/gpo_hearings.csv` |
| Keep Congress.gov committee meeting records | `congress-meetings` | raw cache, `pipeline-data` branch |
| Match each hearing to its recording(s) | `gpo-match` | `data/gpo_hearing_videos.csv`, `data/gpo_hearing_video_coverage.csv` |

- **Raw caches:** the YouTube caches (`youtube/youtube_NN.json`) and meeting records (`congress_meetings.jsonl.gz`) live on the bot-owned `pipeline-data` branch. It's replaced by one snapshot commit each run, so the weekly data doesn't pile up in `main`'s history.
- **Failures:** every command exits non-zero on any failure. That fails the job and skips its commits, and because fetching is incremental, the next run catches up.

The workflow needs two repository secrets:
- `YOUTUBE_DATA_API_KEY`;
- `DATA_GOV_API_KEY`, which serves both GovInfo and Congress.gov.

## Channels: `youtube-accounts.csv`

`packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv` has one row per committee. Row order matters: row N is stored as `youtube_NN.json`, so add new committees at the end.

| Column | Meaning |
|---|---|
| `committee`, `systemCode` | Name and Congress.gov/GPO code (`hsag00` House, `ssfr00` Senate, `jsec00` joint). `jsbp00` is our own placeholder for the 2018 Joint Select Committee on Budget and Appropriations Process Reform, which has no official code. |
| `handle` | The main channel. |
| `secondary` | Other official channels (minority, archives, old handles), separated by `;`. |
| `member_channels` | Chairs' personal channels that hold a committee's hearings (for example Ed Markey's for the 2007–10 Global Warming committee). They're fetched and used for matching, but not counted as committee videos in the report. |

## Matching: `gpo-match`

Each GPO hearing is matched to a recording using this evidence, strongest first:
1. a Congress.gov video link from the hearing's meeting record (a YouTube video, or for the Senate a link to the Senate's own player at senate.gov, which gives `full_recording_offsite`);
2. the hearing's event ID in the video's title or description, whenever it was uploaded;
3. the hearing date in the title or description ("031815 -", "7/23/2013. EMR.");
4. title or subcommittee similarity within a few days.

Rules:
- **One video per hearing:** each video goes to its best-matching hearing. Hearings on the same day may share one.
- **Clips:** a video found by weaker evidence (no Congress.gov link or event ID) counts as a clip when it's under 20 minutes, or under 30 minutes with a member-clip title ("Wyden Q&A …", "Chairman Smith Questions Witnesses …", "Opening Statement …"). Senate party channels post question rounds of that length for most hearings.
- **Multi-hearing Appropriations volumes:** these are matched on each hearing day, read from the transcript (the `hearing_dates` column). About a quarter of them are scanned PDFs with no text, so only their GPO date is used.

`data/hearing_video_overrides.csv` holds reviewed verdicts from the September 2026 research, plus `found_offsite` rows for Senate hearings whose recording the senate.gov archive probe found (`research/scripts/as_run/senate_isvp_probe.py` in the docs folder). They're used where they exist, with these exceptions:
- a "no video"/"clips only" verdict gives way to strong new evidence, or to a dated recording of 30+ minutes;
- rows marked `lock=yes` never change.

To correct a match by hand, add or edit a row there.

`gpo_hearing_videos.csv` statuses:

| Status | Meaning |
|---|---|
| `full_recording` | A recording of the proceeding on YouTube. |
| `full_recording_offsite` | No full recording on YouTube, but one on C-SPAN, in the Wayback Machine or on another site (`video_ids` holds the URLs, `channels` the host). |
| `clips_only` | Only clips or statements. |
| `not_public` | A closed session, written-only volume or errata sheet. |
| `no_video_found` | Nothing found. |
| `before_channel` | Held before the committee's earliest tracked video. |
| `committee_not_tracked` | No channel list entry for the committee. |

Flags:
- `audio_only`: the recording is audio only;
- `volume_days_with_video=a/b`: how many of a volume's hearing days have video;
- `video_shared_with_same_day_hearing`.

## GPO transcripts

**`gpo-fetch`** lists GovInfo's "Congressional Hearings" collection (`CHRG`) for the House, Senate and joint committees since the 106th Congress. The CSV is also its cache. After widening `--chambers` or `--min-congress`, pass `--full-relist` once.

Useful columns:
- `committee_code`: cleaned, with typos fixed and blanks filled from the committee name. `committee_code_gpo` keeps GPO's original.
- `event_id`: the Congress.gov event ID. It's only recorded from about the 114th Congress on, and not always.
- `days_to_govinfo`: days from hearing to publication. Before about the 111th Congress this is when GPO digitized old records.
- `record_type`: `hearing` or `errata`.
- `hearing_dates`: every hearing day in an Appropriations volume.

**`gpo-transcripts`** downloads transcript text to a local folder for search or summaries. It isn't committed: all House and joint hearings since 2013 come to about 2 GB.

```bash
gpo-transcripts --out-dir ~/transcripts --congress 118 --committee hsvr00
```

## Running locally

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e packages/congress_shared -e packages/youtube_api -e packages/congress_api
git worktree add ../pipeline-data pipeline-data   # raw caches

youtube-fetch   --tinydb_dir ../pipeline-data/youtube
youtube-analyze --tinydb_dir ../pipeline-data/youtube --output-path apps/committee_youtube/data/youtube_event_id_report.csv
gpo-fetch --output-path apps/committee_youtube/data/gpo_hearings.csv
congress-meetings --output-path ../pipeline-data/congress_meetings.jsonl.gz
gpo-match --tinydb_dir ../pipeline-data/youtube --meetings ../pipeline-data/congress_meetings.jsonl.gz \
  --gpo-path apps/committee_youtube/data/gpo_hearings.csv --output-path apps/committee_youtube/data/gpo_hearing_videos.csv
```

API keys are read from these sources, in order:
- **Command-line arguments:** `--youtube-api-key` and `--congress-api-key`.
- **Environment variables:** `YOUTUBE_API_KEY` and `DATA_GOV_API_KEY`.
- **Key files:** `~/.youtube.api.key`, and `~/.data.gov.api.key` (or `~/.data.gov.key`).

## Useful reference links

- [Congress API committee meeting detail](https://api.congress.gov/#/committee-meeting/committee_meeting_detail)
- [GovInfo API](https://api.govinfo.gov/docs/)
- [Congress.gov committee video archive](https://www.congress.gov/committees/video)

## License

MIT or public domain depending on underlying sources.
