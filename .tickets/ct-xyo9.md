---
id: ct-xyo9
status: open
deps: []
links: [ct-syp1, ct-wscb]
created: 2026-11-10T08:21:50Z
type: task
priority: 2
assignee: mikewolfd
tags: [gate, release]
---
# Release gate: leftovers from the second review of the gate rules

Second-pass review of claude/ct-gate-rules (31d53712), 2026-11-10: push as is, no blocker; these remain. Report: .cache/archive-release/investigations/gate-rules-20261110/review/REVIEW.md, 'Second pass'. (1) ct-syp1: two NEW cache files swapped between channels still verify; the cited-file check accepts any newly captured body (citing 52 unrelated new bodies passed), so it should require a body of the video-records family for that channel; nothing bounds how many citation-only rows change in one night; with automatic causes off and no record, made-up hashes pass. (2) ct-wscb: an address re-pointed to the sibling half of a correct split passes and no group moves. (3) ct-gc99: the cap of 250 counts documents only (one document with 5,000 addresses passed); cap keys and addresses per document or in total. (4) A candidate key that is both published and retired is never checked (a two-fault plant passed). (5) Three docstrings overclaim: swaps, 'a reviewed publish has this check', and captures 'the candidate does not control' (they are the candidate build's own pinned input; raw is not read). (6) No test covers the job-level retry wiring for receipt reads.

## Acceptance Criteria

Each numbered item is fixed with a failing-first test from the reviewer's plant, or declined with evidence recorded here; the docstrings state only what the code does.

