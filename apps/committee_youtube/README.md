# committee_youtube: congressional hearings and their YouTube recordings

This pipeline tracks every official House, Senate and joint committee YouTube channel. It also tracks every official GPO hearing transcript, and works out which video records which hearing. Findings from the first full analysis are in [`docs/youtube-coverage/findings.md`](../../docs/youtube-coverage/findings.md).

## Committee Explorer publication

`committee-explorer-export` assembles retained source records into the shared
`committee_meeting` model. Source packages still own collection, parsing and
matching. This command reads local files only. The publication workflow runs
after the collection workflow settles and when relevant code changes reach
main. The existing reports continue through their current commands.

```bash
.venv/bin/committee-explorer-export \
  --meetings ../pipeline-data/congress_meetings.jsonl.gz \
  --house-state ../pipeline-data/meeting-inventory/house.json.gz \
  --senate-state ../pipeline-data/meeting-inventory/senate.json.gz \
  --inventory-state ../pipeline-data/meeting-inventory/inventory.json.gz \
  --youtube-dir ../pipeline-data/youtube \
  --gpo-path apps/committee_youtube/data/gpo_hearings.csv \
  --video-matches-path apps/committee_youtube/data/gpo_hearing_videos.csv \
  --recordings-path apps/committee_youtube/data/meeting_recordings_found.csv \
  --recovered-witnesses apps/committee_youtube/data/meeting_witnesses.csv \
  --state-dir .cache/explorer-state --output-dir .cache/explorer-public
```

Pass `--transcript PATH` for each existing structured transcript body. It remains
unchanged and has its own schema; contextual participant rosters do not become
attendance. Optional `--issue-decisions PATH` reads documented resolution rows
with `issue_id`, `status` (`resolved` or `dismissed`), and `explanation`.
`--limit N` declares a rehearsal selection and is not a full-population export.

Preserve the state directory: it stores stable IDs and compact issue history.
Records validate individually before the complete graph check, so assembling
the Catalog does not copy the whole graph again. Prior issues load from SQLite
only when needed; the exporter does not reload the previous complete Catalog.
The exporter validates
references, evidence selectors and artifact hashes before replacing
`CURRENT.json`. The pointer identifies an immutable manifest with exact input
hashes, source scope, media types and file discovery. A failed export leaves the
working pointer in place. Unknown retrieval times remain unknown.

The full local publication includes a compatibility meeting index, record/source
chunks, hashed locators, related-record indexes, paged browse indexes and
evidence-state coverage. Browse pages cover committee terms, meetings,
appearances, materials and issues, grouped by Congress. Meeting rows carry the
same evidence states used in coverage, so filtering and charts share a denominator.
Chunks target 2 MiB; an indivisible source record can exceed this budget and is
listed explicitly. A complete Catalog remains a local offline artifact.
The browser packager excludes that Catalog and the large compatibility index,
compresses browser files with an explicit media type, and enforces a 900 MB
publication budget. The site reader uses query pages, relations and locators.
Coverage counts source
entries in all statuses; unchecked canceled or future meetings are not inferred
publication failures. Issues overlap and are counted separately.

See [integration execution and measured limits](../../packages/committee_meeting/INTEGRATION_EXECUTION.md)
for the complete retained-data rehearsal, source repairs and remaining release
work. Large generated artifacts remain outside the code branch. IDs, current
issue history, job receipts and the browser publication live on `pipeline-data`.
State archives split into checked 50 MiB chunks; expanded state never enters Git.
Publication and collection share a concurrency group. After a verified snapshot
is saved, Pages receives exact code and pipeline commit IDs, verifies the files
again and enforces GitHub's 1 GB site limit before deployment. A failed export or
verification leaves the prior public site in place.

## What runs every week

`.github/workflows/update-data.yml` runs every Sunday. It has three jobs, each run after the one before even when that one failed.

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

