# Research files behind the YouTube coverage findings

These are the inputs, agent outputs and scripts behind `../findings.md` and `../hearing_video_verdicts.csv` (September 2026). They let the results be audited, rebuilt or extended.

## Rebuild the CSV

```bash
python docs/youtube-coverage/research/scripts/aggregate.py --out /tmp/verdicts.csv
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
python docs/youtube-coverage/research/scripts/build_packets.py --out-dir /tmp/packets --channels-csv /tmp/channels.csv
```

With the channel list from commit `7f71208` (the list at the time), this reproduces the 16 original batches exactly.

## Contents

### `agent_briefs/`

The instructions given to the agents, verbatim. File paths in them point to the session's scratch space.

- `research_brief.md`: the 16 research agents, one batch each.
- `verification_brief.md`: the 6 adversarial verifiers.

### `agent_results/`

One JSON line per hearing, as each agent wrote it. Where an agent rewrote a hearing, the last line wins.

- `possible_01…08.jsonl`: research agents for hearings where a tracked channel posted something that week but automatic matching couldn't confirm it (1,294 hearings). Fields: `package_id`, `verdict`, `video_ids`, `channel`, `confidence`, `evidence`.
- `novideo_01…08.jsonl`: research agents for hearings with nothing on a tracked channel that week, or no usable committee code (904 hearings). Same fields.
- `verify_pos_1…4.jsonl`: refuters' outcomes on the 176 riskiest "found" claims. Fields: `outcome` (upheld, revised or refuted), `corrected_verdict`, `video_ids`, `channel`, `evidence`.
- `verify_neg_1…2.jsonl`: challengers' outcomes on a random 90 negative verdicts. Same fields as the refuters.
- `new_channels.jsonl`: official channels the agents found that weren't tracked. All three have since been added to the channel list.

### `data/`

- `swarm_input_hearings.csv`: the 2,198 hearings automatic matching couldn't place, with their status before the research.
- `congress_gov_meetings_112-119.jsonl.gz`: all 13,564 House and joint committee meeting records from Congress.gov (112th–119th Congress). They include event IDs and the official video links, which the channel sweep and the matching used. Fetching these takes about 13,600 API calls.
- `congress_gov_unknown_videos_oembed.json`: the channel behind each Congress.gov-linked video that wasn't in our data.
- `untracked_claim_video_channels.json`: the channel behind each video in a "found elsewhere" claim. `aggregate.py` uses it offline.
- `channel_search_broad.json`, `channel_search_targeted.json` and `channel_search_2007_2012.json`: raw YouTube channel-search results from the channel sweep (about 250 queries).
- `channel_handles_resolved.json`: every handle in the channel list, resolved to its channel ID, title and subscriber count. This is the check that each handle points to the intended channel.

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

## Not saved

- **The cache of fetched YouTube pages (3.6 GB).** It's stale and easy to regenerate.
- **The agents' own working folders (about 150 MB of drafts and page dumps).** Their conclusions are in `agent_results/`.
- **The data.gov API key.** Scripts that call data.gov or Congress.gov read it from `DATA_GOV_API_KEY`, or from a key file in the as-run versions.
