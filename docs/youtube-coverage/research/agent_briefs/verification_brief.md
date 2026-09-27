# Verification brief: adversarially check the swarm's verdicts

A first swarm of agents assigned a verdict to each of 2,198 congressional hearings that have an official GPO transcript but no automatically matched YouTube video:

- `found_tracked`: a full recording is on one of our tracked committee channels;
- `found_untracked`: a full recording is on some other channel;
- `partial_only`: only clips exist;
- `not_public`: it was never public video;
- `no_video_found`: nothing was found.

You are checking a subset of those verdicts, independently and skeptically. Each entry in your batch file has:
- the hearing's GPO metadata (`title`, `held_date`, `committee_name`, `subcommittees`, `event_id`, `witness_count`, and `transcript_html`, the official transcript);
- the first agent's `claim`.

## Tools

The shared helper is rate-limited and cached. Use it for every YouTube request; never use yt-dlp, and never fetch watch pages.

```python
import sys; sys.path.insert(0, "/tmp/claude-0/-home-user-congressional-tech/7872f730-5ed2-5705-be27-7b4b1fc085b7/scratchpad/swarm")
import yt
yt.search(query)               # videoId, title, channel, relative date, length ("1:49:27")
yt.channel_search("@Handle", q)
yt.oembed(video_id)            # channel + title of any video id
yt.local_find_video(video_id)  # our stored copy: publishedAt, full title and description (tracked channels only)
yt.local_videos(code, start, end, text=None)
yt.meetings(code, start, end)  # Congress.gov meeting records (event IDs, titles, official video links)
yt.transcript_head(url, chars) # official transcript text: date, time convened and adjourned, witnesses, place
```

- Committee websites (*.house.gov) can be fetched politely with `requests`.
- web.archive.org and c-span.org are blocked from here.
- Load your batch in Python. Don't read the whole file into context.

## What to do

If your batch is `verify_pos_*` (claims of a found recording), try to REFUTE each claim. Check that the claimed video or videos are really a recording of this specific proceeding, not:
- a different hearing the same day;
- a clip, opening statement or press conference;
- a news package;
- the wrong year.

Evidence to check:
- the video title and description, from `local_find_video` or `oembed`;
- its length (find it with `search` or `channel_search` on its title) against the hearing's length, which the transcript gives as time convened and adjourned;
- the witnesses named in the transcript against those in the description or title;
- the date;
- Congress.gov meeting records for that day, which show whether several hearings competed for the slot.

If the claim is a multi-hearing Appropriations volume, check that the videos correspond to hearings listed in the volume.

If your batch is `verify_neg_*` (claims that no full recording exists), try to FIND one the first agent missed. Search with varied phrasing, including:
- the witness names;
- the subcommittee plus the date;
- the bill number;
- the tracked channels via `channel_search`;
- `local_videos` over a ±400-day window with distinctive words, since late archive uploads are common.

Only overturn a claim when the evidence is clear.

## Output

Write one JSON line per entry, appending as you go, to `/tmp/claude-0/-home-user-congressional-tech/7872f730-5ed2-5705-be27-7b4b1fc085b7/scratchpad/swarm/results/<batch-name>.jsonl`:

```json
{"package_id": "...", "outcome": "upheld|refuted|revised", "corrected_verdict": "found_tracked|found_untracked|partial_only|not_public|no_video_found", "video_ids": ["..."], "channel": "@handle or ''", "evidence": "one or two sentences"}
```

- `upheld`: the claim stands. Use the same verdict and videos.
- `refuted`: the claim is wrong. Give the correct verdict and the right videos, if any.
- `revised`: the claim is partly right. For example, the verdict stands but a video ID is wrong or missing, or a positive should really be `partial_only`.

Every entry needs exactly one line. Every video ID you give must resolve with `yt.oembed` or exist in local data. Don't modify the git repository.

Your final message should be a short summary: counts of upheld, refuted and revised, the most common failure mode you saw, and any systematic issue the first swarm had.
