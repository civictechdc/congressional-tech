# YouTube review of merged main — October 26, 2026

**VERDICT: APPROVE. No actionable correctness regression found in the reviewed YouTube path.** All 119 configured IDs agree with their retained source records. Collection, analysis, matching, retention and Explorer still share the same storage identities. Fresh local checks passed; hosted collection and deployed behavior were not checked.

Exact reviewed source: `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`.

The task worktree is `/Users/mikewolfd/.codex/worktrees/natural-resources-youtube/congressional-tech`. Its prior tip `a6083e44a37081784ccf714c87cde3ff10f1bccc` is preserved at `codex/backup-youtube-before-main-review-20261026`. Branch `codex/review-youtube-merged-main-20261026` was rebased onto the exact reviewed revision with no remaining implementation commits: the original repairs were already integrated. Neither superseded throughput commit was replayed. The primary checkout and shared integration worktree were untouched.

## Findings and limits

No blocker, warning requiring a code change, or actionable regression was found. This commit contains only the review report; no implementation fix is proposed.

Observation O1 — evidence boundary: the source identity audit verifies retained successful API responses from October 18–25, 2026, not fresh external availability. The snapshot, observation dates and exact source bytes are identified in `docs/experiments/youtube-channel-ids-20261026.json:2`. The reviewed fetcher still requires a successful API response before writing a refresh (`packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py:143`). No credentialed API run, hosted workflow run, publication, remote pointer change or deployed readback was performed in this review.

Observation O2 — names and identity: a remote `snippet.customUrl` change leaves the configured literal handle as the local storage key (`packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py:163`). Editing that literal handle in the CSV is a separate configuration change and selects a different video table in analysis (`packages/youtube_api/src/youtube_api/analyze/main.py:161`). This repair intentionally preserves the existing literal keys; it does not implement table renaming or history migration. The remote-rename case was executed locally and retained history correctly.

## Patch summary and scope

This reviews the combined merged source, including its current workflow, shared serializer, downstream matching/retention and Explorer calls, rather than treating the old task branch as current proof. The YouTube changes add verified `channel_ids` for 119 primary, secondary and member handles in 52 committee rows (`packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv:1`), validate the mapping, prefer configured or retained IDs, and resolve an unknown handle only until a successful ID is saved.

Directly changed behavior is in `get_channel_id_overrides` (`packages/youtube_api/src/youtube_api/tables.py:66`), fetcher initialization (`packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py:49`) and `get_channel` (`packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py:75`). Its direct caller is the real fetch command (`packages/youtube_api/src/youtube_api/fetch/main.py:49`). Existing channel/video normalization and storage remain the maintained path, traced below.

Exploration hypotheses:

- H1: Complete stable-ID mappings change requests without changing storage identity. **Confirmed** by the source-byte audit, literal-handle writes, and downstream traces below.
- H2: Discovery persists across a process restart, while a remote public-handle change cannot redirect retained history. **Confirmed for the reviewed path** by ID selection/response checks and an executed disk-reopen/rename check. Hosted availability remains outside that conclusion.
- H3: Workflow/package wiring still reaches the changed collector and consumes its retained output. **Confirmed statically** by the installed scripts, bundled CSV declaration and workflow arguments below. Local caller/consumer tests passed; hosted execution was not performed.

## Function trace

All locations are relative to the repository root at the exact reviewed SHA.

