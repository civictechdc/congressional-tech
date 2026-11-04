---
id: ct-94hw
status: in_progress
deps: [ct-kb4w]
links: [ct-m56x, ct-30fp, ct-kb4w]
created: 2026-11-04T15:19:41Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [daily, nightly, custody, phase2]
---
# Daily reads unpinned bodies through a candidate-scoped R2 listing, checked before captures append

Nightly 20261104T143713Z stopped with RawCustodyRequired: 5 of 5000 readings candidates had no captured stored MD5/size. 85 unread bodies are in that state (5 Oct 31 meeting bodies, 80 Oct 15 bulk-uploaded documents/transcripts): they were uploaded by runs that wrote no receipt, and the later conditional PUT got 412 and recorded outcome=unchanged without pins. Captures appended before readings planned, so the refusal left 5000 appended-but-unread captures. Evidence: .cache/archive-release/investigations/nightly-unpinned-captures-20261104.md. Nightly launchd job unloaded until this lands.

## Design

All in daily.py (no hashed parser touched): before append, count the pending readings backlog and shrink the budget by it; HEAD every candidate body's recorded R2 key into a candidate-scoped listing (quoted ETag); refuse before append if an object is missing; plan readings in the planner's listing mode; report RawCustodyRequired as a status. Branch nightly-listing.

Owner decisions 2026-11-04: read the 85 bodies; SHA-256 verification at read time is sufficient custody. Provenance: the Oct 31 scheduler runs 7aab36630668 and acc7ca3dd55a were interrupted local runs; the Oct 15 bodies came from an owner-run bulk import.

## Acceptance Criteria

Planted wrong ETag/size and unquoted ETag refused; missing candidate fails closed; missing object refuses with no append; budget selects at most max_work_items minus backlog; nightly re-enabled and a run publishes.


## Notes

**2026-11-04T16:39:03Z**

Landed 61ec174b on main (pushed). production-offline full lane exit 0 on the committed code (11,368 passed; all files predate the lane start); touched files re-run 176 passed. Tests: listed-ETag read of unpinned capture, capture MD5 wins, planted wrong ETag refuses before append, absent candidate refuses before any append (fresh and pending), absent non-candidate no effect, planted wrong size refused at read, unquoted ETag fails closed, budget = max_work_items minus pending backlog, backlog past budget refuses before staging, HEAD retry/give-up. Manual nightly run 4 started 2026-11-04 ~11:45 to confirm a publish.

**2026-11-04T17:25:24Z**

Nightly run 5 (ebaa6c2a): daily passed listing custody and the TLS retry held (5 x 429, 1 x 500, 1 x 502, all retried once); daily returned backfill_required as designed. Backfill ran 660 s then failed writing backfill-report.json: readings result carries Path values (work_list, batch readings). Fixed in bcbc7c12 (paths serialized as text; other non-JSON still raises; test fails without the fix). Run 6 started on main bcbc7c12.

**2026-11-04T17:33:20Z**

Run 6 (origin/main ebaa6c2a; local fixes unpushed) published nothing: daily refused producer_unrecorded (appearance_records). Cause: run 5's backfill called produce_daily without the producer ledger and appended 14,972 appearance_records rows (snapshot 1297563386327530412 -> 741356244630763808, one append) with no record. The publish job exited 0 on that stop, so the launcher wrote status ok. Fixes 2b3f20ef: backfill spec pins the publisher's producer anchors and passes the ledger (a daily R2 backfill without them refuses at load); publish exits 2 whenever its daily ran and did not complete. Repair (owner-approved): wrote the missing record lake/producers/01a1a35c-5f95-7150-aeb0-30b20296cd34/741356244630763808.json (sha256 8f5acfdf..., 1145 B) exactly as daily._record_moved would have: job daily.py, commit ebaa6c2a, uv.lock digest adc74b4f..., base = anchored head + anchor pin. decided_at 2026-11-04T17:12:31Z is the backfill process start (watchdog report mtime minus elapsed), not the job's own clock, which was never written out; gate 5 does not check decided_at. Verified before writing: no record named the head, base record found, lineage is a single append. Script and appended parquet: .cache/archive-release/investigations/ct-94hw-producer-repair/. Pushed main.

**2026-11-04T17:43:28Z**

Run 7 (2b3f20ef): producer preflight passed (record repair held). Failed in the raw-custody scope job: scoped-captures export ordered by receipt_key alone, not unique (26,281 captures / 6,941 bodies; receipts with several candidate lines). Run 5 passed only because its candidates had one line per receipt. Fixed 89a8d2df: order by (receipt_key, receipt_line, capture_index); new test fails with the production error under the old ordering. Nothing appended (check runs before captures move). Run 8 started on 89a8d2df.

**2026-11-04T20:05:14Z**

Nightly run 8 (20261104T174328Z, main 3afcd141): daily completed and lake heads advanced with producer records. Publish refused at gate 1: 71 groups vs e4538f00 with no recorded cause (candidate ef4c1632...). Candidate, base and release-gate.json saved under .cache/archive-release/nightly/20261104T174328Z/candidate/. Witnesses -35,899/+35,915 investigated in candidate/witness-rekey.md: the same Congress.gov witnesses re-keyed after 18,123 committee-meeting API URLs first fetched 2026-10-30 entered the lake (new record_sha plus a real context_key where e4538f00 had sha256([null,null])). Content equal apart from 79 names, 68 positions, 69 organizations. Open for the owner: witness_key churns on every re-fetch, and the Explorer /witness route looks up by key. launchd left unloaded until a cause record lands. event 118300 committee_records still 0: nightly does not rebuild Explorer tables (ct-717p stays open).
