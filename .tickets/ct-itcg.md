---
id: ct-itcg
status: open
deps: []
links: [ct-v8y0, ct-5f3e, ct-kunv]
created: 2026-11-01T20:08:13Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [basin, lake, cutover, phase2]
---
# Commit publish_v21 D1-D4 inputs to Basin and bind live table pins

publish_v21 was built from local Parquet snapshots. The Basin tables still hold older data (ct-87uf recorded 24,304 meeting and 62,782 appearance records; v21 has 24,430 and 66,483), and publish-model.json pins no snapshots. Data model §8.1 requires a release to be reproducible from its input record at pinned table versions.

## Design

Commit the five verified inputs to the archive namespace through the checked-in native jobs. A hash-verified local copy is at .cache/archive-release/publish_v21/inputs (ignored by Git; machine-local). The source is the session scratchpad named in the cef-96wc 2026-11-01T17:43:18Z note. If a checked-in job lacks a needed capability, ct-9gmr supplies it; do not use scratch scripts. The lead performs the live commit.

## Acceptance Criteria

- captures 4,147,132; readings 1,349,139; filename_readings 1,311,075; meeting_records 24,430; appearance_records 66,483 rows read back from Basin, compared per table with the local inputs by key, not by count alone.
- publish-model.json has real snapshot pins and publish.json its receipt keys and refreshed model_spec digest.
- A rebuild from those pins reproduces release 448651e7 or every difference is explained.


## Notes

**2026-11-01T22:37:26Z**

2026-11-01, in progress and cause unproven: plan-d-jobs re-staged receipts at HEAD (mapping 30de9f61) and found v21 captures rows that disagree. After 7 of 35 batches, about 2.4M of 4.1M rows, 12,377 differ: senate/captions/2026-09-29 12,362 rows (raw record.outcome=error; HEAD failed, v21 stored), congress/meetings/undated 15 rows. Row counts and the backfill guard pass both, because the values are in-domain. Do not commit captures until this is explained.

**2026-11-01T23:33:23Z**

Root cause work by impl-d-jobs, 2026-11-01. Proven: none of fb408404, its parent, bc0a146c~1 or e31aeb42~1 produces v21's 'stored' on 4 sampled raw-failure lines; v21 captures are pyarrow-written, not native, and no transcript names the writer. Raw receipts support HEAD on at least 12,409 rows (lower bound; 3 receipts missing), for example record.outcome=error and http_error. About 2,270 saved-record rows that v21 marks failed match e31aeb42~1 (extrapolated from 3 of 5 receipts). Inferred: an unrecorded mapping ignored raw record.outcome. Recommendation: do not commit v21 captures; re-stage captures from receipts at the approved mapping.

**2026-11-02T00:36:42Z**

Owner decision 2026-11-01: commit the v21 inputs as they are, and rebuild captures in parallel under ct-kunv. This supersedes the earlier do-not-commit note and the main recommendation against it. The criterion that a rebuild reproduces 448651e7 no longer applies as a target, because that release has known defects; instead every difference is explained. Inputs are at .cache/archive-release/publish_v21/inputs, the only copy.

**2026-11-02T10:24:10Z**

Owner decision 2026-11-02: merge B/C/D first; Claude runs this commit afterwards from a checkout pinned at 6a36e54c (pre-merge code), through the checked-in native jobs, with per-key read-back.

**2026-11-02T12:28:28Z**

Round 1b 2026-11-02 (lead): Run inputs lost with /private/tmp are regenerated from the release's own published input record (release_input_custody.py collect; .cache/archive-release/r1b/inputs). Checked-in specs failed their own loaders after 2351caf4; fixed in impl-e2. basin-commit is running the commit.