| Function or boundary | Source location | Inputs → outputs | Verified behavior |
| --- | --- | --- | --- |
| `get_channel_id_overrides` | `packages/youtube_api/src/youtube_api/tables.py:66` | CSV rows → literal handle/ID mapping | Accepts an absent optional column; rejects a non-object, invalid ID, out-of-row handle or conflicting definition. |
| `map_system_code_committee_handles`, `get_all_committee_handles` | `packages/youtube_api/src/youtube_api/tables.py:37`, `:93` | CSV → ordered committee names and handle lists | Uses the original columns and includes member channels only when requested; does not substitute channel IDs for handles. |
| Fetch `main` / CLI | `packages/youtube_api/src/youtube_api/fetch/main.py:17`, `:88` | CLI paths/selection/key → per-committee fetches | Selects the original row index, includes member handles, runs channel → playlist → detail checks; accumulates individual channel failures and exits 1 after later channels progress. |
| `YoutubeEventFetcher.__init__` | `packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py:49` | Same supplied CSV, cache directory and row index → service/table/mapping | Opens the maintained committee cache and reads the mapping from that CSV. |
| `get_channel` | `packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py:75` | Literal handle, configured/retained IDs → complete API channel item or failure | Searches by literal handle; rejects disagreeing known IDs; sends exactly one `id` or `forHandle` filter; missing/mismatched responses do not reach channel storage. |
| `parse_channel_details` / `SourceModel.source_dict` | `packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py:358`; `packages/youtube_api/src/youtube_api/models.py:7`, `:106` | Complete API item → normalized fields plus complete retained item | Strict known-field validation retains unknown publisher fields and native aliases; both `channelId` and the complete API `id` survive serialization. |
| `store_channel` | `packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py:163` | Literal handle + API item → same keyed channel row | Writes `handle` from the caller, not `customUrl`. Resets scan completion only for a new/changed uploads playlist; upserts by literal handle. |
| `get_all_channel_videos` | `packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py:172` | Retained channel uploads → `youtube_videos_{literal_handle}` | Uses the saved uploads ID; keeps interrupted-scan state and literal table name. A changed API display handle does not create a new table. |
| `insert_videos_into_tb`, `parse_video_details`, `update_video_details` | `packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py:375`, `:393`, `:259` | Native playlist/video records → retained video rows | Keys videos by unchanged `videoId`; complete API records remain separate from normalized claims; details are saved per successful batch. |
| `open_tinydb_for_committee`, `AtomicJSONStorage.write` | `packages/youtube_api/src/youtube_api/tables.py:133`, `:27` | Committee index and JSON tables → same `youtube_{index:02d}.json` | Original file numbering; unchanged Unicode-capable JSON format; uses the shared atomic writer. |
| `write_atomic_bytes` | `packages/congress_shared/src/congress_shared/custody.py:188` | Bytes → sibling temporary file → replaced target | Writes/flushes/fsyncs before replace; failed writes/replaces unlink the temporary file and leave prior target bytes intact. |
| Analyze `main`, `generate_report_for_congress_number`, `write_to_csv` | `packages/youtube_api/src/youtube_api/analyze/main.py:70`, `:142`, `:204` | Original handle lists and cache rows → report CSV | Opens the original literal video table and emits the literal handle; original report columns and date interpretation remain unchanged. |
| `decode_cache`, `YouTubeCache.videos/channels` | `packages/congress_shared/src/congress_shared/youtube_cache.py:33`, `:20`, `:28` | JSON bytes/text/object → unchanged channel rows and literal-table-handle/video pairs | No lookup, normalization, migration, provider imports or acquisition. Preserves order, duplicates and unknown fields. |
| GPO `load_videos` | `packages/congress_api/src/congress_api/cli/gpo_match.py:28` | Numbered cache + committee CSV rows → matching candidates | Takes candidate `channel` from the literal table handle; retains original video ID and committee-code mapping. |
| Inventory / weekly retention | `packages/congress_api/src/congress_api/retention/tables.py:28`; `packages/congress_api/src/congress_api/cli/sync_weekly_tables.py:166` | Same numbered caches/CSV → unchanged video rows or retention rows | Extra CSV field does not alter the index/code mapping; video payloads flow through the shared decoder. |
| Explorer export / YouTube adapter | `apps/committee_youtube/src/committee_explorer/export.py:725`; `packages/youtube_api/src/youtube_api/adapters.py:28` | Saved channel observations and video rows → source/material/channel records | Saves channel observations under the retained handle; video/material identity remains the video ID. The adapter takes actual channel identity from a native row ID, not a table handle; differing supplied channel context produces an explicit issue. |

Library behavior checked: the installed TinyDB implementation in `/Users/mikewolfd/Work/congressional-tech/.venv/lib/python3.12/site-packages/tinydb/table.py` implements `upsert` through `update`, and mapping updates merge fields into the existing record. This supports preservation of `uploads_scan_complete` when the collector omits a replacement value. The local regression and disk-reopen checks also exercise that behavior. The hosted dependency installation itself was not run.

