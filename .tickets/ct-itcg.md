---
id: ct-itcg
status: closed
deps: []
links: [ct-v8y0, ct-5f3e, ct-kunv, ct-m104, ct-8cno]
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

**2026-11-02T12:36:53Z**

Round 1b 2026-11-02 (lead): basin-commit: no checked-in job could commit the parquet files as they are (captures_ingest accepts only current-mapping stages). Added archive_import_job and generalized verify_generations on branch basin-commit (3 commits plus a test). Local dry run passed for all 5 tables (engine EXCEPT ALL and a separate Arrow comparison). No archive.* tables exist in Basin yet. Lead direction: commit into the canonical archive.<name> tables the specs reference, not release-named tables; v21 is the first snapshot and ct-kunv's rebuild the next.

**2026-11-02T12:39:55Z**

Retargeted to canonical archive.<name> tables 2026-11-02; nothing had been written under the release-named tables. Provenance: import-report.json (the commit record) and the append writer definition. publish-model.json table uuids are placeholders; the real ones get pinned from the commit.

**2026-11-02T13:14:38Z**

2026-11-02 (lead): the live write failed with no data written. R2 refused the 133 MB captures data file upload ('InvalidPart: All non-trailing parts must have the same length'). Engine cause: Iceberg FileIO data writes through OpenDalStorageFactory::S3 use no fixed multipart chunk; only upload_file pins 8 MiB (docspec-rs src/storage/remote/objects.rs around line 419). Left in Basin: namespace archive (generation 65356e21) and an empty archive.captures (uuid 01a19c60-7769-73c1-ab9a-b13a9a2857f1, no snapshot); the other 4 tables were not created. The job now resumes into an empty table (3e30b977). The fix is going into the engine release build with ct-deg8's two fixes; after the re-pin, the same command finishes. This affects every remote lake write, the daily job included.

**2026-11-02T15:32:20Z**

2026-11-02 basin-commit: DONE on R2. The five publish_v21 inputs are the first snapshot of the canonical archive.* tables (namespace ct-archive-v2/archive), engine 5a3121c, branch basin-commit 3e30b977 (archive_import_job). Snapshots: captures 1828363953761029924 (4,147,132 rows), readings 417472717314838744 (1,349,139), filename_readings 2975324804189756762 (1,311,075), meeting_records 6095611825010586178 (24,430), appearance_records 2778391476088817064 (66,483); uuids and metadata in .cache/rounds/r1b/basin/pins.json. Read-back: engine EXCEPT ALL both directions, 0 differences; independent Arrow sort-by-key, every column equal. receipt_keys: 2,292 (digest 8b4d786f, equal to the live release's list). Provenance (cef-96wc, unrecorded pyarrow writer, about 51k known-bad captures rows) in work-live/import-report.json and the writer definition. Remaining: commit these pins as 448651e7's reproducibility record in the release branch (the fixed release pins the rebuilt tables), then close. ss-ezin closed upstream.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