**`meetings` job.** A job of its own: its readers depend on docs.house.gov and 21 committee sites, and a failure there must not hold back the GPO and video outputs above.

| Step | Command | Output |
|---|---|---|
| Test the parsers and refresh decisions | `pytest` | none |
| Fill House repository gaps | `house-meeting-records` | `data/house_documents_found.csv`, `data/house_witnesses_found.csv`, `data/house_amendments_found.csv` |
| Read Senate and joint committee pages | `senate-meeting-records` | `data/senate_hearing_pages_found.csv`, `data/senate_witnesses_found.csv`, `data/senate_documents_found.csv` |
| Join meeting records, text, recordings and witnesses | `meeting-inventory` | `data/hearing_text_sources.csv`, `data/meetings_without_records.csv`, `data/meeting_completeness.csv`, `data/meeting_witnesses.csv` |

- **Raw caches:** the YouTube caches (`youtube/youtube_NN.json`), meeting records (`congress_meetings.jsonl.gz`) and parsed meeting-source state (`meeting-inventory/*.json.gz`) live on the bot-owned `pipeline-data` branch. It's replaced by one snapshot commit each run, so the weekly data doesn't pile up in `main`'s history.
- **Initial state and recovery:** `pipeline-data/meeting-inventory/*.json.gz` supplies the parsed records and availability observations. The initial seed was added directly to that branch; no seed blobs are kept in the code branch. See [meeting-state setup and recovery](../../docs/youtube-coverage/meeting-state.md).
- **Failures:** every command exits non-zero on any failure. Derived CSV commits require the whole job to succeed. Once committee readers have started, their raw-state snapshot still saves the last usable records and failed-refresh receipts; setup/test failures do not create a snapshot. The publication records the failed job separately, and incremental fetching catches up on the next run.

The workflow needs two repository secrets:

- `YOUTUBE_DATA_API_KEY`;
- `DATA_GOV_API_KEY`, which serves both GovInfo and Congress.gov.

## Meeting inventory

The source readers run after `gpo-match`, then the inventory joins them once. Neither reader reads the inventory. Every path is explicit, so a rehearsal can use a copy of `pipeline-data` and a separate output directory.

```bash
.venv/bin/house-meeting-records --meetings ../pipeline-data/congress_meetings.jsonl.gz \
  --gpo-path apps/committee_youtube/data/gpo_hearings.csv \
  --state-dir ../pipeline-data/meeting-inventory --output-dir apps/committee_youtube/data
.venv/bin/senate-meeting-records --meetings ../pipeline-data/congress_meetings.jsonl.gz \
  --state-dir ../pipeline-data/meeting-inventory --output-dir apps/committee_youtube/data
.venv/bin/meeting-inventory --meetings ../pipeline-data/congress_meetings.jsonl.gz \
  --gpo-path apps/committee_youtube/data/gpo_hearings.csv \
  --videos-path apps/committee_youtube/data/gpo_hearing_videos.csv --tinydb_dir ../pipeline-data/youtube \
  --recordings apps/committee_youtube/data/meeting_recordings_found.csv \
  --state-dir ../pipeline-data/meeting-inventory --output-dir apps/committee_youtube/data
```

New or changed Congress.gov records are fetched immediately. Unchanged meetings become due weekly through 30 days, every 28 days through two years, and annually after that; a newer House XML update restarts the faster schedule. The House XML's `update-date` is retained: among 6,155 cached files, the 95th-percentile lag was 330 days, 62 updates came after two years and 19 were newer than Congress.gov's update. Consequently, Congress.gov's marker alone cannot settle freshness. Unchanged refreshes are capped at 400 House meetings and 450 Senate pages per run, oldest checks first; a synchronized backfill can leave a queue. The seed's age groups imply means of 364 and 404 checks per week. New and changed records are outside those maintenance caps.

