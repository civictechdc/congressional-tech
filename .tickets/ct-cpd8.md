---
id: ct-cpd8
status: in_progress
deps: []
links: []
created: 2026-11-09T04:47:42Z
type: bug
priority: 3
assignee: mikewolfd
---
# Two production-offline tests time out under machine load


Two tests in the production-offline lane fail only as timeouts when the
machine is busy, and pass alone through the runner.

- `packages/corpus_recovery/tests/test_qualification.py::test_timeout_preserves_evidence_and_next_invocation_retries`:
  the second `qualify` call with `timeout_seconds=0.5` returns `unresolved`
  instead of `qualified`; the 0.5 s budget is too small for a worker start
  under load.
- `packages/viewer_publication/tests/test_page_metadata_model.py::test_shared_html_reader_fixture`:
  `ParserWorker._start` raises `Parser startup failed` because the filename
  worker does not print `ready` within `max(5, timeout_seconds)` seconds.

Evidence: full lane on `ead26e7c` (main 2599519e plus body-text-producer),
2026-11-08 22:40 to 23:44 EST, load average 14.8 / 17.3 / 18.9 from other
sessions' agents and Docker stacks; 12246 passed, 2 failed. Both files rerun
alone: 33 passed in 40 s. Parser-worker import (`python -I -c 'import
congress_api.lake.filenames'`) is 0.2 s warm on both the branch and main,
and the body-text branch loads no spicy_docs or pyobjc module on that path.
Log: `.cache/archive-release/investigations/body-text-lane-ead26e7c-20261108.log`.

Fix candidates: give both tests a start budget that scales with load (or a
pre-warmed worker), rather than fixed 0.5 s and 5 s deadlines. Until then,
treat these two as load timeouts when they fail together under load > 8.

## Notes

**2026-11-09T14:38:21Z**

2026-11-09: both tests passed in two later full lanes on quieter machines (ct-8unc lane at 1ae30211, load 9-14, 12258 passed; MODS lane at 525d20ba, load 3-4, 12312 passed). Confirms load-only. Fixed 0.5 s / 5 s deadlines remain the cause; still open for the deadline fix.

**2026-11-09T16:40:37Z**

2026-11-09: fixed on claude/ct-thread1-unattended; the orchestrator closes it after the lane.

Measured quiet on this Mac (load 5, 14 CPUs): a real qualify of the 2-page fixture takes 0.30-0.33 s against the old 0.5 s budget (1.6x headroom). A parser-worker import takes 0.18 s against a 5 s startup deadline, which the 11-08 lane still missed at load 15-19.

- test_qualification.py::test_timeout_preserves_evidence_and_next_invocation_retries: both calls use the default config (180 s), which keeps one cache key, so the retry still proves the timeout was not cached. The first call's q.time is a clock that reads real time for the budget's start and then far past it, while the real sleeper subprocess still runs and is killed through the real path. The test no longer depends on wall time.
- ParserWorker startup: the deadline is now max(STARTUP_SECONDS=30, timeout) instead of max(5, timeout). The child reads no input at startup, so this only outlasts a busy host. Per-input timeouts and startup crash errors are unchanged (test_parser_worker.py passes). The nightly gets the same protection. parser_worker.py is a shared reading file, so reading-version evidence was re-snapshotted (only workspace_sha256 moved; the change is equivalent).

Results: test_qualification.py 22 passed in 6.95 s; test_page_metadata_model.py 11 passed in 19.57 s; test_parser_worker.py 14 passed (all partial, exit 0).

**2026-11-09T20:20:35Z**

2026-11-09: the parser-worker startup wait (max(5, timeout)) is hashed into the filename producer identity (lake/filenames/__init__.py current_version names retention/parser_worker.py), so raising it moved filenames.current_version and failed the three checked-in job-spec pin tests. Reverted that hunk; only the qualification test's budget change remains. The startup wait stays 5 s and is scheduled as an identity bump with the next intentional filename version change. Evidence: the test passed twice on quiet machines (ct-8unc and MODS lanes).

**2026-11-09T21:16:13Z**

2026-11-09: full lane on 489f026f is green under load 25-38 (production-offline 12338 passed, 39 skipped, exit 0, 3166 s; storage-loopback 34 passed, exit 0). Log: .cache/archive-release/investigations/thread1-lane-489f026f-20261109.log. The qualification-test half is done.

Remaining half, confirmed on main 16084de5 by the CT session: lake/filenames/__init__.py current_version hashes retention/parser_worker.py (and process_resources.py) as declared inputs, while lake/versions.py lists retention as excluded plumbing. The reason is in versions.py: 'Files that set refusal limits are hashed as declared inputs.' The worker file holds the per-input timeout and memory refusal paths, so hashing it is deliberate; the cost is that any worker-transport edit (the 5 s startup wait at parser_worker.py:111 included) moves filename_readings (c65e505e).

Plan for the next intentional filename version step, one commit: raise the startup wait, and narrow what the filename producer hashes to the refusal limits themselves (the declared timeout and memory values) instead of the whole worker file, so transport edits stop moving the identity. That needs the owner's recorded equivalence decision and a _REVIEWED_PRODUCER_VERSIONS entry. Nobody changes the hash before then.

**2026-11-10T17:41:12Z**

2026-11-10 17:41Z seen again: with load about 150 on 14 cores (release lanes, OCR, an engine release build, three sessions' tests), two house-naming bounded-backtracking tests timed out at their 8-second subprocess limit in the third release stack's lanes: test_structured_slots.py::test_long_malformed_amendment_identifier_does_not_backtrack_over_digit_partitions (shard 1) and test_filed_targets.py::test_failed_long_filing_shape_is_bounded (shard 4). Both files pass alone at load 30 (106 passed in 7.3 s) and the stack does not touch packages/house-naming. Shards 1 and 4 are being rerun. A wall-clock timeout is the wrong measure for 'does not backtrack'; counting regex steps or comparing against a short input would not depend on load.
