# Swarm brief: find the YouTube recording for each unmatched House/joint hearing

## Context

We track 81 official congressional committee YouTube channels (57,214 videos) and compare them against GPO's official printed hearing transcripts on GovInfo. After automated matching (Congress.gov video links, event IDs in video descriptions, same committee + date + similar title, subcommittee names in titles), 2,198 hearings since the 113th Congress (2013) still have no confirmed video. Your job is to settle as many as possible, one hearing at a time, with evidence.

You have one batch file of hearings (JSON list). Each entry has:

- the GPO metadata: `package_id`, `held_date`, `title`, `committee_name`, `subcommittees`, `event_id` (Congress.gov event ID, often blank), `serial`, `witness_count`, and `transcript_html` (the official transcript);
- `status_so_far`:
  - "possible match..." means a tracked channel for that committee posted something within a few days but the title didn't match;
  - "no video found" means nothing was posted on a tracked channel that week;
  - "committee not tracked" means GPO's committee code was blank or bad;
- `committee_code_used` and `tracked_channels`: our channels for that committee;
- `candidate_videos`: every video on those channels from 2 days before to 7 days after the hearing, with title, description excerpt and publish date;
- `congress_gov_meetings_same_committee_near_date`: Congress.gov meeting records (event ID, title, type, status, any video URLs).

The batch files are large. Load and work through them in Python rather than reading them whole into context.

## Tools

Use the shared helper for every YouTube request. It caches responses on disk and rate-limits across all agents, so we don't get bot-blocked.

```python
import sys; sys.path.insert(0, "/tmp/claude-0/-home-user-congressional-tech/7872f730-5ed2-5705-be27-7b4b1fc085b7/scratchpad/swarm")
import yt
yt.search(query)                       # YouTube video search: videoId, title, channel handle, relative date
yt.channel_search("@Handle", query)    # search inside one channel (finds videos by title words)
yt.oembed(video_id)                    # channel + title of any video id, including unlisted ones
yt.local_videos(code, start, end, text=None)  # our tracked videos for a committee in a date range (no network)
yt.meetings(code, start, end)          # Congress.gov meeting records for a committee (no network)
yt.transcript_head(transcript_html)    # title page of the official transcript: date, place, "closed" notices
```

Rules for network access:
- Don't use `yt-dlp`, and don't fetch youtube.com watch pages directly: they're bot-walled from this server.
- Don't hit YouTube outside `yt.py`.
- Committee websites (*.house.gov) can be fetched with `requests`. They often have a hearing page with an embedded video. Be polite: under 1 request per second.
- web.archive.org and c-span.org are blocked here.

## How to judge

For "possible match" rows, first judge the candidate videos yourself. Committees often post hearings under generic or shortened titles, such as:
- "Subcommittee on X Hearing";
- "Full Committee Markup";
- "Budget Hearing – Dept. of Y";
- the witness's name;
- "Part 1"/"Part 2".

Descriptions often carry the hearing title or an EventID. A candidate counts as the hearing only if it is a recording of that proceeding (livestream or full or near-full upload, possibly split into parts). A member's statement clip or a press conference about it is `partial_only`.

When candidates don't settle it, or the row is "no video found":
1. Search YouTube: the hearing title (or its distinctive half), plus committee/subcommittee name and year.
2. Try `channel_search` on each tracked channel with distinctive title words. Videos can be posted weeks later, or be missing from our data because they're unlisted.
3. Widen `local_videos` to ±30 days with a text filter on distinctive words.
4. Check the transcript's title page. It shows "CLOSED" or "Executive Session" for closed hearings, and the city for field hearings.
5. Optionally, find the hearing page on the committee's website and look for an embedded YouTube ID. Then resolve that ID with `yt.oembed`.

Spend effort where it pays: judge candidates in bulk, and search only when needed. If a committee's pattern becomes obvious (e.g. "this channel didn't post subcommittee hearings in 2013"), note it and apply it with a quick spot check rather than exhaustive searching.

## Verdicts (one per hearing)

- `found_tracked`: a recording of this hearing is on one of `tracked_channels`. Give its video ID or IDs.
- `found_untracked`: a recording is on a channel we don't track. This includes:
  - another committee's channel;
  - a member's personal channel;
  - a news or C-SPAN YouTube upload of the full hearing.
  Give video ID(s) and the channel handle.
- `partial_only`: only clips or statements from it exist on YouTube.
- `not_public`: evidence it was never public video. Examples: a closed or classified session; a briefing or roundtable that wasn't streamed; a transcript-only record such as an errata or placeholder. Cite the evidence.
- `no_video_found`: you searched and found nothing.

Confidence levels:
- `high`: the title or description clearly identifies the hearing, and the date fits.
- `medium`: likely, e.g. a generic title, but the right subcommittee on the right day.
- `low`: weak.

Never invent video IDs. Every ID you report must come from `candidate_videos`, `local_videos`, `search`, `channel_search`, or a committee web page, and must resolve with `yt.oembed`.

## Output

Write one JSON object per hearing, one per line, to `/tmp/claude-0/-home-user-congressional-tech/7872f730-5ed2-5705-be27-7b4b1fc085b7/scratchpad/swarm/results/<batch-name>.jsonl`, with exactly these keys:

```json
{"package_id": "...", "verdict": "found_tracked|found_untracked|partial_only|not_public|no_video_found", "video_ids": ["..."], "channel": "@handle or ''", "confidence": "high|medium|low", "evidence": "one or two sentences: why"}
```

- Write results incrementally as you go (append), so progress survives if you're interrupted.
- Every hearing in your batch must get exactly one line.

If you find an official committee, subcommittee, select committee or commission channel that is not in any `tracked_channels` list, also append a line to `/tmp/claude-0/-home-user-congressional-tech/7872f730-5ed2-5705-be27-7b4b1fc085b7/scratchpad/swarm/results/new_channels.jsonl`:

```json
{"handle": "@...", "channel_url": "...", "channel_name": "...", "committee": "...", "evidence": "..."}
```

Leave out member and news channels, but still use them as `found_untracked` evidence.

Your final message should be a short summary:
- counts per verdict;
- committee-level patterns you noticed;
- any new channels;
- anything you couldn't finish.

Don't modify anything in the git repository.