Senate listing discovery repeats weekly and when meeting records change. Paged listings stop after two pages overlapping the saved list; WordPress listings use their hearing-date fields. Matching still rejects dates and files shared by more than five pages, uses the hearing page's own date, and requires at least half its distinctive subject. House XML is authoritative, with a fetched page fallback when no candidate XML address exists. Direct House requests stay at least 1.2 seconds apart, with a 60-second pause after a 403. Failures remain retryable; only confirmed 404s become absences.

The 114-meeting, 30-day replay required 125 House requests and 92 Senate requests, without revisiting the full 4,925-page Senate corpus. The House pacing floor for that batch is 150 seconds. The full copied snapshot was 52.8 MB, including 13.8 MB of parsed source state. See [the verification report](../../docs/youtube-coverage/production-verification.md) for timings, live limits and exact differences from the research snapshot.

The ten output filenames and column names are retained. `meeting_recordings_found.csv` is the curated input, now in `data/`. `witness_list_document=unparsed` distinguishes a text PDF with no usable names from a scan; one old row that treated another member's name as a witness affiliation was removed.

Caption observations are imported into compact state. YouTube's `caption=false` does not rule out automatic captions: 2,433 sampled false-flag videos had them, while 1,649 had none. Saved positive and negative observations take precedence; an unobserved video with `caption=true` supplies caption evidence. For recognized Senate studio committees, unobserved filenames since August 2023 are treated as captioned; live master playlists confirmed all 29 additional meetings this identifies in the baseline. Placeholder committee codes are excluded. `video_no_captions` means no confirmed text, including unprobed automatic-caption availability. These are availability rules, not downloaded transcripts.

The Senate recording probe saves each committee-day's positive or negative answer. It waits seven days after a new meeting before probing at most eight archive/live manifests, so future calendar entries do not become permanent absences. Transient errors fail the command. Manual `youtube-captions` and `senate-captions` downloads can later update the inventory with `--youtube-caption-index PATH` and `--senate-caption-index PATH`. Caption downloading and `hearing-transcribe` remain manual.

For an offline rebuild, copy `meeting-inventory/*.json.gz` from the latest `pipeline-data` snapshot into your chosen state directory and pass `--offline` to the three commands. A new backfill uses the same commands with an empty state directory. `--seed-cache ~/hearing-text` imports the old research caches read-only, when available; it is never needed in CI. `house-meeting-records --zyte --threads 16` is an optional metered backfill and requires `ZYTE_TOKEN` in the environment. **No additional weekly secret is needed.** `--limit N` bounds live House meetings or Senate hearing pages; it does not include Senate listing requests. An incomplete initial backfill exits non-zero instead of publishing partial outputs. `--site` restricts live Senate fetching for a bounded check while retaining other saved sites.

The parser, refresh and offline-export tests run first in the `meetings` job.
Install the local packages using the command below, adding the `test` extra to
`packages/congress_api`, and run `.venv/bin/python -m pytest`.

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
- **Hearing days come from the transcript:** `gpo-fetch` reads the day headers of every transcript since the 113th Congress, and a hearing is matched on each day they name (the `hearing_dates` column), else on GPO's held date, and on both when the transcript names one day and GPO another. Multi-hearing Appropriations volumes are matched to meetings by subcommittee, since their title names no hearing. Scanned prints have no text, so only their GPO date is used.

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
- `hearing_dates`: the hearing days the transcript's day headers name, when they say more than `held_date`: every day of a volume or a multi-day hearing, or the one day GPO dated differently.
- `text_read`: `yes` once the transcript has been read for its day headers.
- `committee_name`: GPO's name for the committee, or, where GPO names none, the committee on the transcript's title page. `committee_code` is then filled from the code GPO most often gives that name in that chamber.

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

`packages/congress_api/src/congress_api/senate/isvp.py` holds the Senate player's committee table and URL patterns, shared by `senate-captions`, `meeting-inventory` and the retained research probe.

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
pip install -e packages/committee_meeting -e packages/congress_shared -e packages/youtube_api -e 'packages/congress_api[test]' -e apps/committee_youtube
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
