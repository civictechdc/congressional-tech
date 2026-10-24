---
id: ct-q2ht
status: open
deps: []
links: [ct-czsd, ct-2ukk, ct-nc7l]
created: 2026-10-24T18:15:53Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-98sm
---
# Step 0: measure a full rebuild from raw

First move: fix the two harness problems found by reading (`scripts/measure/benchmark_core_rebuild.py:30` puts the repo-root `tests/` on `sys.path`, but the oracle moved to `packages/congress_api/tests/`; the documented `-m scripts.benchmark_core_rebuild` command is stale). Then run the existing oracle (`packages/congress_api/tests/historical_raw_catalog.py` plus `historical_catalog_lineage.py`) through the existing harness against a read-only, raw-only mirror. Do not write a new harness.

Under the engine-first rule, the full rebuild is the correctness oracle, the recovery tool and the cost baseline for WS7. It no longer decides whether a Python incremental layer is kept. Runs A and B1 set the baseline that WS7's engine-native incremental update must beat by a clear margin; otherwise the daily update is the rebuild.

Owner action: a bucket-scoped, read-only R2 token for these runs. The run of record is a `workflow_dispatch` job on `ubuntu-24.04`; local runs are for profiling only.

## Acceptance Criteria

- Inputs are pinned: `indexes/captures.parquet` (sha256 `db033173…`, 3,909,134 rows), `indexes/download-state.parquet` (sha256 `79b0473c…`), 2,289 receipts, and seed files matching reference A's `seed_digest`. The mirror holds raw inputs only: no `indexes/catalog.json` and no earlier catalog tables.
- Run A replays every `receipts/` line through `apply`/`add_index` into capture and state tables, compares all columns as row multisets with the pinned tables and the native raw selection, and is timed.
- Run B1 (`PYTEST_CURRENT_TEST` unset) is the timing of record. B2 (`PYTEST_CURRENT_TEST=1`) is compared with B1 using `--compare-only`; output and time differences go to WS1.
- Comparison C classifies every field where B1 differs from references A and B: (i) rule change, (ii) incremental-engine error, (iii) a fact only earlier derived tables hold. Any class (iii) difference blocks WS7's deletions until the owner answers open question 8.
- The hosted report records `nproc`, `free -g`, `df -h`, elapsed and per-stage time, peak RSS and scratch disk. The rebuild fits the 360-minute hosted job and runner memory; if not, one `py-spy` profile (B3) names the bottleneck and it is fixed in the rebuild path.
- R-check 1 passes before and after; nothing is written to R2.


## Notes

**2026-10-24T18:47:53Z**

Efficiency pass: also log today's raw-index cost per save (leaves touched, rows rewritten, datasets created) as the baseline for ct-w5fm. Owner action: a bucket-scoped, read-only R2 token for the hosted runs.
