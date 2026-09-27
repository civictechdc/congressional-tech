# Research files behind the YouTube coverage findings

These are the inputs, agent outputs, and scripts behind [`../findings.md`](../findings.md) and [`../hearing_video_verdicts.csv`](../hearing_video_verdicts.csv) (September 2026). They let the results be audited, rebuilt, or extended.

Two products sit next to this folder, and they answer different questions.

- [`../findings.md`](../findings.md) is the writeup. Its six numeric tables are regenerated from the weekly matcher's `apps/committee_youtube/data/gpo_hearing_videos.csv` by `scripts/findings_tables.py`. The prose around the tables is written by hand.
- [`../hearing_video_verdicts.csv`](../hearing_video_verdicts.csv) is the frozen research-pass snapshot: 9,643 House and joint hearings from the 113th Congress on. Later news-search, archive, and Senate-probe finds live in `apps/committee_youtube/data/hearing_video_overrides.csv`, which the weekly matcher reads. The snapshot uses the research verdict labels below. The matcher uses `full_recording`, `full_recording_offsite`, `clips_only`, `not_public`, `no_video_found`, `before_channel`, and `committee_not_tracked`. `partial_only` in the snapshot is the research name for clips.

## How the work was produced

1. `as_run/meetings.py` fetched Congress.gov meeting records (House and joint, 112th–119th). `as_run/links.py` pulled YouTube links out of them.
2. `as_run/match2.py` and `as_run/meetcov.py` tried automatic matching and wrote scratch JSON only (`matched2.json`, `meet_none.json`). The 2,198 hearings they could not place were saved by hand as `data/swarm_input_hearings.csv`. No script in this folder writes that CSV.
3. `scripts/build_packets.py` built 16 evidence batches. Sixteen research agents wrote `agent_results/possible_*.jsonl` and `novideo_*.jsonl`. Six verifiers wrote `verify_*.jsonl`. `as_run/audit.py` checked the research output.
4. `scripts/aggregate.py` merged the automatic matches, the agent verdicts, and the verification into `hearing_video_verdicts.csv`.
5. `as_run/newssearch.py` and `as_run/verify_news.py` searched news and other untracked channels. Eight archive agents, using `as_run/web.py`, looked off YouTube. `as_run/senate_isvp_probe.py` probed the Senate player. Those finds were merged into `hearing_video_overrides.csv` (`as_run/aggregate_agents.py` and `as_run/apply_overrides.py` for the archive pass, `as_run/news_overrides.py` for the news search, `as_run/senate_probe_overrides.py` for the probe).
6. The weekly `gpo-match` reads the overrides. `scripts/findings_tables.py` refreshes the tables in `findings.md`.

`scripts/hearing_text_sources.py` and `scripts/transcribe_compare.py` are the transcript work in the last sections of `findings.md`. They are separate from the verdict CSV.

## Rebuild the verdict CSV

The raw YouTube data has since moved to the `pipeline-data` branch, and `gpo_hearings.csv` now includes Senate hearings, so rebuild from a checkout of the commit the research used:

```bash
git worktree add /tmp/research-snapshot 8247617
S=/tmp/research-snapshot
python docs/youtube-coverage/research/scripts/aggregate.py --out /tmp/verdicts.csv \
  --data-dir $S/apps/committee_youtube/data \
  --channels-csv $S/packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv
cmp /tmp/verdicts.csv docs/youtube-coverage/hearing_video_verdicts.csv   # identical
```

`aggregate.py` runs offline. It keeps every hearing with `congress >= 113` in the GPO file it is given. The committed CSV is House and joint because that was the extract at `8247617` (9,234 House and 409 joint). Current `gpo_hearings.csv` has 15,478 hearings from the 113th Congress on, including 5,835 Senate, so the same command against current data writes a larger file.

With the pinned inputs it:

