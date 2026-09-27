# Research files behind the YouTube coverage findings

These are the inputs, agent outputs and scripts behind `../findings.md` and `../hearing_video_verdicts.csv` (September 2026). They let the results be audited, rebuilt or extended.

## Rebuild the CSV

The raw YouTube data has since moved to the `pipeline-data` branch, and `gpo_hearings.csv` gained cleaned codes, so rebuild from a checkout of the commit the research used:

```bash
git worktree add /tmp/research-snapshot 8247617
S=/tmp/research-snapshot
python docs/youtube-coverage/research/scripts/aggregate.py --out /tmp/verdicts.csv \
  --data-dir $S/apps/committee_youtube/data \
  --channels-csv $S/packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv
cmp /tmp/verdicts.csv docs/youtube-coverage/hearing_video_verdicts.csv   # identical
```

`aggregate.py` runs offline from the files in this folder and the repo's data. It:
1. re-runs the automatic matcher;
2. applies the research agents' verdicts;
3. applies the verification outcomes;
4. reclassifies off-channel videos that are really on a tracked channel;
5. flags videos matched to hearings on different dates.

It reproduces the committed CSV byte for byte, as long as the repo's YouTube data, channel list and GPO data are unchanged.

To rebuild the research agents' evidence packets (their inputs):

```bash
git show 7f71208:packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv > /tmp/channels.csv
python docs/youtube-coverage/research/scripts/build_packets.py --out-dir /tmp/packets --channels-csv /tmp/channels.csv \
  --data-dir /tmp/research-snapshot/apps/committee_youtube/data
```

With the channel list from commit `7f71208` (the list at the time), this reproduces the 16 original batches exactly.

## Contents

### `agent_briefs/`

The instructions given to the agents, verbatim. File paths in them point to the session's scratch space.

- `research_brief.md`: the 16 research agents, one batch each.
- `verification_brief.md`: the 6 adversarial verifiers.
- `archive_brief.md`: the 8 archive-investigation agents (C-SPAN, Wayback Machine, committee archives).

### `agent_results/`

One JSON line per hearing, as each agent wrote it. Where an agent rewrote a hearing, the last line wins.

- `possible_01…08.jsonl`: research agents for hearings where a tracked channel posted something that week but automatic matching couldn't confirm it (1,294 hearings). Fields: `package_id`, `verdict`, `video_ids`, `channel`, `confidence`, `evidence`.
- `novideo_01…08.jsonl`: research agents for hearings with nothing on a tracked channel that week, or no usable committee code (904 hearings). Same fields.
- `verify_pos_1…4.jsonl`: refuters' outcomes on the 176 riskiest "found" claims. Fields: `outcome` (upheld, revised or refuted), `corrected_verdict`, `video_ids`, `channel`, `evidence`.
- `verify_neg_1…2.jsonl`: challengers' outcomes on a random 90 negative verdicts. Same fields as the refuters.
- `new_channels.jsonl`: official channels the agents found that weren't tracked. All three have since been added to the channel list.
- `news_search_confirmed.csv` and `news_search_review.csv`: the news-channel search's candidates after the Data API check (see below). `confirmed` rows passed the date gate; `review` rows matched on title only and are almost all other hearings on the same subject.

- `archive_01…08.jsonl`: the archive investigation's verdicts (below), one line per hearing: `package_id`, `verdict` (`found_youtube`, `found_cspan`, `found_archived`, `found_other_site`, `clips_only`, `not_public`, `not_found`), `urls`, `video_ids`, `channel`, `confidence`, `evidence`. `archive_review_decisions.json` records which low-confidence finds were kept and why.

### `data/`

- `swarm_input_hearings.csv`: the 2,198 hearings automatic matching couldn't place, with their status before the research.
- `congress_gov_meetings_112-119.jsonl.gz`: all 13,564 House and joint committee meeting records from Congress.gov (112th–119th Congress). They include event IDs and the official video links, which the channel sweep and the matching used. Fetching these takes about 13,600 API calls.
- `congress_gov_unknown_videos_oembed.json`: the channel behind each Congress.gov-linked video that wasn't in our data.
- `untracked_claim_video_channels.json`: the channel behind each video in a "found elsewhere" claim. `aggregate.py` uses it offline.
- `channel_search_broad.json`, `channel_search_targeted.json` and `channel_search_2007_2012.json`: raw YouTube channel-search results from the channel sweep (about 250 queries).
- `channel_handles_resolved.json`: every handle in the channel list, resolved to its channel ID, title and subscriber count. This is the check that each handle points to the intended channel.
- `senate_channels.csv`: the Senate channel discovery notes, one row per Senate committee, caucus or select committee with GPO hearings (23), with the evidence for each channel found and for the seven with none.
- `senate_isvp_probe.csv`: the senate.gov archive probe's result for every Senate hearing since 2013 that had no recording (5,115 rows; 4,786 with the player URL of the recording found).
- `news_search_candidates.json` and `news_search_video_details.json`: the news-channel search's raw candidates (441 hearings, 984 videos) and each video's upload date, length and description from the YouTube Data API.

