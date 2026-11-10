---
id: ct-dagf
status: open
deps: []
links: []
created: 2026-11-10T19:53:10Z
type: task
priority: 2
assignee: mikewolfd
---
# Release gate named corrections: review follow-ups

From the independent review of 5950bb11 (ct-4nax; verdict SHIP, no must-fix), to land after the 2026-11-10 release is live because any change under packages/ makes the nightly discard a built candidate: (1) add the two tests in .cache/archive-release/investigations/gate-corrections-20261110/review/gr_proposed_test.py.txt to test_release_gate.py (a working waiver must not hide a vanished key; a row with no file keeps its null in the candidate bodies); (2) release note wording at release_gate.py:869: say 'N corrections', since it counts entries and a key with two live files has two; (3) stale docstring at release_comparison.py:890-891 still lists lookup keys as outside the rule; (4) pre-existing: when urls has no lookup_key column or sources has no url column the comparison crashes in counted (release_comparison.py:313-319) before the link rule can report 'not checked': it still blocks, but with a traceback instead of a reason; (5) only corrections check that a ticket file exists, groups do not: decide whether groups should; (6) verdict writes named_corrections into the report it is given: return it instead; (7) run_lanes.py stamps each lane line before waiting, so its times are start times.

