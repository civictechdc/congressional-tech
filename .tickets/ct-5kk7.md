---
id: ct-5kk7
status: open
deps: []
links: [ct-94hw]
created: 2026-11-04T20:47:30Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, correctness, release-blocker]
---
# Meetings lose their videos when a Congress.gov meeting record is first fetched with an unchanged update date

Nightly candidate ef4c1632 vs live e4538f00: meetings 102827, 102917, 103028, 103081, 103182, 103185, 103226, 337959 go from 2 videos to 0 (meetings.videos 9, recordings removed 8, recording_matches removed 16, meeting_coverage recording/caption rows). Their congress_gov_updated is unchanged; the record first fetched 2026-10-30 wins the tie as newest. Not yet known whether the new API bodies omit videos or the parser/model drops them. Evidence: .cache/archive-release/nightly/20261104T174328Z/causes/evidence/10-possible-defect-meeting-videos.json, .cache/archive-release/nightly/20261104T174328Z/causes/evidence/11-meeting-coverage.json.

## Acceptance Criteria

Read the lake meeting_records rows (old and new body) for the 8 meetings and state which side drops videos. If the API omits them, a newer body with the same updated stamp must not erase videos stated by an older body (or the release states why). Fixture for the tie case; rebuilt candidate keeps the videos or carries an explained cause.


## Notes

**2026-11-05T01:45:54Z**

Root cause and fix (branch meeting-videos-tie, commit ac9c8be0, off origin/main 3afcd141; not pushed).

Which side drops the videos: the Congress.gov API, not the parser. The base records are inline saved-record lines in receipts/congress/meetings/undated/assemble-20260930.jsonl.gz (copied from legacy pipeline-data / committee-explorer congress_meetings.jsonl.gz; no fetch time). The 2026-10-30 records are fetched API bodies (committee-meeting/<congress>/<chamber>/<event>?format=json, lake files ce349af3 and bea12059). For all 8 events the payloads are identical except that the new body has no videos key; updateDate is equal. 119569 is the mirror case (legacy absent, new present). The parser maps a missing key to absent and [] to empty. Congress.gov never emits an empty videos, jackets or subjects list (0 of 36,279 records), so omission is its only way to say "none".

Model defect: meeting-records-current.sql took every collection from one winner per (event, source), ordered updated DESC, retrieved_at DESC NULLS LAST. The fetched body beat the undated inline record, and its omission erased the videos.

Fix: within the winner's updated stamp, a collection the winner omits (absent) comes from the best-ranked record of that stamp that states it. A later stamp still replaces, and empty or unrecognized never fall back. Applies to all six collections. New materialized step meeting-records-ranked.sql picks row numbers; meeting-records-current.sql joins the collections back. first_value over a nested list fails on lake (Parquet field_id) inputs in the pinned engine, so the windows pick scalars only. model-relation-rows.json gains meeting_records_ranked = 24,305; the lifetimes relation count goes from 204 to 205.

Fixtures (test_phase2_model_entities.py): same-stamp tie in both rank orders (videos and jackets fall back independently); a later stamp that omits videos removes them; empty or unrecognized under the same stamp never fall back. The tie cases fail against origin/main's SQL.

Real data: the maintained meeting steps were run over all 42,551 lake meeting_records rows. Origin/main reproduces the candidate (8 events at 0 videos, 119569 at 2). The fix restores 2 videos to each of the 8 and changes no other event (18,140) in videos, jackets, sittings, committees, subjects, title, status or updated. Peak 1.97 GiB. Downstream recordings, recording_matches and meeting_coverage were not rebuilt.

Lanes: production-offline (full lane): exit 0 (11404 passed, 37 skipped; peak 1.96 GiB). native-loopback (full lane): exit 0 (10 passed, 0 skipped; peak 1.00 GiB).

Evidence: .cache/archive-release/investigations/ct-5kk7-meeting-videos/README.md.
