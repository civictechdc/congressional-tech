# Handoff: state as of 2026-09-26

The work stopped partway through "address all findings". This note records where everything stands.

## Done and committed

The weekly pipeline is in place:
- **Matcher:** `gpo-match`, with `hearing_video_overrides.csv` holding the reviewed research verdicts.
- **Meetings:** `congress-meetings` keeps the Congress.gov meeting records.
- **Transcripts:** `gpo-transcripts` downloads transcript text locally.
- **Workflow:** `.github/workflows/update-data.yml` runs everything weekly. The raw caches live on the `pipeline-data` branch.

Fixes:
- `youtube-fetch` stores each video's length and handles channels with no public uploads.
- `youtube-analyze` exits non-zero on any problem.
- `gpo-fetch` cleans committee codes, flags errata, reads the hearing days of Appropriations volumes, and includes the Senate.
- Both data.gov key file names work.
- The dashboard shows joint rows correctly.

Channels:
- Chairs' channels (Markey, Gowdy) are in the new `member_channels` column.
- The 2018 joint budget committee is listed under `jsbp00`.
- **Senate:** 16 committees and 32 channels are in `youtube-accounts.csv`. The discovery notes are in `senate_channels.csv` in this folder.

Data:
- The `pipeline-data` branch has all 52 committees' YouTube caches, with lengths, plus 18,139 Congress.gov meeting records covering the House, Senate and joint committees.
- `gpo_hearings.csv` has 34,559 hearings, including 13,343 from the Senate.
- `youtube_event_id_report.csv` covers all 52 committees.

## Not finished

1. **Rerun `gpo-match` with Senate hearings included.** The committed `gpo_hearing_videos.csv` still covers House and joint only (21,216 rows). The fix for undated GPO records is committed but hasn't been run. Command: see `apps/committee_youtube/README.md`, "Running locally".
2. **News-channel search.** The partial candidates, if any were saved, are in `news_candidates.json`, and progress is in `newssearch_progress.txt`. The search was interrupted. To finish: rerun `newssearch.py`, then verify the candidates by length, date and title against the transcripts, and add the confirmed ones to `hearing_video_overrides.csv` as `found_untracked`.
3. **Update `docs/youtube-coverage/findings.md`** with the new matcher's numbers. It no longer counts clips as recordings, and it found Ways and Means' 2013–18 hearings re-uploaded to `@waysmeanscmte`. Add the Senate coverage too.
4. **Open a PR, merge it, and trigger `update-data.yml`.**

## Needed from the repo owner

- **Secrets:** add `DATA_GOV_API_KEY`, and check that `YOUTUBE_DATA_API_KEY` exists.
- **Keys:** rotate both keys that were pasted into the chat.
