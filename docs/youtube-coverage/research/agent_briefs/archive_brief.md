# Brief: find public video for House and joint hearings that have none on YouTube

You are one of eight agents. Each gets a batch of about 100 congressional hearings (2013 to date) for which we have found **no full recording on YouTube**, only clips, or nothing. A 16-agent research pass and a YouTube search already ran; their evidence is in each hearing's `research_evidence` field. Your job is to look **beyond YouTube's public channels**: the Wayback Machine, C-SPAN, and any other archive a committee used. Do not repeat the YouTube channel searches.

## Setup

- Repo: `/Users/mikewolfd/Work/congressional-tech` (read-only for you; do not edit or commit anything there).
- Python: `/Users/mikewolfd/Work/congressional-tech/.venv/bin/python` (has `requests`). Run everything from the repo directory.
- Your batch: `SCRATCH/packets/batch_NN.json` (the launcher tells you NN). One object per hearing: `package_id`, `held_date`, `committee`, `committee_code`, `subcommittees`, `title`, `event_id`, `status` (`no_video_found` or `clips_only`), `transcript_url`, `research_evidence` (what the earlier agents found, including dead YouTube IDs and what the committee website said), `research_verdict`, `clips_on_youtube`.
- Shared web client: `SCRATCH/swarm/web.py`. **Always use it for every request**; it caches on disk and rate-limits per host across all eight agents. Read its docstring first. Main calls:
  - `web.cspan_search(query, sdate, edate)` — C-SPAN video library, server-rendered. With `query=''` it lists every program in the date range; filter `kind == 'house-committee'`. `web.cspan_program(url)` gives a program's date, duration and description.
  - `web.wayback_snapshots(url_pattern, from_year, to_year)` — CDX listing (use `*` for prefixes, e.g. `edworkforce.house.gov/calendar/eventsingle.aspx*`). `web.wayback_page(url, timestamp)` fetches an archived page. `web.video_links(html)` pulls every video reference out of it (YouTube IDs, .mp4/.wmv/.wvx/.m3u8 files, Ustream, Vimeo, C-SPAN, Facebook, house.gov streams).
  - `web.yt_status(video_id)` — whether a YouTube video still exists (oEmbed), with its title and channel.
  - `web.transcript_head(url)` — the GPO transcript's first page (exact date, room, "CLOSED" notices, witnesses).
  - `web.get(url, params)` for anything else.
- Write your own scripts in `SCRATCH/agents/agent_NN/`. Batch the mechanical lookups in Python (C-SPAN listing per hearing date, CDX listings per committee site) and read the results, rather than fetching page by page by hand.

## What to check, per hearing

1. **C-SPAN.** List C-SPAN's programs for the hearing date (and the next day for late uploads). A House committee program with a matching title, committee or subject is a find. Open the program page to confirm the date and that it's the proceeding, not a 5-minute excerpt. C-SPAN covers a minority of hearings, so most days yield nothing; that's a real result.
2. **Wayback Machine, committee website.** Find the committee's hearing page for that event as it was archived near the hearing date (the `research_evidence` often names the site and page pattern, e.g. `edworkforce.house.gov/calendar/eventsingle.aspx?EventID=…`, `waysandmeans.house.gov/event/…`, `docs.house.gov`). List the page's video references with `web.video_links`. Then:
   - a YouTube ID: check `web.yt_status`; if it's alive and it's the full hearing, that's a find (report the channel);
   - a video file (`.mp4`, `.wmv`, `.wvx`, `.m3u8`): check whether Wayback archived the file itself (`web.wayback_closest(file_url, timestamp)`); an archived, downloadable full-length file is a find; a dead link is evidence of what once existed, not a find;
   - Ustream/Livestream/Windows Media streams: record them as evidence; they're gone, so not a find;
   - a C-SPAN or Vimeo or Facebook link: follow it.
3. **Other archives, when the evidence points there.** For example DVIDS or defense.gov for Armed Services, DARPA's site, the Helsinki Commission's site (csce.gov, which embeds Facebook video), university or witness-organization sites named in the transcript, the Internet Archive's own video collections (`archive.org/details/…`, search via `web.get('https://archive.org/advancedsearch.php', {...})`). Keep this bounded: two or three targeted lookups per hearing, not an open-ended hunt.

Do not spend more than a few minutes on any one hearing. If everything comes up empty, say so with what you tried.

## Verdicts

Write one JSON line per hearing to `SCRATCH/agents/agent_NN/results.jsonl` **as you go** (append after each hearing, so an interruption loses nothing). Fields:

- `package_id`
- `verdict`: one of
  - `found_youtube` — a public YouTube video of the full proceeding (report `video_ids` and `channel`);
  - `found_cspan` — the full proceeding on C-SPAN (report `urls`);
  - `found_archived` — a full-length recording in the Wayback Machine or another archive, actually retrievable today (report `urls`);
  - `found_other_site` — a full recording on some other live site (report `urls`);
  - `clips_only` — you found only excerpts, on any site;
  - `not_public` — the transcript or page shows it was closed, or the volume is written testimony only;
  - `not_found` — nothing beyond what was already known.
- `urls`: list (may be empty); `video_ids`: list of YouTube IDs; `channel`: YouTube handle or site host;
- `confidence`: `high` (title and date match on the video's own page), `medium` (date and committee match, title generic), `low`;
- `evidence`: two or three sentences saying what you checked and what you saw, with the archived page URL or C-SPAN program title. Include dead video links you found (e.g. a `.wvx` on edgeboss.net) so the record shows what the committee once hosted.

"Full proceeding" means the hearing itself, start to finish or all its parts, not a member's questions, an opening statement or a news package. Two-hour hearings don't come in 12-minute videos.

## Rules

- Never bypass `web.py` for network calls. Don't lower its rate limits. Don't fetch YouTube watch pages (bot-walled); use `yt_status`.
- Report only what you saw. A plausible guess is `not_found` with the guess in `evidence`.
- Don't modify anything under the repo. Don't touch other agents' folders.
- When done, append a final line `{"done": true, "hearings": N, "found": M}` and reply with a short summary: counts per verdict, the sources that worked for your committees, and anything systematic you noticed (e.g. "all Homeland Security 2013 pages link a dead Ustream embed").
