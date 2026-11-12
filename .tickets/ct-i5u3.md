---
id: ct-i5u3
status: closed
deps: []
links: [ct-qxfc, ct-x00f]
created: 2026-11-10T13:26:44Z
type: task
priority: 2
assignee: mikewolfd
tags: [model, tests, memory]
---
# Model join lint under-counts and 38 steps still build an outer join on a large preserved relation

From ct-n5ec (2026-11-10). The whole-model lint in packages/viewer_publication/tests/test_phase1_model_repeat_cost.py lists steps whose outer join builds its hash table on a large preserved relation and pins them in OUTER_BUILD_TRACKED. Independent review: its NODE regex drops plan lines with nothing after the colon (106 'Left Join:', 40 'Cross Join:', 115 'Projection:'), so it reports 93 joins in 35 readers where a full parse finds 129 joins in 38; inner joins collapse through one-row joins (page-descriptions.sql:43 is missed); LeftSemi, LeftAnti and LeftMark joins (89 with a large left) are ignored; the allow-list equals the lint's own output, so it is exact only against itself; the row fixture lacks document_filename_facts and document_bill_decisions. The two recovery subquery flips in model/sql/document-recovery-normalized.sql (2ae32ba5) have no guard: reverting them passes every test. The largest offenders are recovery_candidates, meeting_detail_*, url_state_lines (about 4.1M rows), document_identities, document_metadata, component_meeting_links. Which of them is near the pool limit is unknown until a build logs pool_reserved_peak per step (the engine ticket).

## Acceptance Criteria

The lint parses every plan line and covers semi, anti and mark joins; its allow-list is checked against an independent count. The recovery flips have a guard that fails when reverted. The offending steps are ranked by measured pool_reserved_peak from a full build, and each one above an agreed share of the pool is rewritten small-side-first with a byte-identity proof, or recorded as accepted with its margin.


## Notes

**2026-11-10T15:47:02Z**

2026-11-10 root-cause analysis (.cache/archive-release/investigations/docspec-feedback-20261110/root-cause/, APPENDIX.md section 2.7; script rc_lint_count.py). The 35-or-38 question is settled as far as reading can settle it. Parsed in full, the lint's own rule gives 38 readers and 129 joins on the retained dump (sf-all-plans.json); the committed regex (test_phase1_model_repeat_cost.py:153) requires ': ' after the node name, drops 106 of 344 'Left Join:' lines and all 40 'Cross Join:' lines, and so reports 35 and 93. Third check from the physical plans of the same dump: 226 hash plus 117 nested-loop left joins, 343 against 344 logical. But the dropped lines are keyless left joins the optimizer makes from uncorrelated scalar subqueries (__scalar_sq_N), run as nested-loop joins over one-row aggregates; the lint's estimator rates a node by the largest scan beneath it and so calls them large. The three extra readers (filename_both_names, invariants, url_state_invariants_step) are probably harmless. So: the reviewer is right about the parse, the builder probably right about the risk, and neither number ranks danger. Recommendation: no more lint work. The replacement is ct-qxfc (step row counts reach the planner, so the planner picks the build side) plus per-join build memory from a real build; the allow-list and its estimator are deleted only after that engine is pinned and a full-size build is byte-identical.

**2026-11-11T14:33:14Z**

validated 2026-11-11, left open: the lint is unchanged (test_phase1_model_repeat_cost.py:196 NODE still requires ': ' after the node name, so bare 'Left Join:' lines are dropped). Per the 2026-11-10 root-cause note the replacement is ct-qxfc's row counts to the planner (X1b), which is parked and not in the pin candidate ae12bbd (X1a only, names in plans). Remains: X1b's measurement and decision, then per-join build memory from a real build, before the allow-list can go.

**2026-11-12T16:00:00Z**

