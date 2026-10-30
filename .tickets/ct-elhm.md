---
id: ct-elhm
status: closed
deps: []
links: [ct-uov2, ct-v967]
created: 2026-10-22T17:34:59Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-syem
tags: [youtube-api, duplication, smells, bug]
---
# Clean up youtube_api code smells: reuse congress_shared.custody/webvtt, fix mutable globals & sys.argv defaults, and stop caching network errors as 'none'

CS300 Audit Finding (Committee, Naming & YouTube Auditor - packages/youtube_api):
1. Duplication with congress_shared: (a) youtube_api re-implements atomic temp-file writes 4 times (tables.py:28-39 AtomicJSONStorage.write; captions/main.py:79-81, 101-103, 167-172) instead of using congress_shared.custody (write_atomic_text/write_atomic_json); (b) captions/main.py:32-48 re-implements WebVTT parsing (vtt_to_text) instead of using congress_shared.webvtt; (c) 5 separate TinyDB youtube_{i:02d}.json readers exist across youtube_api/tables.py, congress_api/cli/gpo_match.py:28-45, sync_weekly_tables.py:61-77, retention/tables.py:28-56, and committee_explorer/export.py:681-709 while congress_shared.youtube_cache is unused by youtube_api.
2. Silent Error Swallowing & Permanent 'none' Caching Bug: captions/main.py:91-92 catches bare except Exception: around yt_dlp and writes status 'none' to captions_index.csv (line 103), permanently caching transient network/proxy/rate-limit errors as 'no captions exist'. Similarly, youtube_event_fetcher.py:139-145 catches except Exception and returns {}.
3. Code Smells & Dead Code: (a) Dead class attribute videos_tbs = {} (youtube_event_fetcher.py:47, 74, 192) and phantom get_event() in docstring (line 40) + wrong return types in docstrings (lines 95-105, 217-229); (b) Mutable module globals _TINYDB (analyze/main.py:36, 90, 157) and YDL_OPTS (captions/main.py:51, 85, 186); (c) Import-time default argument args: list[str] = sys.argv[1:] in fetch/main.py:86, analyze/main.py:163, captions/main.py:109; (d) Runtime assert statements in tables.py:52, 121-123 and youtube_event_fetcher.py:72, 132; (e) parse_iso8601_duration (youtube_event_fetcher.py:25-33) fails on P1DT... day durations; (f) Public function typos get_all_committee_handless (tables.py:75) and get_all_commitee_names (tables.py:86); (g) Empty package.json / turbo.json in youtube_api.

## Acceptance Criteria

1. Delegate atomic writes and WebVTT parsing in youtube_api to congress_shared.custody and congress_shared.webvtt. 2. Distinguish transient yt_dlp/API errors from 'no captions available' in captions/main.py:91-103 and youtube_event_fetcher.py:139-145. 3. Remove dead videos_tbs, replace runtime asserts with explicit exceptions, fix sys.argv[1:] defaults to None, eliminate mutable globals _TINYDB/YDL_OPTS, support day durations in parse_iso8601_duration, and add properly spelled get_all_committee_handles / get_all_committee_names aliases.


## Notes

**2026-10-22T17:42:50Z**

Subagent Self-Review Additions:
- Delete stale packages/youtube_api/src/youtube_api.egg-info/ directory alongside package.json and turbo.json cleanup.

## Audit 2026-10-24

- Verdict: PARTIAL (batch syem).
- Grades: proposal 60 → 60, work 66 → 66.
- Problem: The handler was *broadened* to `except (DownloadError, Exception)` (`captions/main.py:92`), so programming errors now become silent, retryable `error` rows.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:89
- Status: Closed as superseded by the simplification plan (WS12, ct-uov2): the remaining item (the `_TINYDB` global) is polish with no observable behavior. Not covered: the broadened `except (DownloadError, Exception)`, which turns programming errors into retryable rows.
- See docs/reviews/2026-10-24-ticket-audit/README.md

**2026-10-24T18:47:54Z**

Reopened after the Oct 24 audit. captions/main.py:92 catches 'except (DownloadError, Exception)', so programming errors become silent, retryable error rows and can hide raw caption-capture failures. Done when: only DownloadError (and named transient errors) are retried, and other exceptions fail the run, with a test.

**2026-10-30T16:49:25Z**

Fixed in commit 91c2f86c: narrowed packages/youtube_api/src/youtube_api/captions/main.py:92 from except (yt_dlp.utils.DownloadError, Exception) to except (yt_dlp.utils.DownloadError, OSError, TimeoutError) so programming errors propagate instead of becoming silent retryable error rows. Verified by test_youtube_programming_errors_propagate_instead_of_becoming_retryable_error_rows in packages/congress_api/tests/test_caption_source_fidelity.py (74 passed across test_caption_source_fidelity.py, test_caption_inventory_receipts.py, and packages/youtube_api/tests/).
