---
id: ct-pz32
status: in_progress
deps: []
links: []
created: 2026-11-17T08:49:41Z
type: task
priority: 1
assignee: mikewolfd
tags: [hosted, mcp, ci, publish]
---
# Hosted MCP follows the live archive pointer; nightly chain runs unattended

Owner 2026-11-17: everything runs automatically from now on. After ct-b1jj the hosted nightly is capture (schedule) -> publish (workflow_run), but each release still needed a hand edit of PUBLICATION in apps/explorer_mcp/cloudflare/wrangler.jsonc plus a wrangler deploy (d1b8a0b5, 72b62edb), so the hosted MCP would fall one release behind every night. The workflow_run trigger itself had never fired: all five hosted publish runs were workflow_dispatch.

## Acceptance Criteria

The Worker resolves the immutable manifest from the moving pointer itself (each container still pinned to one immutable release, named after it); no per-release commit or deploy. One capture-triggered (workflow_run) publish finishes green, and the hosted MCP /ready names the pointer's release afterwards without a deploy. The archive workflow fails visibly when the hosted MCP does not follow.


## Notes

**2026-11-17T09:40:00Z**

Done and verified:
- Hosted MCP follows the pointer (33ac5fc4; Worker version f67e0bec, max_instances 4). `GET /` and `/ready` name 6ac86c21b373 with no release in wrangler.jsonc; smoke.py passes; a cold start through the new Worker took 53 s. The publish job's last step compares hosted `/ready` with the pointer.
- A cause record whose candidate is live no longer refuses later nights (18ebf957).
- The workflow_run trigger fires: capture 44049858500 (workflow_dispatch, green, 16m51s) started publish 44052307169 on 18ebf957 with no dispatch.

Not met: that publish built candidate c998ffa0766f (1,307 s, 10.08 GiB peak) and stopped at gate 1 with 42 groups. Evidence: `.cache/archive-release/hosted-runs/44052307169/`. Measured:
- The model definition is identical to the live build's (`profile_sha256` 5cd6fc7850d2 in both completed-model.json files); only lake snapshots differ, so every difference comes from the night's 1,173 new receipts. Link rule clean (0 missing, 0 dangling).
- The automatic proof (ct-ud0b) covers additions only and at most 250 documents. This one capture added 478 documents and changed existing rows: 1,097 titles, 287 committee_keys, 1,934 source link texts, url_state attempts, 81 meeting-coverage counts.
- All 42 refused group ids are in the last accepted record (4b9a7bd126cc-6ac86c21b373); 39 are in the 2026-11-13 capture-night record. All 13 releases since 2026-11-03 carried a hand-written record: no capture night has ever published unattended.

So the chain runs by itself up to gate 1 and stops there every capture night. What may pass gate 1 without a person is the owner's decision (asked 2026-11-17).

**2026-11-17T11:05:00Z**

Owner decision 2026-11-17 (asked with the measurements above): data-only nights self-approve. A night built from the live release's own definition and pinned inputs, whose receipt set only grew, publishes without a record inside tripwires; any code, parser, pin or decision change still stops.

Built and reviewed twice by independent Opus reviewers (`.cache/archive-release/reviews/data-only-night-20261117/REVIEW.md`, `round2/REVIEW2.md`); every blocking finding was fixed and tested:
- b1d4d3fa `viewer_publication/data_only_night.py`. Decides only a night the traced proof cannot read (`release_gate.untraceable_groups`), so it never overrides a check that ran and refused. Compares profile, entity digests, decision-record ETags and `unprofiled_inputs` (all producer versions including captures, committed job pins), which `run_publish` now writes on the input record. Explains only capture-night shapes; a removal, a demoted link, a defect, a flag or a whole file waits for a person. Caps: 5,000 rows or 2% per group, 10,000 per file, 5 removed rows (0.25% for the queue), 5% column loss from Parquet footers. Real gate reports are fixtures: the 2026-11-17 night passes all 42 groups, the 2026-11-16 html_metadata wipe refuses on group checks alone.
- 473423a8 the fetch queue is exempt from the column tripwire (first real run lost 5.8% of url_state.linked_from, which is fetched addresses leaving the queue).
- c34bd84f bootstrap record 6ac86c21b373 -> 95f4e73e859d: the live input record predates `unprofiled_inputs`, so one recorded release was needed. Written by `.cache/archive-release/investigations/data-only-night-20261117/bootstrap_record.py` only after nine checks passed on refused run 44065807228.