Closed on `claude/ct-wave-2-pin2` with Pin 2 (`docspec-rs` `e3d9092a6393e654efe221d662a76daf8fd56ca5`).
1. Lint & regression guards (`packages/viewer_publication/tests/test_phase1_model_repeat_cost.py`):
   - Fixed `NODE` regex to parse bare-colon plan lines (`Left Join:`, `Cross Join:`, `Projection:`) with zero dropped operator lines (`len(parsed_kinds) == len(operator_lines)` across all 351 model readers, accounting only for literal `\n` continuations inside `Utf8("\n")`).
   - Excluded keyless uncorrelated scalar-subquery `Left Join:`s (`__scalar_sq_`, executed as `NestedLoopJoinExec`) in `large_outer_builds` (`OUTER_BUILD_TRACKED`: 30 readers / `75` keyed outer joins), extended join coverage to `LeftSemi`, `LeftAnti`, and `LeftMark` joins (`SEMI_ANTI_MARK_BUILD_TRACKED`: 16 readers / `83` joins), and cross-checked both allow-lists against independent line-level logical join counts (`1,298` total) and physical `HashJoinExec` / `NestedLoopJoinExec` plans.
   - Added explicit regression guards for both `model/sql/document-recovery-normalized.sql` subquery flips (`2ae32ba5`) that fail immediately if either flip is reverted.
2. Full-build `pool_reserved_peak` ranking across ALL stages (`step`, `query`, and `output` events in `.cache/archive-release/release-20261112-pin2/benchmarks/pin2-full-build-steps.jsonl`, `12 GiB` pool = `12,288 MiB`, 46/46 Parquet files byte-identical to `ae12bbd`; rewrite threshold set at `50%` of pool = `6,144 MiB` for join steps):
   - Whole-model peak across all 829 events is **`member_votes.parquet` (`output` event: `10,178.6 MiB` = `82.83%` of pool, `+7,134.4 MiB` export sort/write delta, `17.17%` headroom)**, followed by `capture_evidence.parquet` (`9,363.2 MiB` = `76.20%`), `capture_sources.parquet` (`8,088.5 MiB` = `65.82%`), and `source_filename_readings.parquet` (`6,848.8 MiB` = `55.74%`). Peak across `step`/query events is `recording_matches_export` (`6,062.5 MiB` = `49.34%` of pool).
   - **All 16 `SEMI_ANTI_MARK_BUILD_TRACKED` readers sit below `42%` of the `12 GiB` pool** (`> 58%` pool headroom; step delta `<= 16.55%` of pool) and are recorded as accepted with explicit margins:
     1. `source_annotation_facts`: `5,104.9 MiB` (`41.54%` of pool, `+2,033.4 MiB` = `16.55%` step delta, `11,848,797`-row `LeftSemi` build on `source_filename_readings`; `58.46%` headroom).
     2. `link_inputs`: `4,856.2 MiB` (`39.52%`, `+1,794.3 MiB` = `14.60%` delta, max `192,191`-row `LeftAnti` build).
     3. `url_state_queue_links`: `4,576.2 MiB` (`37.24%`, `+1,504.3 MiB` = `12.24%` delta, `361,991`-row `LeftAnti` build).
     4. Remaining 13 `SEMI_ANTI_MARK_BUILD_TRACKED` readers: `duplicate_component_edges` (`30.35%`), `url_state_invariants_step` (`29.97%`), `document_witness_url_matches` (`29.50%`), `pinned_readings` (`29.38%`), `model_invariants` (`29.20%`), `document_witness_raw_matches` (`28.10%`), `profile_completeness` (`26.51%`), `entity_profile_completeness` (`26.01%`), `retired_links_export` (`25.48%`), `relationship_invariants` (`25.34%`), `filename_conflicts` (`25.22%`), `explorer_invariants` (`24.74%`), `unresolved_meeting_document_urls` (`1.76%`).
   - **All 30 `OUTER_BUILD_TRACKED` readers sit below `38%` of the `12 GiB` pool** (`> 62%` pool headroom; step delta `< 13%` of pool) and are accepted with wide safety margins:
     - Top 7: `source_addresses` (`4,647.8 MiB` = `37.82%`, `+1,585.9 MiB` delta), `source_filename_readings` (`4,622.0 MiB` = `37.61%`, `+1,550.4 MiB` delta), `document_metadata` (`4,469.0 MiB` = `36.37%`, `+1,397.9 MiB` delta), `document_identities` (`4,274.3 MiB` = `34.78%`, `+1,202.8 MiB` delta), `source_annotations` (`4,223.2 MiB` = `34.37%`, `+1,151.7 MiB` delta), `url_state_lines` (`4,210.5 MiB` = `34.27%`, `+1,138.6 MiB` delta), `source_members.parquet` (`4,206.5 MiB` = `34.23%`, `+1,229.1 MiB` delta). `recovery_candidates` used only `+14.2 MiB` delta (`24.87%` peak; `14,416` post-filter build rows). Both allow-lists retire under Stage 2 managed jobs (`ct-x00f`).
