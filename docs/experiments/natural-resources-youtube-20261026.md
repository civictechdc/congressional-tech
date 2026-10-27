# Natural Resources Democrats YouTube lookup repair

Decision: Keep the retained handle `@NRDems` and look up its verified stable channel ID, `UCB6LGE5-_i-xxtZxk1_SeTg`. This is a local repair of the maintained reader. Production recovery remains unverified.

## Verified source identity

Read-only checks on October 26, 2026 establish the following chain:

1. The [official committee video page](https://democrats-naturalresources.house.gov/media/videos) returns 200 and embeds `QCyGM5fmBt4` (alongside another video). Its channel link still uses `/user/NaturalResourcesDems`.
2. The [embedded video's YouTube watch page](https://www.youtube.com/watch?v=QCyGM5fmBt4) returns 200. Its `ytInitialPlayerResponse.videoDetails` names House Natural Resources Committee Democrats and gives `channelId=UCB6LGE5-_i-xxtZxk1_SeTg`. Its owner profile still names `@NRDems`.
3. The [stable channel page](https://www.youtube.com/channel/UCB6LGE5-_i-xxtZxk1_SeTg) and [channel feed](https://www.youtube.com/feeds/videos.xml?channel_id=UCB6LGE5-_i-xxtZxk1_SeTg) return 200 and identify the same committee channel. The feed includes the official embedded video and recent hearing uploads.
4. Direct requests to `@NRDems`, `@NaturalResourcesDems`, and `/user/NaturalResourcesDems` return 404. A working stable ID therefore has stronger current evidence than a guessed replacement handle. Search indexes still return old successful handle pages; those cached results do not establish current resolution.

[The evidence JSON](natural-resources-youtube-20261026.json) records check time, URLs, status, response digest/size, and selected identifying fields. It does not retain full response bodies or claim complete source replay. No YouTube Data API credential was available locally, so these checks do not establish `channels.list(id=...)` success. Google's [maintained API reference](https://developers.google.com/youtube/data/reference/rest/v3/channels/list) supports the `id` filter and requires exactly one filter.

## Change and retained history

The existing CSV's optional `channel_ids` column maps literal handles to verified stable IDs. Only `@NRDems` is pinned. The fetcher reads the same supplied CSV, requests `channels.list(id=...)` for that entry, and uses `forHandle` for unpinned channels. Older custom CSV files without the column retain their existing lookup behavior.

The CSV row stays at index 11 with handles `@NaturalResourcesGOP` and `@NRDems`. The TinyDB filename remains `youtube_11.json`; video tables remain keyed by the literal handle. Channel metadata refreshes under that same handle. No migration, renamed table, removed video, changed video ID, or changed historical hearing association is required. A missing or mismatched ID response preserves retained data and does not fall back to a possibly reassigned handle.

The existing command already continues through individual channel failures, retains completed writes, and exits nonzero after reporting failures. This repair leaves that behavior in place and does not suppress a source failure.

## Checks

Base: `c466a45e09e27bde48ade12454f8b458c3643d21`.

Worktree: `/Users/mikewolfd/.codex/worktrees/natural-resources-youtube/congressional-tech`.

Local checks: **16 passed** across `packages/youtube_api/tests/test_channel_identity.py` and `packages/youtube_api/tests/test_youtube_fetch_fidelity.py`; `git diff --check` passed. Tests cover the configured pin, unchanged row/handles, retained channel/video history, empty and mismatched responses, unpinned handle behavior, old CSV compatibility, and the complete mocked `main(..., committee_name="Natural Resources")` path. That selected run makes only the committee's two channel lookups and writes only its owned temporary `youtube_11.json`. Existing fidelity checks cover interrupted refresh and atomic retention.

Runtime dependencies came from the primary checkout's existing Python environment, with this worktree's source directories first in `PYTHONPATH`; pytest came from the existing `/private/tmp/ct-v6-index-test-deps` directory. No package installation or primary-checkout writes were needed.

## Integration limits and next check

Before calling the source refreshed, use a credentialed, committee-only `youtube-fetch --committee-name "Natural Resources" --channels-csv-path ... --tinydb_dir ...` against a separate retained-cache copy. Confirm `channels.list(id=...)` returns the pinned ID and that uploads/details complete under the existing `@NRDems` table. The working public ID page/feed supports the repair but cannot guarantee Data API availability or a successful full playlist scan. No production data was changed and no all-channel refresh was run.

The optional column is consumed by the fetcher only. Existing mapping, analysis, inventory, and Explorer readers continue to use unchanged literal handles. Deploy the reader and bundled CSV together; a custom CSV that omits the pin will continue using the failing handle lookup. GPO, news-lake, viewer, publication, and workflow changes belong to other scopes and are not assumed complete.

No push, PR, merge, deployment, R2 publication, remote pointer change, or job restart was performed. The primary checkout's unrelated planning files were preserved.