## Data flow and invariants

1. CSV `channel_ids` is created from recorded successful API identities and read into the fetcher's mapping (`tables.py:66`; fetcher `:73`). It escapes only as the fetcher's lookup state; the original handle columns still define committee/cache ordering (`tables.py:37`).
2. `known_ids` combines the configured mapping with retained normalized `channelId` and complete API `id` (`youtube_event_fetcher.py:124`). Multiple different IDs fail before a request; a single invalid retained ID also fails. The temporary `lookup` dictionary chooses exactly one request filter (`:141`). It is not used as a table name.
3. A successful response is checked against the expected ID (`youtube_event_fetcher.py:154`), then normalized and saved with the caller's literal `handle` (`:163`). Unknown handles save their ID here; a later fetcher can load it from disk. A failed discovery remains retryable because it writes no replacement identity (`:150`).
4. Complete API items retain their source aliases and unknown fields (`models.py:7–23`). The normalized `channelId`, uploads playlist and caller handle coexist (`youtube_event_fetcher.py:358–372`, `:163–170`). A changed API `customUrl` updates metadata without redefining the storage key.
5. Collection, report generation, matching and inventory all retain the original committee file index and video table handle. The shared decoder passes rows through unchanged (`youtube_cache.py:20–39`). Explorer assigns material identity from `videoId` and actual channel identity from native `channelId` (`adapters.py:44–81`).

The all-pin audit re-read the exact retained source bytes for all 52 source files. For every one of the 119 entries it checked the recorded file digest/Git blob, source row uniqueness, observation timestamp, API ID, normalized channel ID, API custom URL, uploads playlist, matching committee row and valid ID shape. There were **zero missing/conflicting entries** and no duplicate IDs. It also compared all five original CSV columns and all row ordering against `c466a45e`; they are unchanged. Source evidence is pinned to `b1d1a008b97e0e7e4dfe354fe7f7a8c45ae70ae3`, not whatever a moving branch might contain later.

Workflow reachability:

- Weekly collection sets the maintained CSV path, installs the source packages and calls the declared `youtube-fetch` entry point with `pipeline-data/youtube` (`.github/workflows/update-data.yml:24–50`; `packages/youtube_api/pyproject.toml:16`). The CSV remains bundled by `packages/congress_shared/pyproject.toml:18` and located by `packages/congress_shared/src/congress_shared/resources.py:8`.
- Channel failures stay visible; the later snapshot step still runs after a completed fetch failure (`update-data.yml:59–63`). GPO/meeting work remains independently eligible (`:70–73`). The snapshot script persists the cache directory (`.github/scripts/save-pipeline-data.sh:5–11`). These are traced actions, not actions executed by this review.
- Publication still reacts to relevant source changes or completed collection, installs the source adapter and exporter, and supplies `--youtube-dir pipeline-data/youtube` (`.github/workflows/publish-explorer.yml:5–21`, `:50–53`, `:117–131`). It reuses retained YouTube metadata; publishing a code change alone is not a channel refresh.

## Test behavior and boundary cases

Fresh execution at the reviewed SHA: **72 tests passed, plus 7 subtests**. This is local offline proof. The external APIs were mocked and all created cache data lived in owned temporary directories. No full catalog rebuild was performed.

