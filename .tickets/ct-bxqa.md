---
id: ct-bxqa
status: closed
deps: []
links: [ct-c6b0, ct-kunv]
created: 2026-11-02T04:01:45Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [captures, eligibility, phase2]
---
# Non-200 raw record.status rows map to stored and count as good fetches

review-d-jobs measured 1,807 rows with raw record.status 404, 202, 503, 429 or 403 that map to stored, complete, http_status NULL, then pass archive_url_state.py:45 good_lines. Include in the batched parser version move.

## Acceptance Criteria

Per-status fixtures, and those URLs are not good.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): plan-e1 raw read: 3,159 body entries state 404/202/429/503/403 under a status key the mapping never reads; 2,997 pass good_lines today (ticket's 1,807 is the record-level subset). Cause 72d03498 plus the mapping's 'no status with a body => stored' rule. Fix: one document rule in receipt_metadata.py (2xx except 202, non-empty body, per-item final state) used by captures, receipt_writer, archive_url_state and the scheduler. Reading status also admits 51,979 stated-200 rows (3,721 new bodies, mostly m3u8); decision: adopt, with HLS and other non-document media classified non-document. Implementing: impl-e1, branch r1b-e1.

**2026-11-02T13:54:36Z**

2026-11-02 (lead): impl-e1 r1b-e1 (4 commits): status is read from 6 owner shapes; origin 72d03498; 13 deep 404 rows stay a residual. Staged before/after on 40,881 of 40,883 lines (2 lines over 36 MB not staged: youtube/api :1, documents :50170): 0 violations, 7,379 stored to failed, 18 to retry_later, 0 stored non-documents, good fetches -232/+30,178. APPROVED_MAPPING is now 9bb28646. Under red/green review.

**2026-11-02T14:20:30Z**

2026-11-02 green-e1 (request changes): the rule checks out against raw: all 7,401 outcome changes supported (6,971 empty bodies, 405 404s with a body, 18 429/503, 5 envelopes, 1 403, 1 empty ZIP member); 32,895/32,895 filled statuses match the raw owner status; non-document rows among good URL lines 2,759 to 0. Good fetches -237/+30,236 (58 rows on 5 lines missed by the candidate set). The 83 MB line youtube/api/2026-09-29:1 (22,364 rows) exceeds the engine's line allowance and was never staged; it explains the +51,979 vs +30,178 gap, and the rebuild must admit it. Defects sent to impl-e1: MP2T 206 samples become documents (media rule keys on NULL legacy media_type); refuse_local_paths rejects ~.docx ZIP members and aborts the run; duplicated rules (archive_model.py:440, local path twice); compare_generations fails on v21's 37 columns; the guard accepts a stale 64-hex mapping_version.

**2026-11-02T15:34:13Z**

2026-11-02 impl-e1 r1b-e1 04e20965: all green-e1 and red-e1 items fixed; production-offline 10,849 passed. A 206 counts only when content_range covers the whole body (the 3 senate samples now fail); segments get role media by the registry .ts pattern; one absolute-path rule (member names never refused; the writer refuses before storing; per-item failure); one empty-body rule; compare_generations on shared columns (works on v21); the guard accepts only a current or registered-compatible mapping; url prefers record.final_url (34,658 v21 rows; 249 queued URLs leave the queue). Staged all 40,887 lines including the 83 MB line (max_batch_bytes >= 84 MB): 7,880 stored to failed, 18 retry_later, good fetches -232/+52,089; +2,389 m3u8 tracks; 5 empty tracks dropped. red-e1b is doing a light re-check before the first merge.

**2026-11-02T15:46:32Z**

2026-11-02 red-e1b: merge with one fix. The final-URL move makes locator-signals.sql test only url, so a Senate WAF block page (3460294b, 'Request not Accepted – Security Risk Detected', at senate.gov/…/waf.htm) becomes a real file and would be listed on 5 Armed Services transcripts and 1 release. Fix: evaluate requested_url and url, and recognize the WAF page. Held: 249 queue leavers (248 whole PDFs; S.3492 cut short by the server), no real document's link changed target, the 206 and segment rules, and -237.

**2026-11-02T16:18:58Z**

2026-11-02 (lead): r1b-e1 merged into integrate-round1 by fast-forward at d5574752 (8 commits): the document rule, the partial-206 rule, segments as media, final URL, the WAF page signal, mapping_version and original_path, writer path refusal. The WAF fix judges a redirect's role by both addresses and adds a senate_waf_block signal (3 v21 bodies). Merge order continues: e2 (+ e2-map), g, f, h, then u2, the targets deferral, r2-session and the basin import job.

**2026-11-03T22:53:34Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
