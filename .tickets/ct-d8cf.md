---
id: ct-d8cf
status: open
deps: [ct-tw3r]
links: [ct-jo8n, ct-xu1o, ct-pgxn, ct-a3le, ct-0bce, ct-qkvr, ct-4nyy, ct-5yof, ct-ur7v, ct-dzyf, ct-a1aa, ct-8ax6, ct-n6lj, ct-r60e, ct-x0nk]
created: 2026-10-24T18:15:54Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-98sm
---
# WS8: news_lake on the DocSpec backend only

Owner decision 2: keep the DocSpec backend, port its crash, fence and merge tests, fix the two reproduced bugs and delete the PyIceberg oracle.

First move: parametrize the conftest `lake` fixture over both backends (`tests/conftest.py:147-150`) and run the Python-owner suites against `DocSpecLake`: `test_releases.py`, `test_coordinator_replay.py`, `test_recovery.py` and `test_partitions_and_bridges.py`. Expected values come from the contract, not from the Iceberg run.

Fixes: remove the automatic `compact_lifecycle` on commit (bug 1); revert ct-xu1o's time keys to `['id']` and delete the `_known_ids`/`_known_upsert_records` caches (bug 2); re-check the fencing epoch on every dataset commit; always load captures for exported versions.

Engine-first changes to the plan: export rights (C5) use the engine's policy as the single authority - expiry as a native predicate, not an id list - and the duplicate Python policy goes after a differential test (reverses the plan's "Python export_release stays the authority"; ct-4nyy, ct-5yof). Replace the Python view oracle (`analysis/views.py`) with direct contract assertions unless the owner keeps it test-only (plan open question 6; ct-ur7v). Use the engine's `/changes` for the rollback delta (ct-dzyf). Delete the app's table compaction (`docspec/compaction.py`) in favor of engine tail coalescing; an engine gap becomes an ss-* ticket.

## Acceptance Criteria

- Bug 1 reproduced: an old release stays readable after lifecycle compaction.
- Bug 2 reproduced: an existing append id is refused from a fresh process, after fixing the order-dependent test at `test_docspec_backend.py:1461-1468`.
- A lease stolen mid-publish is refused.
- A C5 subset read does not export expired text; the engine policy matches the old Python output in a differential test that includes `retain_until == now`.
- The cost of `['id']` lookups with compaction on is measured (ct-pgxn).
- Self-referential tests are deleted or fixed: the static receipt (`:2070-2100`), the test-local `_ArrowHttpStream` (`:738-753`); the schema is pinned by digest against git.
- R-check 1.

