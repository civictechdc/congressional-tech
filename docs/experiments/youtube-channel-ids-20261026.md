# Stable IDs for all configured YouTube channels

Implemented locally: all **119 channels across 52 committee rows** now use verified stable IDs. Literal handles, committee row order, cache filenames, and video table names remain unchanged. No production cache or remote state was changed.

The change extends commit `55a77fadd6ba34613b3b73008bbe0fde247b62be` in `/Users/mikewolfd/.codex/worktrees/natural-resources-youtube/congressional-tech`. Applying it elsewhere requires that preceding Natural Resources repair as well.

## Identity evidence

[The backfill record](youtube-channel-ids-20261026.json) names immutable source snapshot `b1d1a008b97e0e7e4dfe354fe7f7a8c45ae70ae3`, the cached `origin/pipeline-data` revision from October 25, 2026. Each mapping records its source path, Git blob, SHA-256, observation time, API custom URL, channel ID, and uploads playlist.

For every configured primary, secondary, and member handle, the committee cache contained exactly one retained channel row. The normalized `channelId` agreed with the complete API item's `id`; its `snippet.customUrl` matched the literal configured handle ignoring case; its uploads playlist agreed with the normalized record. All IDs had the expected `UC` plus 22-character form. There were no missing mappings, conflicting mappings, or repeated IDs. The existing Natural Resources pin agreed with its retained record.

Successful source observations range from October 18 through October 25, 2026. This verifies the retained identity association, not current external availability. No fresh Data API credential was available; no live all-channel refresh was performed. The earlier official-site and live YouTube verification for Natural Resources remains in its separate dated report.

## Lookup behavior

The maintained CSV now fills the existing `channel_ids` field for every row. The existing reader and fetcher consume those mappings; no second configuration format or alternate collection path was added.

For an unpinned channel, the fetcher uses an ID already retained in `channelId` or the complete API item. A channel with no known ID resolves its handle once and saves the response, so later refreshes use its retained ID. Configured and retained IDs must agree. Conflicts fail before a channel request or cache update; absent and mismatched responses retain history and report failure without a handle fallback. Configuration rejects malformed IDs, mappings to handles outside the committee row, and conflicting definitions.

The concrete improvement is removing repeated dependence on handle resolution while reusing the maintained API, cache, and CSV paths. No speed or resource improvement is claimed.

## Local verification

- **41 passed:** the full offline `packages/youtube_api/tests` suite.
- The mocked full fetch covers all 119 configured channels. Every request uses `id`, all 52 temporary committee cache files retain their expected literal handles, and no handle lookup occurs.
- Focused checks cover retained history, one-time discovery, ID reuse from either retained field, empty and mismatched responses, identity conflicts, invalid configuration, old CSV files without the optional column, and the selected Natural Resources path.
- A comparison with the preceding commit confirms all five original CSV columns and all row ordering are unchanged.
- `git diff --check` passed.

Tests ran with this worktree's source first in `PYTHONPATH`, the primary checkout's existing Python runtime dependencies, and pytest from `/private/tmp/ct-v6-index-test-deps`. Only owned temporary test caches were written. No dependency installation was needed.

Changed files: the shared channel CSV; `youtube_api/tables.py`; `fetch/youtube_event_fetcher.py`; `tests/test_channel_identity.py`; the package README; this report; and its evidence JSON.

Production proof still requires a credentialed refresh using this reader and CSV together. Existing playlist/video collection, analysis, inventory, and Explorer history associations keep their maintained paths. No push, PR, merge, deployment, publication, remote pointer change, or job restart was performed. Unrelated primary-checkout work was preserved.