### `scripts/`

- `aggregate.py` and `build_packets.py`: clean, offline, and verified to reproduce the committed outputs (see above).
- `as_run/`: the scripts as they were run during the research, kept for reference. They contain hardcoded scratch paths (`/tmp/claude-0/...`) and would need small edits to rerun.
  - `meetings.py`: fetch all Congress.gov meeting records.
  - `links.py`: pull the YouTube links out of those records and resolve unknown videos to channels.
  - `match2.py`: the automatic GPO-to-video matcher.
  - `meetcov.py`: meeting-side coverage.
  - `resolve.py`, `ytsearch.py`, `sites.py`: channel discovery by handle resolution, YouTube search and committee-website scraping.
  - `yt.py`: the shared, rate-limited, cached YouTube client the agents used.
  - `audit.py`: the automatic check of the agents' output.
  - `newssearch.py` and `verify_news.py`: the news-channel search (below).
  - `senate_isvp_probe.py`: the senate.gov archive probe (below).
  - `web.py`: the shared, cached, rate-limited web client the archive agents used (C-SPAN through Zyte, Wayback CDX and page fetches, video-link extraction). `aggregate_agents.py` turns their verdicts into override rows after a Data API check of every claimed YouTube video; `apply_overrides.py` merges those rows into `hearing_video_overrides.csv`.

## Transcripts and captions (September 2026)

- `data/hearing_text_sources.csv`: every Congress.gov meeting since the 113th Congress with the GPO print(s) matched to it, its recordings, and which has text (`research/scripts/hearing_text_sources.py`).
- `data/meetings_without_records.csv`: the Congress.gov meetings since the 113th Congress with no GPO print, no recording found (by Congress.gov link, event ID, the matcher's date-and-title rules, or the Senate archive probe) and no captions, with whether witness or meeting documents exist. Written by `scripts/hearing_text_sources.py` alongside the index.
- `data/transcribe_compare/`: the comparison of machine transcription routes against a GPO print (`scripts/transcribe_compare.py`): `gpo.json` (the print parsed into the shared schema), `routeA_*.json` (Gemini 3.5 Transcribe plus a speaker resolver, with and without the video), `routeB.json` (Gemini 3.8 Flash on the video), `compare.json` (word error rate and speaker accuracy), and rendered samples.

## Archive investigation (September 2026)

After the news-channel search, eight agents took the 840 House and joint hearings still without a full recording, grouped by committee, and looked off YouTube: C-SPAN's video library listed by hearing date, the Wayback Machine's copies of each committee's hearing pages and every video reference on them, and the archives those pointed to (DVIDS, the Senate's video archive, csce.gov, host organizations). They found recordings for about a third. Every claimed YouTube video was checked with the Data API; finds under 20 minutes were reviewed by hand (`archive_review_decisions.json`). C-SPAN bot-blocks direct clients, so those requests went through the Zyte API.

## Senate archive probe (September 2026)

The Senate hosts hearing video on its own player (`senate.gov/isvp/?comm=<committee>&filename=<committee><MMDDYY>`), and Congress.gov only started linking it in late 2023. The player's page names the archive path for each committee, so the probe builds the recording name from each hearing's committee and date (with `A` and `B` for a second and third hearing that day), sends a HEAD to the archive manifest and to the newer live path, and records the player URL when either exists. Run over the 5,115 Senate hearings since 2013 without a recording, it found 4,786. Its hits are `found_offsite` rows in `hearing_video_overrides.csv`.

## News-channel search (September 2026)

The adversarial check's one refuted negative was a Roll Call livestream under a generic title, so every House and joint hearing since 2013 still without a full recording (825 after the weekly matcher's first run) was searched again on YouTube: a general search on the hearing title and year, plus in-channel searches of Roll Call, the Washington Post and PBS NewsHour. Candidates of 30 minutes or more on untracked channels with some title overlap were kept (441 hearings, 984 videos), then checked with the YouTube Data API. A candidate counted only when it was uploaded the day of the hearing to three days after, or its text carried the hearing's date or event ID, and its title matched. That left 26 hearings, reviewed by hand: 14 were real recordings on news, witness-organization or member channels and are now `found_untracked` rows in `hearing_video_overrides.csv`; the rest were other hearings on the same subject, a report launch, or a member's question round. The same review found nine volumes of the 2019 impeachment markup blocked from their committee's own livestreams by a wrong GPO date on a sibling volume; they are `found_tracked` rows.

## Not saved

- **The cache of fetched YouTube pages (3.6 GB).** It's stale and easy to regenerate.
- **The agents' own working folders (about 150 MB of drafts and page dumps).** Their conclusions are in `agent_results/`.
- **The data.gov API key.** Scripts that call data.gov or Congress.gov read it from `DATA_GOV_API_KEY`, or from a key file in the as-run versions.