Known limits, accepted: wrong but non-null content at ordinary volume; columns of 50 or fewer values; losses that add up across nights; a lake table rewritten at an unchanged version; no per-document link caps on this path. First Sunday (weekly pipeline-data refresh) may exceed the caps and stop for a record; tune from that report.

CI hardening the same day (99d4bfcc..ba607808): pushes to main are validated, `ci-alerts.yml` opens one `ci-failure` issue per failing unattended workflow and a stale-nightly alarm, every job has a timeout and a pinned runner, Dependabot proposes action bumps weekly.

**2026-11-17T15:10:00Z**

First schedule-triggered night (capture 44080162359 at 12:07Z, publish 44087092120). It exposed three faults, all fixed the same day, and one real stop:
- attempt 1: R2 read timeout writing a producer record after a long engine step. f051364a: every archive job's client evicts its pooled sockets before a call that follows 120 s of silence (`client.evict_idle_connections`), replacing the one close() after the model build.
- attempt 2: gate 5 refused the daily append made on top of a reviewed capture-stage append (ct-z4w5 ran `captures_ingest.py` against production at about 10:20Z). 6c0e5c89: a daily chain may end on a snapshot another registered producer wrote; reviewed against the real records (`.cache/archive-release/reviews/gate5-chain-20261117/REVIEW.md`).
- attempt 3: gate 1 stopped, correctly, on one House Transportation event page captured again at the same address with a different latest-news sidebar (its link now opens the newer capture), and on the night's size: 1,775 receipts, about 1.6 times the two nights the caps were measured on. Record 95f4e73e859d -> 2ec7ae83a852 names the correction and each exceeded tripwire (9728be78).
- The tripwires now scale with the night's new receipts (5 rows a receipt per group, 15 per file, at most 2,500 receipts a night, 2% of a file), verified removals outside the document tables are capped at 0.25%, and every refusal is reported together. All three real gate reports are fixtures; the third is stopped only by the link rule and two single unverified removals.

Open, for the owner (ct-hs34 has the CI side): a page captured again at the same address changes its link key whenever its sidebar changes, and each one needs a named correction today. A standing rule could prove these from receipts (same address, HTTP 200, receipt new to the release, title unchanged). Single unverified entity removals (a person key gone ambiguous, a recording match replaced) also stop a night.

**2026-11-17T15:20:00Z**

Release 2ec7ae83a852 went live at 15:08Z from the first schedule-triggered night (run 44087092120, fourth attempt, hand-recorded). No night has yet published without a signed record.

A blind review (`.cache/archive-release/reviews/greybeard-ci-20261117/REVIEW.md`) found the effort was fitting the gate to the night being judged and running production on unvalidated commits. Owner decisions the same hour:
- a page captured again at its own address under an unchanged title moves its links without a person, proven from the raw receipt (`data_only_night.recaptured_pages`; replayed on the real night: all three findings proven, a receipt already live refuses);
- an unverified removal keeps stopping the night;
- capture, publish, backfill and maintenance check out the newest commit of main whose push validation passed, and changes reach main through pull requests;
- a pull request now says whether it changes the model definition (`.github/scripts/definition-change.py`), which is the merge-time signal for a code-caused stop. A data-caused stop cannot be rehearsed before the night's data exists.

Still open with the owner: a night after a stopped night carries two nights of receipts and exceeds `NIGHT_RECEIPTS`, so one stop forces a second signed night. Also found: the fetch queue held a case variant of an address already saved (`EventSingle.aspx` beside `eventsingle.aspx`), so the capture fetched the same page again; that is what produced tonight's recapture.