| Relevant test or boundary | Evidence | Result and execution meaning |
| --- | --- | --- |
| `test_natural_resources_pin_preserves_configured_handles_and_row_order`; `test_all_configured_channels_fetch_by_verified_id_and_keep_literal_handles` | `packages/youtube_api/tests/test_channel_identity.py:32`, `:172` | Passed: retained Natural Resources index/handles; full mocked fetch makes 119 ID-only calls and writes 52 correctly keyed caches. |
| `test_id_lookup_refreshes_existing_channel_and_keeps_video_history` | `test_channel_identity.py:39` | Passed: one channel row refreshed, old video row unchanged, scan marker retained, no ID-named video table created. |
| `test_failed_pinned_lookup_preserves_cache_without_handle_fallback` | `test_channel_identity.py:58` | Both cases passed: empty response returns no channel; mismatched response raises before storage; exact prior cache stays intact and no handle fallback occurs. |
| `test_unpinned_channel_uses_existing_handle_lookup`; `test_custom_csv_without_id_column_keeps_handle_lookup_configuration` | `test_channel_identity.py:75`, `:83` | Passed: a new unresolved channel uses `forHandle`; old custom CSV without the optional field is accepted. |
| `test_selected_committee_fetch_loads_pin_and_uses_only_its_two_channels` | `test_channel_identity.py:89` | Passed: real command wiring limits selection to Natural Resources and creates only its owned temporary cache. |
| `test_new_channel_discovers_once_then_refreshes_by_retained_id`; `test_retained_id_is_used_without_configuration_and_preserved_on_absence` | `test_channel_identity.py:116`, `:128` | Passed: next lookup uses saved ID; either retained ID representation works; absence preserves saved data. |
| `test_conflicting_retained_identity_blocks_lookup_without_changing_history`; `test_invalid_configured_identity_fails_before_fetch` | `test_channel_identity.py:143`, `:157` | Passed: conflicting normalized/API/configured identity and invalid configuration fail without a channel request or changed retained bytes. |
| Retention/fidelity tests | `packages/youtube_api/tests/test_youtube_fetch_fidelity.py:27`, `:37`, `:56`, `:69`, `:76`, `:92`, `:112`, `:123`, `:137` | All passed: complete unknown fields, preserved history, retry after interrupted scan, forced-refresh retention, completed-batch custody and atomic replacement remain intact in the combined code. |
| Analysis callers and time boundaries | `packages/youtube_api/tests/test_youtube_interpretation.py:17`, `:77`, `:99` | Passed within the full package suite: existing custom CSV/table handling and report date semantics remain compatible. |
| Decoder and GPO/inventory callers | `packages/congress_api/tests/test_youtube_cache.py:33`, `:78`, `:99`, `:110`; `packages/congress_api/tests/test_congress_api_cli_refactor.py:90` | Passed: literal table labels, native payloads, ordering and duplicates retained; candidate identity unchanged; malformed input still fails; decoder imports remain isolated. |
| Native channel/recording serialization and associations | `apps/committee_youtube/tests/test_explorer_youtube_adapter.py:92`, `:101`, `:111`, `:138`, `:148` | Passed with the rest of that adapter test file: native channel deduplication, explicit-context disagreements, meeting associations, publication times and bounded availability claims retain their meanings. |
| End-to-end retained-cache export fixture | `packages/congress_api/tests/test_explorer_export.py:227` | Passed: exact cache snapshot digest, complete channel observations, selected native video rows and channel identity survive the real exporter; input bytes remain unchanged. |

Additional executed review checks covered boundaries not directly expressed by the committed identity tests: a fresh fetcher reopened a real temporary cache and reused its saved ID; a remote public-handle rename preserved the original literal handle, old video, scan marker and decoder result; conflicting repeated CSV handle definitions were rejected; and a missing channel still allowed the next channel to succeed before the real command exited 1. These checks used no network and changed no production data. The deliberately logged missing-channel error was expected and asserted.

Local evidence files:

- `/private/tmp/ct-youtube-merged-review-tests-ad222085-20261026.log`
- `/private/tmp/ct-youtube-merged-review-audit-ad222085-20261026.json`
- `/private/tmp/ct-youtube-merged-review-boundaries-ad222085-20261026.json`

Executed pytest inputs: the complete `packages/youtube_api/tests` suite, `packages/congress_api/tests/test_youtube_cache.py`, `apps/committee_youtube/tests/test_explorer_youtube_adapter.py`, and the two named GPO-loader/Explorer-export fixture tests above. The worktree's package source directories came first in `PYTHONPATH`; the existing primary-checkout Python runtime supplied dependencies, and `/private/tmp/ct-v6-index-test-deps` supplied pytest. No installation was required. `git diff --check` passed.

## Conclusion

**VERDICT: APPROVE.** The combined source achieves stable channel lookups while retaining the existing history keys and source fidelity. Coverage of the changed path is **ADEQUATE**, including all configured IDs, persisted discovery, remote handle changes, failure isolation, serializers and real downstream caller fixtures. Confidence is **HIGH for the reviewed local behavior**. Live Data API collection, hosted workflow execution, publication and deployed behavior remain unverified by this review and are not prerequisites for finding a local source regression.
