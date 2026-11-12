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
   - Fixed `NODE` regex to parse bare-colon plan lines (`Left Join:`, `Cross Join:`, `Projection:`) with zero dropped lines, extended join coverage to `LeftSemi`, `LeftAnti`, and `LeftMark` joins while explicitly distinguishing uncorrelated scalar-subquery (`__scalar_sq_`) nested-loop joins, and verified the parsed tree against an independent line-level join count.
   - Added explicit regression guards for both `model/sql/document-recovery-normalized.sql` subquery flips (`2ae32ba5`) that fail immediately if either flip is reverted.
2. Full-build `pool_reserved_peak` ranking across all 33 `OUTER_BUILD_TRACKED` readers (`release-20261112-pin2/candidate-build/steps.jsonl`, `12 GiB` pool = `12,288 MiB`, 46/46 Parquet files byte-identical to `ae12bbd`):
   - Whole-model peak `pool_reserved_peak` is `recording_matches_export` (`6,062.5 MiB` = `49.34%` of pool, `+2,993.2 MiB` step delta).
   - Every single one of the 33 `OUTER_BUILD_TRACKED` readers sits **below `38%` of the `12 GiB` pool** (`> 62%` pool headroom; step delta `< 13%` of pool), so all 33 are accepted with wide safety margins and zero SQL rewrites needed:
     - Top 7 by step delta / pool peak: `source_addresses` (`4,647.8 MiB` = `37.82%`, `+1,585.9 MiB` delta, `2,321,241` build rows), `source_filename_readings` (`4,622.0 MiB` = `37.61%`, `+1,550.4 MiB` delta, `2,122,699` rows), `document_metadata` (`4,469.0 MiB` = `36.37%`, `+1,397.9 MiB` delta, `2,122,699` rows), `source_members.parquet` (`4,206.5 MiB` = `34.23%`, `+1,229.1 MiB` delta, `551,015` rows), `document_identities` (`4,274.3 MiB` = `34.78%`, `+1,202.8 MiB` delta), `source_annotations` (`4,223.2 MiB` = `34.37%`, `+1,151.7 MiB` delta), `url_state_lines` (`4,210.5 MiB` = `34.27%`, `+1,138.6 MiB` delta, `1,631,385` rows).
     - `recovery_candidates` (ranked #1 by empty-plan static row estimation) used only `+14.2 MiB` delta (`0.12%` of pool; `3,056.5 MiB` = `24.87%` peak; `14,416` post-filter build rows), and the 3 bare-colon scalar-subquery readers (`url_state_invariants_step`: `29.97%`, `invariants`: `29.09%`, `filename_both_names`: `1.11%`) confirmed benign.
