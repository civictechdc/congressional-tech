---
id: ct-i5u3
status: open
deps: []
links: []
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

