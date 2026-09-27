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
- **Mistagged videos:** committees sometimes tag a video with another hearing's event ID, and Congress.gov's link follows the tag. Event-ID or Congress.gov evidence for a video posted more than a week after the hearing ranks below a same-week title match when the video's title doesn't match the hearing, or matches a hearing held the week it was posted.
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

## Transcripts and captions

GPO prints transcripts for roughly 70–90% of House hearings, months later, and for none of the markups. For the rest, the recordings' captions are the only text:

| Command | Source | Text quality |
|---|---|---|
| `gpo-transcripts` | GPO's printed transcript | The record |
| `youtube-captions` | The video's English caption track: the uploader's if there is one, else YouTube's automatic captions | Automatic captions are unpunctuated speech recognition, fine for search and for finding who said what when |
| `senate-captions` | The caption track of the Senate player's recordings since mid-2023 | Closed captions as broadcast, in capitals |

```bash
youtube-captions --out-dir ~/hearing-text/youtube --ids-file videos.txt
senate-captions  --out-dir ~/hearing-text/senate  --urls-file links.txt   # senate.gov/isvp/?comm=...&filename=... links
```

Each writes one text file per recording and a `captions_index.csv` (what was fetched and what had no track), and skips what's already there. YouTube starts asking for a sign-in after a few hundred requests from one address. A JavaScript runtime on the machine (`brew install deno`) makes that rarer, `youtube-captions --proxy http://<zyte-api-key>:@api.zyte.com:8011` routes the fetch through Zyte's proxy mode, which passes, and failed videos are left out of the index so the next run retries them. Like `gpo-transcripts`, they fill a local folder rather than the repository. Older Senate recordings (the archive path, before mid-2023) carry captions only inside the video stream, which `senate-captions` doesn't decode. C-SPAN no longer publishes transcripts of its programs.

`packages/congress_api/src/congress_api/senate/isvp.py` holds the Senate player's committee table and URL patterns, shared by `senate-captions` and the archive probe in the docs folder.

### Machine transcripts in the print's shape: `hearing-transcribe`

For a hearing with no print, `hearing-transcribe` produces a transcript with the members and witnesses named, in one schema that a GPO print also parses into (`congress_api/transcribe/schema.py`: header, participants with role, party, state, bioguide ID and affiliation, speaker turns with times, record inserts). It writes `<id>.json` and `<id>.gpo.txt`, the latter laid out like the print.

```bash
export GEMINI_API_KEY=...
hearing-transcribe --event-id 116xxx --out-dir ~/hearing-text/transcripts --gpo-path apps/committee_youtube/data/gpo_hearings.csv --meetings ../pipeline-data/congress_meetings.jsonl.gz
hearing-transcribe --gpo-package CHRG-118hhrg54254 --out-dir ...     # the print itself, parsed into the schema
```

Who was in the room comes from the Congress.gov meeting record (witnesses with organization and position), GPO's MODS record for the hearing or for the committee's nearest printed hearing that Congress (members with party, state and bioguide ID), and congress-legislators for current members.

Gemini 3.8 Flash transcribes the recording in 25-minute windows into named speaker turns: the YouTube video itself, where it reads the name plates and hears the chair's recognitions, or uploaded audio chunks for senate.gov and local recordings. Measured on a 2023 Judiciary hearing against its print: word error rate 8.7% (largely the print's own editing of false starts and repairs), speaker right on 85% of words, about 5 minutes and 600k input tokens for a 100-minute hearing.

Window size is set by the model's recitation filter, not its context: a verbatim window over about 30 minutes, or the whole video in one call, comes back empty, so a window that fails is split in half. The dedicated transcription model (Gemini 3.5 Transcribe, with diarization and word timestamps) matched the words as well but its speaker labels mapped to the right person for only 66–74% of words, so it isn't used; `docs/youtube-coverage/research/scripts/transcribe_compare.py` and `research/data/transcribe_compare/` hold that comparison.

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
