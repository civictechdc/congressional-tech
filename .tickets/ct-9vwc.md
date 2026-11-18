---
id: ct-9vwc
status: open
deps: []
links: []
created: 2026-11-18T22:05:04Z
type: bug
priority: 1
assignee: mikewolfd
tags: [model, recordings]
---
# Match recordings to hearings by hearing date, not page publication date

Defect: recording matching (recording_matches, recordings.event_ids, meeting_coverage) uses the committee page publication date where it should use the hearing date. After newly captured committee pages, all six existing recordings that gained a hearing ID gained the wrong one (e.g. the July 18 Indo-Pacific video gained the June 7 Western Hemisphere hearing), and postponed hearing 117329 falsely went from no recording (unknown) to present. Legitimate change to keep: hearing 102893 rose from 1 to 18 clips.

RCA: /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/investigations/publish-stop-44399856473/codex-rca.md (examples in six-recordings.csv beside it).

Fix plan: match on hearing date; keep page publication date as its own field; reject an embed whose hearing identity (date, committee, title) contradicts the hearing it would attach to. Tests: plant the six wrong associations and the postponed-hearing case (must not match); 102893 must still match. Definition change: batch with PR 211 under one cause record.

Status: NOT STARTED beyond branch and this ticket (agy run stopped at session limit before any edit). Remaining: locate derivation in model/sql, change the rule, add tests, run definition-change.py --base origin/main, open PR.

Publish run 44399856473 is stopped at gate 1 with its candidate kept. Do not write a cause record until this fix and PR 211 merge together.