1. re-runs the automatic matcher (a Congress.gov event ID in the video text, else a video posted from one day before the hearing to three days after, accepted on title overlap of at least 0.5, else the subcommittee name in the title);
2. applies the research agents' verdicts for the 2,198 hearings in `data/swarm_input_hearings.csv`;
3. applies the verification outcomes (`refuted` and `revised` replace the verdict; `upheld` is recorded and left in place);
4. reclassifies `found_untracked` videos whose handles, looked up in `data/untracked_claim_video_channels.json` (video ID to handle, not the agent's `channel` string), are on a tracked channel;
5. records `shared_video` whenever one video is matched to more than one hearing. When those hearings fall on different dates, the rows that lose the video (all but the hearing closest to the upload date) get `verdict_note`, and only `source=auto` losers become `unconfirmed`. Same-day shares are flagged and left in place.

Weak automatic matches (`date_only`, or no candidate) are stored as `source=excluded`, `verdict=before_channel_existed`.

Columns: `package_id`, `held_date`, `congress`, `chamber`, `committee_code`, `committee_name`, `subcommittees`, `title`, `source`, `verdict`, `confidence`, `video_ids`, `channel`, `evidence`, `verification`, `verdict_note`, `shared_video`, `prior_status`, `transcript_url`. `evidence` can contain newlines, so the file has more physical lines than rows.

| | |
|---|---:|
| Rows | 9,643 |
| `held_date` | 1992-03-17 – 2026-07-22 (a few bad GPO dates; three rows fall before 2013) |
| `source=auto` / `swarm` / `excluded` | 7,428 / 2,198 / 17 |
| `found_tracked` | 8,632 |
| `no_video_found` | 478 |
| `partial_only` | 334 |
| `unconfirmed` | 74 |
| `not_public` | 55 |
| `found_untracked` | 53 |
| `before_channel_existed` | 17 |
| `verification` upheld / revised / refuted | 251 / 11 / 4 (the other 9,377 rows were not in the adversarial sample) |

To rebuild the research agents' evidence packets:

```bash
git show 7f71208:packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv > /tmp/channels.csv
python docs/youtube-coverage/research/scripts/build_packets.py --out-dir /tmp/packets --channels-csv /tmp/channels.csv \
  --data-dir /tmp/research-snapshot/apps/committee_youtube/data
```

With the channel list from commit `7f71208`, this writes 16 JSON arrays (`possible_01.json` … `possible_08.json`, `novideo_01.json` … `novideo_08.json`), 2,198 hearings. Each packet has the GPO fields, `status_so_far`, tracked channels, candidate videos posted from two days before to seven days after, and Congress.gov meetings of the same committee within two days. Those meetings always come from `data/congress_gov_meetings_112-119.jsonl.gz`, and the swarm list always comes from `data/swarm_input_hearings.csv`; `--data-dir` does not redirect either file. Committee-code aliases applied while bucketing meetings: `jjec00→jsec00`, `hlvc00→hsgo00`, `hlfd00→hsju00`, `hlqj00→hsju00`. A blank or unknown GPO code is replaced by the majority code for that committee name. `possible` is every swarm row whose status starts with `possible`; the rest are `novideo`.

To refresh the six tables in `findings.md` after a weekly match (this edits the file in place, and only the marked regions):

```bash
python docs/youtube-coverage/research/scripts/findings_tables.py
```

Markers: `house_summary`, `senate_summary`, `house_congress`, `house_committee`, `senate_congress`, `senate_committee`. Committee groups smaller than five hearings are omitted. "Since 2019" is `congress >= 116`.

## `findings.md`

Sections: Summary; House and joint coverage by Congress; House and joint coverage by committee; Senate coverage; what happened to the missing House video, committee by committee; YouTube channels; problems found in the pipeline; problems found in GPO's metadata; recommendations; transcripts and captions; verification (research pass, news-channel search, archive investigation, weekly matcher); method; files.

The summary counts are the live matcher. They differ from the verdict CSV above because the matcher has since applied the overrides, the one-video-per-hearing rule (which retired the snapshot's 74 `unconfirmed` rows), and the off-YouTube finds. The matcher's event-ID and date rules later found a further 134 hearings the research pass had marked as clips only or no video, almost all Ways and Means hearings re-uploaded years later under date-only titles. `findings.md` records the automatic check of the research pass: 2,496 claimed videos (2,400 resolve to the claimed channel, 42 exist but block embedding, 54 sit on a different tracked committee's channel) and 1,335 found claims, of which 510 carry the event ID in the video text, 636 match the title, 89 give the date, and 100 have none of those signals. The same writeup records 1,278 late bulk uploads found by the research pass, 32 hearings that share a video with another hearing on the same day, 7,545 YouTube videos linked from Congress.gov House meeting records (9 of them unlisted on a tracked channel), and 1,381 Senate player links on Congress.gov since late 2023.

## Contents

### `agent_briefs/`

The instructions given to the agents, verbatim. Paths in the research and verification briefs point at the session scratch tree (`/tmp/claude-0/.../scratchpad/swarm`). The archive brief uses a `SCRATCH/` prefix.

- `research_brief.md`: the 16 research agents. Verdicts: `found_tracked`, `found_untracked`, `partial_only`, `not_public`, `no_video_found`, each with `confidence` of `high`, `medium`, or `low`. Official untracked committee channels go to `new_channels.jsonl` (member and news channels stay out). Network access is the shared `yt.py` client.
- `verification_brief.md`: the 6 adversarial verifiers. Outcomes: `upheld`, `refuted`, `revised`, with `corrected_verdict` on every line.
- `archive_brief.md`: the 8 archive-investigation agents. Verdicts: `found_youtube`, `found_cspan`, `found_archived`, `found_other_site`, `clips_only`, `not_public`, `not_found`. They use `web.py` (C-SPAN through Zyte, Wayback CDX and page fetches). `found_archived` is in the brief; no committed row uses it.

### `agent_results/`

One JSON line per hearing, as each agent wrote it. Where an agent rewrote a hearing, the last line wins. In these files each `package_id` appears once.

- `possible_01…08.jsonl`: hearings where a tracked channel posted something that week but automatic matching could not confirm it. 1,294 lines (162 in each of the first seven files, 160 in `possible_08`). Fields: `package_id`, `verdict`, `video_ids` (a list), `channel`, `confidence`, `evidence`.
- `novideo_01…08.jsonl`: hearings with nothing on a tracked channel that week, or no usable committee code. 904 lines (113 each). Same fields. One `partial_only` row has an empty `video_ids` list (`CHRG-113hhrg86245`).
- Together, 2,198 unique package IDs and no overlap. Verdicts: `found_tracked` 1,273, `partial_only` 330, `no_video_found` 479, `not_public` 54, `found_untracked` 62. Confidence: high 1,505, medium 659, low 34.
- `verify_pos_1…4.jsonl`: refuters on the 176 riskiest "found" claims (every off-channel find, every medium- or low-confidence match, and every claim with no signal in the video text). 44 lines each. Outcomes: upheld 166, revised 7, refuted 3. Fields: `package_id`, `outcome`, `corrected_verdict`, `video_ids`, `channel`, `evidence`.
- `verify_neg_1…2.jsonl`: challengers on a random 90 negative verdicts. 45 lines each. Outcomes: upheld 85, revised 4, refuted 1. Same fields.
- `new_channels.jsonl`: three official channels the agents found that were not tracked, since added to the channel list. Fields: `handle`, `channel_url`, `channel_name`, `committee`, `evidence`. Handles: `@HASCRepublicans`, `@congressionaloversightcomm6808`, `@HouseJudDems`.
- `news_search_confirmed.csv` and `news_search_review.csv`: the news-channel search after the Data API check. `confirmed` has 45 video rows for 26 hearings (the date gate passed). `review` has 733 video rows for 323 hearings (title overlap only). Eleven hearings appear in both files. Columns: `package_id`, `held_date`, `committee`, `hearing_title`, `status` (the pre-search matcher status, `no_video_found` or `clips_only`), `videoId`, `channel`, `handle`, `published`, `gap_days`, `minutes`, `sim_title`, `sim_text`, `date_in_text`, `event_id_in_text`, `video_title`, `transcript`.
- `archive_01…08.jsonl`: 840 hearing lines plus a terminal `{"done": true, "hearings": N, "found": M}` line in each file (848 lines). Batch sizes run from 99 to 131. Fields: `package_id`, `verdict`, `urls`, `video_ids`, `channel`, `confidence`, `evidence`. A few rows also carry `partial`, `covers`, `also_cspan`, or `note`. Verdicts: `not_found` 377, `clips_only` 144, `found_cspan` 123, `found_youtube` 98, `found_other_site` 90, `not_public` 8. `found_archived` does not appear. `findings.md`'s hand summary splits the finds further: C-SPAN 120, YouTube 96, the Senate archive 52, the Helsinki Commission's Facebook page 43, DVIDS 2. The JSONL verdict totals above are the ones to recount; the hand summary folds some `found_other_site` and `found_youtube` rows into those hosts.
- `news_search_review_decisions.json`: the hand review of the 26 date-confirmed news-search hearings: 14 accepted, 3 rejected with the reason, and the nine impeachment volumes handled as a side find.
- `archive_review_decisions.json`: the hand review of short or unverifiable archive finds. Keys: `accept_low` (10 package IDs kept), `accept_low_why`, `reject` (7 package IDs dropped), `reject_why`, `not_public_extra` (impeachment volumes V and X, `CHRG-116hhrg39405` and `CHRG-116hhrg39410`), `not_public_extra_why`.

### `data/`

- `swarm_input_hearings.csv`: the 2,198 hearings automatic matching could not place. Columns: `held_date`, `congress`, `chamber`, `committee_code`, `committee_name`, `subcommittees`, `title`, `event_id`, `youtube_status`, `transcript_url`. Statuses: `possible match (same committee, same days, different title)` 1,294, `no video found` 845, `committee not tracked` 59. Dates run from 2012-09-28 to 2026-03-18. `transcript_url` is the GPO HTML link `aggregate.py` uses to recover `package_id`.
- `congress_gov_meetings_112-119.jsonl.gz`: 13,564 meeting records, House 13,398 and joint (`NoChamber`) 166, congresses 112–119, dates 2011-01-20 to 2026-09-28. This file has no Senate rows. Typical keys: `_url`, `chamber`, `committees`, `congress`, `date`, `eventId`, `location`, `meetingDocuments`, `meetingStatus`, `title`, `type`, `updateDate`, and on many rows `videos`, `hearingTranscript`, `witnessDocuments`. Fetching them took about 13,600 API calls. `hearing_text_sources.py` reads a different export, the weekly `pipeline-data/congress_meetings.jsonl.gz` next to the repo, which includes Senate meetings. `findings.md` cites that weekly file (18,139 meetings).
- `congress_gov_unknown_videos_oembed.json`: 43 Congress.gov-linked videos that were not in the local YouTube data, each with `author`, `url`, and `title`.
- `untracked_claim_video_channels.json`: 79 video IDs from "found elsewhere" claims, mapped to a channel handle (41 handles). `aggregate.py` uses it offline.
- `channel_search_broad.json`, `channel_search_targeted.json`, and `channel_search_2007_2012.json`: raw YouTube channel-search results, 292 queries in total. `broad` has 200 queries and 2,621 hits, each hit a 4-list `[channelId, title, handle, handle]` (the fourth element repeats the handle). `targeted` has 50 queries and 758 hits, each a 2-list `[channelId, title]`. `channel_search_2007_2012.json` has 42 queries and 345 hits, same 2-list shape. `as_run/ytsearch.py`, as saved, writes a query-keyed file whose fourth element is the subscriber-count text, so it does not reproduce the committed broad file's repeated handle. The targeted and 2007–2012 files have no script in `as_run/`. `findings.md` also cites the live corpus (119 channels, 67,244 videos) and about 250 searches; the three JSON files are the 292 queries actually saved.
- `channel_handles_resolved.json`: 74 handles from the channel list, each with `id`, `handle`, `title`, `subs`, and `videos` (`subs` and `videos` are display strings such as `"2.99K"`). This is the check that each handle points at the intended channel.
- `senate_channels.csv`: Senate channel discovery notes, one row per Senate committee, caucus, or select committee with GPO hearings (23). Columns: `committee`, `systemCode`, `handle`, `secondary` (extra handles, semicolon-separated), `evidence`. Sixteen rows have a primary handle. The seven without one are Agriculture, Armed Services, Rules, Ethics, Intelligence, the Senate National Security Working Group, and the Porteous impeachment trial committee.
- `senate_isvp_probe.csv`: the senate.gov archive probe. 5,251 rows: 5,115 Senate packages (three dated before 2013) and 136 joint packages. Columns: `package_id`, `held_date`, `committee_code`, `comm`, `urls` (player URLs, space-separated; 455 rows have more than one). 4,845 rows have a URL. Of the 5,112 Senate packages dated 2013 or later, 4,786 have a URL, which is the figure in `findings.md`.
- `news_search_candidates.json`: a list of 441 hearings still without a full recording. Each object has `package_id`, `held_date`, `committee`, `title`, `status`, `transcript`, and `candidates`. Each candidate has `videoId`, `title`, `channel_name`, `channel`, `published`, `length`, `minutes`, `sim`, `found_by`. 1,105 candidate slots, 984 distinct video IDs. Status: `no_video_found` 240, `clips_only` 201.
- `news_search_video_details.json`: those 984 videos, keyed by video ID, each with `published`, `seconds`, `title`, `description`, `channel`, `channelId`.
- `hearing_text_sources.csv`: 17,606 Congress.gov meetings from the 113th Congress on (House 12,865, Senate 4,575, joint 166), dates 2013-01-04 to 2026-10-01. Columns: `event_id`, `congress`, `chamber`, `type`, `date`, `committees`, `title`, `gpo_packages`, `youtube_ids`, `senate_urls`, `text_source`, `documents`, `rescheduled_to` (the later same-committee, same-title meeting that has a record, when this one has none: Congress.gov keeps a postponed meeting as Scheduled after re-entering it under a new event ID), `not_held` (`yes` when the record's own title begins POSTPONED, CANCELED, RESCHEDULED or Test; 11 rows). `text_source` counts in the committed file: `gpo` 11,779, `youtube_captions` 2,194, `video_no_captions` 1,871, `no_video` 985 (40 of them with `rescheduled_to` set), `senate_captions` 777. `gpo` and `no_video` follow the meetings export and the matcher rules. The three caption buckets follow the `captions_index.csv` files in the youtube and senate directories at the time of the run, so a later run can move rows among `youtube_captions`, `senate_captions`, and `video_no_captions` without changing the row count or the `no_video` count. `documents` is `yes` when the meeting record has witness or meeting documents. The table in `findings.md` prints the House and Senate rows; the 166 joint meetings are in this CSV. Caption files behind `youtube_captions` and `senate_captions` were fetched with `youtube-captions` and `senate-captions` (see `apps/committee_youtube/README.md`).
- `meetings_without_records.csv`: the 939 rows of `hearing_text_sources.csv` with `text_source=no_video`, no `rescheduled_to` and no `not_held`. Columns: `event_id`, `congress`, `chamber`, `type`, `date`, `committees`, `title`, `documents`. Chamber: House 415, Senate 509, joint 15. `documents`: yes 361, no 578. Of the House rows, 199 are hearings and 216 are markups or business meetings (`Markup` 123, `Meeting` 93); 258 have documents. The largest House committees in the file are Intelligence (`hlig00`, 162) and Natural Resources (`hsii00`, 35). 554 rows are closed by nature (type or title says closed, briefing or deposition). Of the Senate rows, 292 are Intelligence (`slin00`), 30 are marked closed, and 413 have `documents=no`.
- `search_smoke_test.csv`: the search-engine check of the gap findings (September 2026). 201 rows in five rounds: round 1 is one hand-picked row per gap listed in `findings.md` (25); round 2 a seeded random sample of 44 across five populations (printed House/joint hearings with no video, printed Senate hearings with no video or an untracked committee, printed hearings with clips only, unprinted House hearings with no records, unprinted Senate open meetings with no records); round 3 a seeded random sample of 43 from the strata round 2 had not reached (House markups and business meetings, House hearings outside Natural Resources, Natural Resources hearings, Senate open meetings, joint bodies, two closed meetings); round 4 a seeded random sample of 37 from the open remainder by committee plus two House Intelligence hearings whose titles say open; round 5 all 50 open House meetings whose committee had a recording for 80% or more of its meetings of that kind in that year, searched through SerpAPI with `scripts/search_smoke.py`. Rounds 1 to 4 were run by hand in a browser (Google's own results page, captcha solved by the operator). Columns: `round`, `gap`, `key` (package ID, event ID or video ID), `date`, `committee`, `title`, `query` (the Google query), `outcome`, `note`. Outcomes: `holds` 161, `explained` 12, `wrong_fixed` 12, `miss_unfixed` 4, `rescheduled` 3, `unverified_lead` 2, `found_cspan_medium` 1, `gpo_multiday` 1, `found_offsite` 1, `gpo_wrong_date` 1, `joint_twin` 1, `transcript_elsewhere` 1, `found_unlisted` 1. `wrong_fixed` rows became an override or a rule in `hearing_text_sources.py`; `rescheduled` and `joint_twin` rows are handled by that script's `rescheduled_to` marking and same-day same-title sharing; `miss_unfixed` rows are known misses no safe rule reaches; `found_unlisted` is an unlisted upload on a tracked channel, reachable only through the committee's event page.
- `transcribe_compare/`: one hearing, `CHRG-118hhrg54254` ("HEARING ON COMPLIANCE WITH COMMITTEE OVERSIGHT", House Judiciary subcommittee, 2023-11-30), against YouTube `8V3OGbZOLB0`. Shared transcript schema (`schema_version` 1.0): `header`, `participants`, `turns`, `inserts`, `source`.
  - `gpo.json` and `gpo.rendered.txt`: the print. 192 turns, 13,234 words.
  - `routeA_text.json` and `routeA_video.json`: Gemini 3.5 Transcribe plus a speaker resolver, on the transcript text and on the video. 174 turns each. The current `transcribe_compare.py` no longer writes these.
  - `routeB.json` and `routeB.rendered.txt`: Gemini 3.8 Flash on the video in 25-minute windows. 391 turns, 13,710 words.
  - `compare.json`: word error rate and speaker accuracy from that September run. Route A video: WER 0.081, speaker-word accuracy 0.661. Route A text: WER 0.081, speaker-word accuracy 0.737. Route B: WER 0.087, speaker-word accuracy 0.855. Keys are `gpo`, `A_video`, `A_text`, `B`, and each route also has `turns`, `words`, `aligned_words`, `unknown_words`, `speakers`, and `per_speaker_accuracy`. A fresh run of the current script writes only `gpo.json`, `routeB.json`, and a `compare.json` whose `B` object has `wer`, `shares`, `speakers_named`, `unknown_word_share`, and `time_s`.
  - `example_house_video.json` and `example_house_video.gpo.txt`: a `hearing-transcribe` run of the same House hearing (package `CHRG-118hhrg54254`, video `8V3OGbZOLB0`), not an output of `transcribe_compare.py`. The JSON is `gemini-3.8-flash (video)`, 179 turns, 12,565 words, 45 participants. The `.gpo.txt` is the print rendered as text. The command is documented in `apps/committee_youtube/README.md` under `hearing-transcribe`.
  - `example_senate_audio.json` and `example_senate_audio.gpo.txt`: the same tool on a Senate recording, package `CHRG-118shrg53786` (Budget, "Hearings to examine public investment.", 2023-09-20, event `334844`, player `senate.gov/isvp/?comm=budget&filename=budget092023`). The JSON is `gemini-3.8-flash (audio)`, 106 turns, 15,029 words, 26 participants. The `.gpo.txt` is that print rendered as text.

### `scripts/`

Clean scripts, meant to be re-run:

- `aggregate.py` and `build_packets.py`: offline, and verified to reproduce the committed verdict CSV and the 16 packets (see above).
- `findings_tables.py`: rewrites the six marked tables in `../findings.md`. No arguments. It reads `gpo_hearing_videos.csv` (`status`, `channels`, `congress`, `chamber`, `committee_code`), `gpo_hearings.csv` (committee names), and `youtube-accounts.csv` (`handle`, `secondary`, `member_channels`). Senate tables add columns for off-YouTube recordings, hearings before the channel existed, and committees with no channel.
- `search_smoke.py`: `SERPAPI_TOKEN=... python search_smoke.py sample.json results.json`. Sends each sample row's `query` to Google through SerpAPI once (answers cached in `results.json`), reduces the answer to organic and video results with real URLs, looks YouTube links up in the Data API, and prints per row what surfaced (`video` when a 20-minute-plus upload sits on the meeting's day or the next, `page` for house.gov, senate.gov, congress.gov, govinfo.gov and c-span.org, `other`). Metered. The round-5 sample and answers are not committed.
- `hearing_text_sources.py`: writes `data/hearing_text_sources.csv` and `data/meetings_without_records.csv`. It reads `apps/committee_youtube/data/gpo_hearings.csv`, the channel list, `{repo-parent}/pipeline-data/congress_meetings.jsonl.gz`, and one TinyDB file per channel-list row at `{repo-parent}/pipeline-data/youtube/youtube_{i:02d}.json`. It imports `congress_api` (GPO matching helpers and `congress_api.senate.isvp`). Optional caption indexes: `--youtube-dir` (default `~/hearing-text/youtube`, file `captions_index.csv` with `video_id` and `kind` of `manual`, `auto`, or `none`) and `--senate-dir` (default `~/hearing-text/senate`, `captions_index.csv` with `filename` and `kind` of `webvtt` or `none`). Meetings kept are those with status Scheduled or Rescheduled. Meeting committee codes go through the matcher's `ALIAS` map first (Congress.gov files the Joint Economic Committee as `jjec00`, GPO as `jsec00`). YouTube matches for meetings with no GPO package need a tracked video of at least 1,200 seconds that is either posted a day before to three days after the meeting with title similarity of at least 0.5 or naming one of the same bill numbers, or an upload whose title carries the meeting's date (`10-29-13 Full Committee Business Meeting`, `Full Committee Markup (May 23, 2018)`, and Natural Resources' `3.2.16. EMR. 10:00 AM.`, where the `NR_UNITS` map turns the abbreviation into a subcommittee code) when the meeting is the committee's only one that day or the title names its subcommittee, nearest hour when a subcommittee met twice; or a session upload, a generic hearing or markup title that agrees with the meeting's type (`session_kind_fits`) and carries no other date and no event ID, posted on the meeting's day or the next day if the committee held no session of that kind then, when the meeting is the committee's only one that day or the title names its subcommittee and that subcommittee met once. Same-day meetings with the same title (a joint hearing entered under each committee) share their records. `--probe-cache` keeps the Senate archive probe's answers in a JSON file so a rebuild takes a minute instead of ten. Meetings without a Congress.gov video link are probed on the Senate archive with an HTTP HEAD (12 threads): Senate and joint-body meetings on their own committee's stream, and House meetings whose title says joint and Senate on the Senate counterpart's stream (`SENATE_COUNTERPART`). `text_source` is chosen in order: `gpo`, `youtube_captions`, `senate_captions`, `video_no_captions`, `no_video`.
- `gpo_parse_check.py`: parses nine prints (House 2008, 2013, 2019 and 2023, an Appropriations volume, Senate 2014, 2019 and 2024, JEC 2017) and prints one line each; exits non-zero when a print yields no turns, loses more than 30% of its words, or produces a heading or bare title as a speaker. Network: the prints and their MODS records.
- `transcribe_compare.py`: positional arguments `package_id`, `video_id`, `out_dir`. Needs `GEMINI_API_KEY`, `yt-dlp`, and `jiwer`. It fetches the print's HTML and calls `mods_people` and `context_for_event` (network, plus the meetings export). It writes `gpo.json`, `routeB.json`, and `compare.json` only. Example: `python docs/youtube-coverage/research/scripts/transcribe_compare.py CHRG-118hhrg54254 8V3OGbZOLB0 /tmp/compare`.

`as_run/` is the scripts as they were run. They contain hardcoded scratch paths (`/tmp/claude-0/...`, and a `REPO` of `/home/user/congressional-tech` in `yt.py`) and need small edits to rerun. The scratch tree used `meetings.jsonl`, YouTube JSON under `d3/` or `d4/`, a `swarm/` copy of `yt.py` with a `cache/` directory, `agents/agent_*/results.jsonl` for the archive pass, and `results/` for `audit.py`.

| Script | Scratch output | Committed as |
|---|---|---|
| `meetings.py` | `meetings.jsonl`, resumed from the same file; API key in `{scratch}/.dgkey`. Congresses 112–119, chambers `house` and `nochamber`. Does not gzip the file | `data/congress_gov_meetings_112-119.jsonl.gz` |
| `links.py` | `links.json`, `oembed.json`; reads YouTube JSON from `{scratch}/d3/` | `data/congress_gov_unknown_videos_oembed.json` |
| `match2.py` | `matched2.json` (package, method, video, score). Diagnostic copy of the matcher | logic lives in `aggregate.py` |
| `meetcov.py` | `meet_none.json`. Two arguments: scratch dir, YouTube JSON dir. Classifies Congress.gov meetings (`Scheduled` and `Rescheduled` only) | not kept |
| `resolve.py` | `{input}.json` from a text file of handles | `data/channel_handles_resolved.json` |
| `sites.py` | stdout only; scrapes House committee sites for YouTube links | not kept |
| `ytsearch.py` | `{scratch}/ytsearch.json` | related to `data/channel_search_broad.json` |
| `yt.py` | disk cache under `swarm/cache/`, 0.5s global throttle | not saved (about 3.6 GB) |
| `web.py` | disk cache; imported by archive agents, not run as a CLI. C-SPAN goes through Zyte (`ZYTE_TOKEN`, or a `.env` under `~/Work/spicy-stack/RefSpec`) | not saved |
| `audit.py` | `results/_merged.json`. Expects packet JSON and `results/{batch}.jsonl` beside the script. Allowed verdicts are the five research labels | not kept; the check is written up in `findings.md` (2,496 claimed videos, 1,335 found claims) |
| `newssearch.py` | `{scratch}/news_candidates.json`, checkpointed every 25 hearings. Argument: scratch dir, which must contain `swarm/yt.py`. Reads `gpo_hearing_videos.csv` for House and joint hearings from the 113th Congress still `no_video_found` or `clips_only`. Searches the title plus year, and `@RollCall`, `@washingtonpost`, `@PBSNewsHour`. Keeps videos of at least 30 minutes whose channel is outside the tracked set (`handle`, `secondary`, and `member_channels`) when `len(title_words ∩ video_words) / min(len(title_words), 10) >= 0.3`, up to five per hearing. A hearing is written only when that filter keeps at least one video | `data/news_search_candidates.json` (441 hearings that had a candidate; `findings.md` says the search covered 825) |
| `verify_news.py` | `video_details.json`, `confirmed.csv`, `review.csv`. Needs `YOUTUBE_API_KEY`. Drops videos under 30 minutes. A row is confirmed when the upload falls on the hearing day through three days after, or the text carries the date or event ID, and the title matches (title similarity at least 0.5, or full-text similarity at least 0.6, or the event ID hits) | `data/news_search_video_details.json`, `agent_results/news_search_confirmed.csv`, `agent_results/news_search_review.csv` |
| `aggregate_agents.py` | `agent_overrides.csv`, `agent_review.csv`. Reads `{scratch}/agents/agent_*/results.jsonl`, not the committed `archive_*.jsonl`. Needs `YOUTUBE_API_KEY`. Maps `found_youtube` to `found_tracked` or `found_untracked` by the channel list, and `found_cspan` / `found_archived` / `found_other_site` to `found_offsite` (URLs in the `video_ids` column). YouTube claims under 20 minutes are forced to low confidence. High and medium rows, plus low rows listed in `accept_low`, become overrides. `not_public` at high confidence is kept. Reads review decisions from `{scratch}/review_decisions.json`; the committed copy is `agent_results/archive_review_decisions.json` | merged onward by `apply_overrides.py` |
| `apply_overrides.py` | rewrites `apps/committee_youtube/data/hearing_video_overrides.csv` in place. An existing `found_tracked` or `found_untracked` row is left in place when the new row is `found_offsite` | that overrides file |
| `news_overrides.py` | rewrites `hearing_video_overrides.csv`: the 14 accepted news-search finds as `found_untracked` (handles from `news_candidates.json`) and nine impeachment volumes as `found_tracked`, replacing the research row and keeping its verdict in the note. Argument: the scratch dir holding `news_candidates.json` | that overrides file |
| `senate_probe_overrides.py` | rewrites `hearing_video_overrides.csv` from a probe CSV: hits become `found_offsite` rows; existing found rows are kept, research negatives replaced | that overrides file |
| `senate_isvp_probe.py` | the CSV given as `argv[1]`, appended and resumed. Senate and joint GPO hearings from the 113th Congress whose matcher status is neither `full_recording` nor `full_recording_offsite`. Filenames `{comm}{MMDDYY}`, `{comm}A{MMDDYY}`, `{comm}B{MMDDYY}`; HEAD on the archive manifest and the live path. Imports `congress_api.senate.isvp` | `data/senate_isvp_probe.csv` |

## Archive investigation (September 2026)

After the news-channel search, eight agents took the 840 House and joint hearings still without a full recording, grouped by committee, and looked off YouTube: C-SPAN's video library listed by hearing date, the Wayback Machine's copies of each committee's hearing pages and every video reference on them, and the archives those pointed to (DVIDS, the Senate's video archive, csce.gov, host organizations). Their verdicts are the `archive_*.jsonl` files above. Every claimed YouTube video was checked with the Data API; finds under 20 minutes were reviewed by hand (`archive_review_decisions.json`). C-SPAN bot-blocks direct clients, so those requests went through the Zyte API.

`aggregate_agents.py` turned the scratch copies of those verdicts into override rows, and `apply_overrides.py` merged them. The committed JSONL is the audit copy of what the agents wrote. `findings.md` records one correction the pass made to the research snapshot: 31 hearings the research agents had marked found on a tracked channel were 1–6 minute member clips (Homeland Security Democrats and JEC Republicans); the archive agents found the full recordings on C-SPAN and in the Senate archive. The live matcher output is compared with `hearing_video_verdicts.csv` to catch that kind of change. Nothing in the pipeline reads the snapshot itself.

## Senate archive probe (September 2026)

The Senate hosts hearing video on its own player (`senate.gov/isvp/?comm=<committee>&filename=<committee><MMDDYY>`), and Congress.gov only started linking it in late 2023. The player's page names the archive path for each committee, so the probe builds the recording name from each hearing's committee and date (with `A` and `B` for a second and third hearing that day), sends a HEAD to the archive manifest and to the newer live path, and records the player URL when either exists. Run as described in the script table, the committed CSV is the 5,251-row file above. Its hits are `found_offsite` rows in `hearing_video_overrides.csv`, written by `as_run/senate_probe_overrides.py`. The probe confirms that a recording exists for the committee and day. `findings.md` notes that several hearings on one day share that recording, on 420 days, and that the probe does not check length.

## News-channel search (September 2026)

The adversarial check's one refuted negative was a Roll Call livestream under a generic title, so every House and joint hearing since 2013 still without a full recording was searched again on YouTube, as `newssearch.py` and `verify_news.py` describe. That left the 26 hearings in `news_search_confirmed.csv`. `findings.md` records the hand review of that list: 14 real recordings on news, witness-organization, or member channels, and a side find of nine volumes of the 2019 impeachment markup whose GPO dates had collided.

The live overrides for those 26 package IDs, after the archive pass and the impeachment correction, are 9 `found_untracked`, 6 `found_tracked`, 8 `not_public`, and one each of `found_offsite`, `partial_only`, and `no_video_found`. Six of the `found_untracked` notes begin `News-channel search:`. Volumes V and X of the markup (`CHRG-116hhrg39405`, `CHRG-116hhrg39410`) are absent from the confirmed CSV and are listed in `archive_review_decisions.json` as `not_public_extra`. Volume I (`CHRG-116hhrg39401`) is `found_tracked`; the other document volumes in the confirmed file are `not_public`.

## Live files outside this folder

These are what the weekly pipeline and `findings.md` read. The app's own notes are `apps/committee_youtube/README.md`. Matcher code is `packages/congress_api/src/congress_api/gpo/match.py`. The Senate player helpers are `packages/congress_api/src/congress_api/senate/isvp.py`.

- `apps/committee_youtube/data/gpo_hearings.csv`: GPO prints. `findings.md` cites 34,559 rows. Current file, 113th Congress on: 15,478 (House 9,234, Senate 5,835, joint 409).
- `apps/committee_youtube/data/gpo_hearing_videos.csv`: one row per GPO hearing, rewritten weekly (34,559 rows, matching `gpo_hearings.csv`). Columns: `package_id`, `congress`, `chamber`, `committee_code`, `held_date`, `hearing_dates`, `record_type`, `status`, `video_ids`, `channels`, `method`, `score`, `video_minutes`, `flags`, `source`, `note`. `gpo-fetch` and `congress-meetings` refill the GPO CSV and the meetings export; both are documented in `apps/committee_youtube/README.md`.
- `apps/committee_youtube/data/gpo_hearing_video_coverage.csv`: hearings per Congress, committee, and status.
- `apps/committee_youtube/data/hearing_video_overrides.csv`: 7,099 rows. Columns: `package_id`, `verdict`, `video_ids`, `channel`, `lock`, `note`. Verdicts: `found_offsite` 5,007, `found_tracked` 1,368, `no_video_found` 360, `partial_only` 235, `not_public` 65, `found_untracked` 64. Three rows have `lock=yes`. The research pass, the news search, the archive investigation, and the Senate probe all land here. There is no single offline script that rebuilds the whole file.
- `apps/committee_youtube/data/youtube_event_id_report.csv`: the weekly per-channel report.
- `packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv`: the channel list (`handle`, `secondary`, `member_channels`).
- YouTube TinyDB exports (`youtube_NN.json`) live on the `pipeline-data` branch, and under `{repo-parent}/pipeline-data/youtube/` for `hearing_text_sources.py`.

## Not saved

- **The cache of fetched YouTube pages (about 3.6 GB),** written by `yt.py` under `swarm/cache/`. It is stale and easy to regenerate.
- **The `web.py` cache** (Wayback, C-SPAN, page fetches).
- **The agents' own working folders (about 150 MB of drafts and page dumps),** including `agents/agent_*/results.jsonl`, `agent_overrides.csv`, and `agent_review.csv`. Their conclusions are in `agent_results/`, and the archive decisions that were kept are in `archive_review_decisions.json`.
- **`audit.py`'s `results/_merged.json`.** The check is summarized in `findings.md`.
- **The caption corpus** (`~/hearing-text/youtube`, 2,374 text files from 3,917 videos tried, 188 of them the uploader's captions; `~/hearing-text/senate`, 719 files from 1,364 recordings tried), about 270 MB, regenerable with `youtube-captions` and `senate-captions` from the IDs and URLs in `hearing_text_sources.csv`.
- **Machine transcripts** other than the two examples in `data/transcribe_compare/`.
- **API keys.** `meetings.py` reads `{scratch}/.dgkey`. `aggregate_agents.py` and `verify_news.py` read `YOUTUBE_API_KEY`. `web.py` reads `ZYTE_TOKEN`. `transcribe_compare.py` reads `GEMINI_API_KEY`. `hearing_text_sources.py` calls Congress.gov only through the meetings file it is given; scripts that call data.gov or Congress.gov themselves read `DATA_GOV_API_KEY` or a key file.
