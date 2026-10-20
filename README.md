# pipeline-data

Raw caches for the weekly `Update committee data` workflow (`.github/workflows/update-data.yml` on main). This branch is replaced by a single snapshot commit on every run, so it never accumulates history. Don't commit here by hand.

- `youtube/youtube_NN.json`: TinyDB caches of every tracked channel's videos (title, description, publish date, caption flag, duration). NN is the committee's row in `youtube-accounts.csv`.
- `congress_meetings.jsonl.gz`: Congress.gov committee meeting records (House, joint and Senate), including official video links.

The derived outputs (per-channel report, GPO hearings, hearing-to-video matches) are committed to main under `apps/committee_youtube/data/`.
