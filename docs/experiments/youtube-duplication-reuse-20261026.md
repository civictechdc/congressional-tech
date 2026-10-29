# YouTube: reuse configuration, page indexes and issued digests

Implemented locally on base `7242f0419f589ffcf9e52f5f5068fb4edd5b6c44`. This removes the approved local repeats while preserving the maintained API calls, literal cache names, source records and per-page durability. No source acquisition, remote change, publication or deployment was performed.

## Measured fixture operation reductions

The accepted baseline is the read-only validation at `output/duplication-validation-20261026/youtube/report.md` in the primary checkout. The same small maintained-entry-point fixtures and instrumentation were replayed on this isolated candidate; no replacement collector or database was benchmarked.

| Operation / fixture | Baseline | Candidate |
| --- | --- | --- |
| CSV opens in the full 52-committee fetch command | 54 | 1 |
| JSON row-map parses in that command | 2,704 | 52 |
| Retained-video index rebuilds across two playlist pages | 2, visiting 3 then 4 rows | 1, visiting 3 rows |
| Discarded ordinary search in force mode | 1 | 0 |
| Whole-cache reads/parses for one mixed update/insert page | 3 | 2 |
| JSON serializations / durable writes / write-payload hashes for that page | 2 / 2 / 2 | 1 / 1 / 1 |
| Identical payload hashes with weekly staging enabled | 2 | 1 |

Fake request counts stayed the same: 119 channel metadata and 119 empty-playlist requests in the full-config fixture; two requests in the two-page scan; one details batch in both force/nonforce fixtures. Force still refreshes the fresh video intentionally. The change removes local work, not downloads. These are operation counts on constructed fixtures, not production speed, memory or throughput measurements. A newly opened TinyDB may need an additional initial read for its maintained document-ID allocator; the cache-read counts above describe the seeded mixed-page fixture.

## Why the structure changed

`load_committee_configuration` reads the CSV once and applies the same metadata and channel-ID validation helpers to those rows. Fetch `main` derives committee names/handles and selection from that snapshot, then shares the ID mapping with its fetchers. Existing standalone configuration readers and fetcher construction remain supported. There is no global configuration cache: the next command reads changed bytes and validates them again. Existing analysis/date and export aggregation code is unchanged.

A channel scan builds one video-ID → **all** document IDs mapping and updates it only after each page's write succeeds. Duplicate source rows remain separate; every existing document matching a video ID is refreshed. Incoming duplicates retain the previous last-item-wins behavior. New entries on an overlapping page are saved before the scan stops.

TinyDB 4.9.0 has public bulk-update and bulk-insert operations but no public mixed update/insert transaction. The page callback uses its maintained `Table._update_table` hook once and delegates allocation to `Table._get_next_id`. TinyDB still owns document-key conversion, cache invalidation and the storage write. No second database/storage implementation or delayed channel-wide cache was introduced. The existing `AtomicJSONStorage` → shared atomic writer still flushes/fsyncs and replaces the file for each accepted page; detail batches retain their existing checkpoint behavior. The one remaining generic write-payload digest receipt was left alone outside this scope.

Force mode now selects all retained videos directly. Weekly YouTube staging uses the digest returned by `stage_body_bytes` for the exact serialized payload; nonstaged and already-supplied-digest behavior remains unchanged. Other callers in the shared retention module were left untouched.

## Verification

Baseline: **41 passed**, the existing YouTube package tests before edits.

Final focused checks: **91 passed, 7 subtests passed**. Command, from the worktree root with its source directories first in `PYTHONPATH` and existing `/private/tmp/ct-v6-index-test-deps` for pytest:

```sh
/Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest -q -p no:cacheprovider \
  packages/youtube_api/tests \
  packages/congress_api/tests/test_youtube_staging_digest_reuse.py \
  packages/congress_api/tests/test_youtube_cache.py \
  apps/committee_youtube/tests/test_explorer_youtube_adapter.py \
  packages/congress_api/tests/test_congress_api_cli_refactor.py::test_video_loader_preserves_cache_table_channel_identity \
  packages/congress_api/tests/test_explorer_export.py::test_youtube_cache_preserves_snapshot_channels_rows_and_export_limit
```

New tests cover one CSV read for full/name/index selection; changed configuration on the next command; one index across pages; duplicate/noncontiguous document IDs and stable row order; unknown and upstream-field retention; incoming last-item-wins behavior; query-cache invalidation; one durable mixed-page write; malformed-page refusal; failed fsync/replace leaving disk and index unchanged; retry; accepted first-page bytes before a later request fails; incomplete-scan replay; insertion before overlap stop; and force refresh of fresh videos without the discarded search. Staging tests cover exact dict/list/string/bytes/bytearray serialization, changed payload identities, nonstaged hashing and supplied-digest behavior.

Candidate probe/evidence directory: `/Users/mikewolfd/.codex/worktrees/youtube-duplication-reuse/congressional-tech/output/youtube-duplication-reuse-20261026/`. It contains the pre-comparison note, adapted probe, raw JSON/log and regression log. Reproduce the five approved count probes with:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/private/tmp/ct-v6-index-test-deps \
/Users/mikewolfd/Work/congressional-tech/.venv/bin/python \
  output/youtube-duplication-reuse-20261026/probe.py
```

No dependency installation, credentials read, external request, full suite or native build was needed. `git diff --check` passed. The primary checkout and other sessions' source worktrees were not edited.

## Integration and limits

Worktree: `/Users/mikewolfd/.codex/worktrees/youtube-duplication-reuse/congressional-tech`; branch: `codex/youtube-duplication-reuse`. Root owns integration; no push or main merge was performed here.

The page callback deliberately depends on two protected TinyDB hooks, tested against installed 4.9.0; its focused disk, allocation and cache-invalidation tests must remain when upgrading that dependency. Its index lasts only for the owned channel scan and assumes the existing single-writer collector model. Atomic file writes are not removed. The source's separate report/date/export passes and other services' digest paths remain outside this task. Hosted refresh and release performance remain unverified.
