---
id: ct-9vwc
status: in_progress
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

Status: Fixed on branch `recording-match-hearing-date` (PR 212), ready for review and batched merge with PR 211.

Publish run 44399856473 is stopped at gate 1 with its candidate kept. Do not write a cause record until this fix and PR 211 merge together.


## Notes

**2026-11-18T23:09:06Z**

Implemented on `recording-match-hearing-date` (PR 212):
- `model/sql/house-page-meeting-links.sql`: separated `page_date` (`min(try_cast(pf.content_date AS DATE))`) from `hearing_date` (`Hearing Date:` label in `text_head`, else proceeding `text_head` dates, else URL dates); matched and windowed `single_page_on_date` on `hearing_date`; excluded `not_held` meetings; projected `(page_body, event_id, hearing_date, page_date)`.
- `packages/viewer_publication/src/viewer_publication/archive_model.py`: extended `known_meetings` with `meeting_date`, `not_held`, `committees`, and `subject_keys`.
- `model/sql/entity-recording-matches.sql`: rejected `committee_page` embeds on `not_held` meetings and embeds whose own hearing identity contradicts the target meeting (kind, pre-hearing `published_at < meeting_date - 30 days`, stated video title date, stated held event ID, channel parent or full-vs-subcommittee level, or explicit topic title).
- `packages/viewer_publication/tests/test_explorer_native_tables.py`: added planted tests `test_house_page_links_use_hearing_date_and_reject_six_wrong_associations` and `test_committee_page_rejects_embeds_contradicting_hearing_identity` covering all 6 wrong associations (`4rSy_EReGYg`, `73UihZi8neM`, `_lyoHuKNhU4`, `aFfFblwBffg`, `ky1SY6BoL74`, `qeiE8Y79bHw`), postponed `117329`, and legitimate `102893` (18 clips). Verified both fail on `origin/main` (`2 failed, 38 passed`) and pass after the fix (`40 passed`), alongside `215 passed` in 11 model SQL structural/job suites and `53 passed` in `test_phase2_model_entities.py`.
- `definition-change.py --base origin/main`: `3 definition files and 0 job pins differ from the base` (`model/sql/entity-recording-matches.sql`, `model/sql/house-page-meeting-links.sql`, `packages/viewer_publication/src/viewer_publication/archive_model.py`). Batch with PR 211 under one cause record.

**2026-11-21**

Rebased onto `origin/main` (`53787ec9`, integrating `ct-414r`, `ct-6v77`, and Iceberg field-id normalization `337c6ed4`):
- `model/sql/house-page-meeting-links.sql`: kept all `ct-414r` protections (`link_rule`, `match_note`, `direct_stated_conflict`, `outbound_event_ids`, `single_page_on_date` via `page_key`, roundtable separation, suffix stripping) alongside `ct-9vwc`'s `hearing_date` vs `page_date` separation (`outbound_same_date_event_ids` and `single_page_on_date` use `hearing_date`), `not_held` exclusion, and `(page_body, event_id, link_rule, match_note, hearing_date, page_date)` projection.
- `packages/viewer_publication/src/viewer_publication/archive_model.py` & `model/sql/entity-recording-matches.sql`: kept `origin/main`'s thin `entity-recording-matches.sql` (0 repeated CTEs); extended `known_meetings_sql()` with `meeting_date`, `not_held`, and `committees`; integrated `ct-9vwc` embed-contradiction filters (`not_held`, pre-hearing `published_at < meeting_date - 30 days`, video title date, held stated-event conflict, channel parent/level mismatch, explicit topic conflict) with `ct-414r` filters inside materialized `recording_match_prep_steps()` (`recording_topic_stopwords`, `recording_page_video_facts`, `recording_page_video_stated_overlaps`, `recording_page_meeting_committees`, `recording_page_match_rows`).
- `packages/viewer_publication/tests/test_explorer_native_tables.py`: preserved all `origin/main` tests (`ct-414r`, frozen DAG, Iceberg field-id regression) and updated both `ct-9vwc` planted tests to the materialized prep-step schema.
