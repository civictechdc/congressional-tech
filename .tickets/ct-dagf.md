---
id: ct-dagf
status: closed
deps: []
links: []
created: 2026-11-10T19:53:10Z
type: task
priority: 2
assignee: mikewolfd
---
# Release gate named corrections: review follow-ups

From the independent review of 5950bb11 (ct-4nax; verdict SHIP, no must-fix), to land after the 2026-11-10 release is live because any change under packages/ makes the nightly discard a built candidate: (1) add the two tests in .cache/archive-release/investigations/gate-corrections-20261110/review/gr_proposed_test.py.txt to test_release_gate.py (a working waiver must not hide a vanished key; a row with no file keeps its null in the candidate bodies); (2) release note wording at release_gate.py:869: say 'N corrections', since it counts entries and a key with two live files has two; (3) stale docstring at release_comparison.py:890-891 still lists lookup keys as outside the rule; (4) pre-existing: when urls has no lookup_key column or sources has no url column the comparison crashes in counted (release_comparison.py:313-319) before the link rule can report 'not checked': it still blocks, but with a traceback instead of a reason; (5) only corrections check that a ticket file exists, groups do not: decide whether groups should; (6) verdict writes named_corrections into the report it is given: return it instead; (7) run_lanes.py stamps each lane line before waiting, so its times are start times.


## Notes

**2026-11-11T14:35:33Z**

validated 2026-11-11, left open: none of the seven items has landed (git log --grep ct-dagf finds only the filing commit 08030731). Spot checks on origin/main: the reviewer's two proposed tests are not in test_release_gate.py; release_comparison.py:1145 still lists lookup keys among what the link rule cannot see.

**2026-11-12T03:11:00Z**

Resolved all seven review follow-up items via Red -> Green TDD:
1. Added `test_a_waiver_in_force_never_quiets_a_vanished_key` and `test_a_key_that_also_reaches_a_row_with_no_saved_file_cannot_be_named` from `gr_proposed_test.py.txt` to `packages/viewer_publication/tests/test_release_gate.py`.
2. Updated `render_notes` (`release_gate.py`) to say `{len(corrections)} corrections (keys and addresses that now answer another file on purpose), each named in the reviewed cause record with both files (ct-4nax):` (`test_render_notes_calls_corrected_entries_corrections`).
3. Updated `link_rule` docstring (`release_comparison.py`) to note `unless a reviewed correction names it` and remove `lookup keys` from what the rule cannot see (`keys outside links, lookups and addresses (event IDs, witness keys, bill IDs)`).
4. Guarded missing `lookup_key`, `url`, and `member_path` columns in `documents`, `urls`, `sources`, and `account` (`release_comparison.py`) so `compare()` emits unexplained missing-column flags and reaches `link_rule`'s fail-closed `unchecked` reason instead of crashing with `duckdb.BinderException` (`test_compare_with_missing_address_columns_reports_unchecked_without_crashing`).
5. Moved the `.tickets/<id>.md` existence check into `_tickets()` (`release_gate.py`) so `groups` entries enforce ticket file existence just like `corrections` (verified 0 missing ticket files across all 7 historical `model/jobs/release-causes/*.json`; tested in `test_load_causes_refuses_a_group_entry_whose_ticket_has_no_file`).
6. Changed `verdict(report, causes)` (`release_gate.py`) to return `(reasons, named_corrections)` without mutating `report`, updating callers in `require_release_gates` and `test_bill_identity_decisions.py` (`test_verdict_returns_named_corrections_without_mutating_report`).
7. Promoted `run_lanes.py` to tracked `scripts/run_lanes.py` fixing the f-string evaluation order (`code = process.wait()` before `stamp()`), closing parent log file descriptors after `Popen`, deriving `default_lock_path` via `git rev-parse --git-common-dir`, and testing ordering in `scripts/tests/test_run_lanes.py`.
