---
id: ct-aapl
status: closed
deps: []
links: [ct-v967, cefr-xjsp, cef-vai0, ct-30fp, ct-v51p, ct-adtz, ct-9wl3, ct-yci9, ct-5esu, ct-rie2]
created: 2026-11-01T02:34:11Z
type: task
priority: 1
assignee: mikewolfd
tags: [url-normalization, recovery, scheduler, wayback, acceptance]
---
# Implement and verify URL normalization, Wayback CDX pagination/alias recovery, scheduler address repair, and PDF bill corroboration (docs/plans/url-normalization.md)

End-to-end implementation and Section 6 empirical verification of docs/plans/url-normalization.md across Wayback CDX pagination/alias admission (Work Item 1), url-rules.json wrapper rules and SQL/Python URL identity parity (Work Item 2), capture_scheduler.py canonical fetch-address selection and post-capture state suppression (Work Item 3), fail-closed PDF bill heading corroboration in acceptance.py (Work Item 4), and narrow malformed URL repairs in url_normalization.py and pipeline.py (Work Item 5).

## Acceptance Criteria

All 6 work items of docs/plans/url-normalization.md implemented, verified across 3 rounds of blind multi-agent red/green/ETL/refactoring review, and validated against pinned corpus inputs (74,221 URLs, 120 retained Wayback CDX responses, 7+9 scheduler scenarios, 1,563 accepted PDF repair bodies; 370 pytest checks pass).


## Notes

**2026-11-01T02:34:12Z**

Completed implementation and 3-round blind review (R1, R2-F1..R2-F10, R3-F1..R3-F5) plus Section 6 baseline comparison:
- Work Item 1 (discovery.py): showResumeKey pagination, time-window bounds, empty HTTP 200 [] -> complete (36/120 retained CDX responses), SURT-equivalent original != target admission (145 new candidates across 15 targets, 12/12 retained replay bodies qualified, 0 false completions).
- Work Item 2 (url-rules.json & url_normalization.py): 0 mismatches between model/sql/url-normalized.sql + url-keys.sql and url_identity across 74,221 corpus URLs; 8,116 URLs and 71 merged key groups across 1,202,155 keyed_universe URLs; 4,024 published Senate &download=1 URLs unified with 0 document merges/splits in publish_v20.
- Work Item 3 (capture_scheduler.py): ADDRESS_REPAIR_RULES=('download-ampersand-query','senate-notfound','lis-gpo') + TRAILING_SPACES, done_keys/done_urls/has_state suppression, state_candidates reset/keep substitution, and cross-key attempt_aliases. All 7 retained-address + 10 post-capture/campaign scenarios pass.
- Work Item 4 (acceptance.py): fail-closed PDF bill heading corroboration (page_bill_identifiers, bill_text_disagreement, _corroborate_pdf_bill_identifier with 128 MiB cap and post-read custody check); holds HR-4824 (body H.R. 4755) and 6 unnumbered drafts as review_required while keeping 1,556/1,563 accepted.
- Work Item 5 (url_normalization.py & pipeline.py): narrow_address_repairs, scope_probe_urls, and end-to-end corpus_recovery/pipeline.py orchestration.
- Verification: 370 passed in 38.85s.

**2026-11-01T10:38:19Z**

Independent Validation Audit (2026-11-01, validator 97de9ecd):
- Verdict: PASS-WITH-CAVEATS (6/6 work items verified; 375 focused pytest checks pass; 0 SQL-vs-Python url_identity mismatches across 74,221 URLs; 120 retained Wayback CDX responses, 145 new SURT-alias candidates across 15 targets, 12/12 replay bodies, and 1,556/1,563 PDF repair bodies reproduced).
- Remaining work before closure:
  1. [Priority 2] In packages/corpus_recovery/src/corpus_recovery/url_normalization.py:351-360 (narrow_address_repairs), set `current = candidate` after appending `(candidate, 'senate_notfound_wrapper_repair')` so a `/404?notfound=%2fdownload%2f...%26download%3d1` wrapper chains into `download_ampersand_query_repair` (`?download=1`) and `trailing_space_trim_repair` in one call (matching 2-pass `url_identity`).
  2. Commit working-tree changes and record local vs live campaign/publication status.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 5 Engineer (4c90d67e, 99% confidence):
  1. Updated `narrow_address_repairs` in `packages/corpus_recovery/src/corpus_recovery/url_normalization.py:386-388` so `senate_notfound_wrapper_repair` updates `text = repaired`, chaining into `publisher_download_query_fallback` (`download-ampersand-query`) and `trailing_space_trim_repair` in a single call (`test_normalized_pipeline.py:1210-1244`).
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (99%), Green Team PASS (100%), Greybeard PASS (99%), Evolutionary Refactoring PASS (95%).

**2026-11-05T20:08:15Z**

November 5 release/root-cause follow-up: preserve this ticket's completed normalization, replay and local scheduler implementation scope. The live e145d24c389e audit and three-agent analysis found separate remaining boundaries, now owned explicitly: [ct-yci9](ct-yci9.md) for content contradicting agreeing filename package/measure claims; [ct-5esu](ct-5esu.md) for additional public lookup spellings; [ct-rie2](ct-rie2.md) for requirements-bound campaign execution and final metrics; ct-umtm for all twelve historical replay dispositions; ct-4jms for the ordinary scheduled run and Ashley download acquisition trace; ct-nh41 for explanation authoring. Current profile version 1 is valid ordinary behavior, and scheduled capture/campaign acceptance remain separate. No new retry-policy defect or distinct-document merge from trailing-space repair was established. The detailed acceptance criteria belong to those owners, not a reopened normalization umbrella. [Root-cause report](../docs/experiments/url-normalization-revalidation-20261105/root-causes.md). Ticket changes only; no implementation or execution.
