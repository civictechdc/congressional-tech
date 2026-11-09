---
id: ct-cpd8
status: open
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
