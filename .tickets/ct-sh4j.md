---
id: ct-sh4j
status: closed
deps: []
links: [ct-v967, ct-77zb, cef-nkzp, ct-h1nd, ct-d0o0, cefr-7sar, ct-kac4, ct-64el, ct-n2cy, ct-5f3e, ct-c6b0]
created: 2026-10-30T21:13:37Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [data-model, review, correctness]
---
# Preserve per-attempt capture eligibility separately from final fetch state

Blind greybeard/data-engineering review of the current data model found that final request facts can promote a prior incomplete body. captures.py assigns final status to body rows and derives prior completeness without reading the pointed attempt. test_captures_ingest.py:test_prior_body_does_not_borrow_recorded_final_completeness currently expects prior (206, false) to become (200, true). Correct DATA-MODEL §6.1/§7.3/§7.7 and the maintained implementation without widening retained payloads or changing raw evidence.

## Design

Owner: congress_api/lake/captures.py and native receipt projection, model/sql/good-fetches.sql and url-state consumers. Read only the narrow eligibility scalars of each referenced attempt while the receipt is already open. Keep body eligibility distinct from final line/item scheduling facts. Explicit incomplete/error values must not be overwritten by a later successful attempt; unknown prior eligibility stays unknown. Preserve the scoped legacy final-response derivation where evidence supports it. Version schema/mapping changes, compare affected outputs by cause, and retain selected releases and source locators.

## Acceptance Criteria

- Earlier 206/incomplete and 403/error bodies followed by a final 200 response remain ineligible originals; the valid final body remains eligible.
- A valid prior body followed by final failure keeps its own eligibility, while URL scheduling reports the final failure and counts the fetch once.
- Missing prior facts are not inferred from final success; explicit contradictory attempt/capture facts refuse or produce a named unresolved disposition.
- Tests cover ordinary, list-valued, provider-retry and archive-member records, entry/pointed-attempt precedence, and final-line scheduling. No prior payload expansion or repeated receipt read is added merely to recover these scalars.
- Version and document the capture schema/mapping change; preserve raw rows, original locators, selected releases and rollback references. Reconcile changed document eligibility by cause on retained inputs before live publication.
- Replace the regression assertion that currently blesses incomplete-to-complete promotion. Record focused project-runner checks and distinguish local from live acceptance.


## Notes

**2026-11-01T04:27:19Z**

Verified and tested:
- Expanded model/lake/captures.schema.json and congress_api.lake.captures to 37 public columns in §6.1 order (nullable outcome, plus attempt, fetch_http_status, fetch_outcome).
- Extended congress_api.lake.receipt_metadata and congress_api.lake.captures to extract prior_attempts and record.captures within the single json_get_many projection, decode per-attempt http_status, complete, and outcome separately from final fetch_http_status and fetch_outcome, and refuse conflicting attempt facts.
- Updated capture_backfill_guard.py and archive_url_state.py so good-fetches uses per-attempt eligibility while url_state uses final fetch_http_status / fetch_outcome.
- Verified with uv run pytest across all 12 coupled capture/url_state test files (721 passed).

**2026-11-01T10:39:01Z**

Independent Validation Audit (2026-11-01, validator cf08c5da):
- Verdict: FAIL (2/6 ACs met, 3 partial, 1 not met; 146/146 coupled tests pass, but `test_captures_typed.py::test_bounded_metadata_fanout_preserves_public_rows` OOMs under 512 MiB and adversarial probes found 5 edge-case defects):
- Remaining work before closure:
  1. [Priority 1] In `packages/congress_api/src/congress_api/lake/captures.py:242-243` (`selected_records`), swap `FROM entry_facts e LEFT JOIN (SELECT * FROM items ...) i` to `FROM (SELECT * FROM items ...) i RIGHT JOIN entry_facts e` so `items` is the HashJoin build side instead of the 131,072-row unnested `entry_facts` (fixing the 512 MiB OOM in `test_bounded_metadata_fanout_preserves_public_rows`).
  2. [Priority 1] In `packages/congress_api/src/congress_api/lake/captures.py:310-312` (`prior_pointer_slot`), check pointer indices `(0, 1, 2, 3)` instead of `(0, 1, 2)` so valid prefixed domain-item pointers `['record', 0, 'receipt', 'prior_attempts', 0, 'body']` resolve slot `0` instead of raising `conflicting attempt facts`.
  3. [Priority 1] In `packages/congress_api/src/congress_api/lake/captures.py:326-333,418-433`, do not assign `attempt=0` or final `http_status`/`complete` to unpointered `file_references` (`reference_kind='file'`, `pointer=None`, `attempt=None`) when `prior_attempts` is present (`confirmed_final` is False).
  4. [Priority 1] In `packages/congress_api/src/congress_api/lake/captures.py:461-470,528-531,607-612` and `capture_backfill_guard.py:47-53`:
     - Check `prior_error` / `cap_error` and non-2xx/304 status against `prior_mapped_outcome='stored'` / `cap_mapped_outcome='stored'` (refusing contradictory attempt facts).
     - Refuse conflicting `fetch_http_status` / `fetch_outcome` across entries of the same fetch (`attempt=0` or `record.captures`) when `source_final_status` is absent.
     - Handle bodiless (`sha256=None`) prior capture entries (`attempt>=1`) consistently between `stage_captures` and `validate_generation`.
  5. [Priority 1] In `packages/viewer_publication/src/viewer_publication/archive_url_state.py:40-45` and `model/sql/url-state.sql:3-6`, include `requested_url` in `url_state_good_lines` and join `USING(receipt_key, receipt_line, requested_url)` so a good fetch on one item of a list-valued `record` cannot contaminate `last_good_at` on a failed item on the same line.
  6. [Priority 2] In `packages/congress_api/src/congress_api/lake/capture_comparison.py:26,254`, remove `o.http_status=n.source_entry_status AND n.http_status=n.source_final_status` from `restored_status` per `docs/plans/simplification-plan-20261024.md:224`.
  7. Update closing note with accurate test counts (`146 passed` in the 12 modified files; `751` across all 58 capture/url_state files) and commit working-tree changes.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 1 Engineer (19a7dbac, 99% confidence) across Round 1 & Round 2:
  1. Swapped `selected_records` join order in `captures.py:242-243` to `FROM (...) i RIGHT JOIN entry_facts e` so `items` is the HashJoinExec build side (passes 131,072-row `test_captures_typed.py` under 512 MiB `proof/native-limits.json`).
  2. Expanded `prior_pointer_slot` to `(0, 1, 2, 3)` in `captures.py:310-312` and restricted `record_pointer_index` slot-1 fallback in `receipt_metadata.py:57-61` to `json_get_str(pointer, 0) = "record"`.
  3. Gated unpointered `file_references` on `confirmed_final` (`captures.py:326-332,414-452`), enforced `attempt = 0` in `final_body_candidate` (`:558`), enforced `WHEN mapped_outcome NOT IN ("derive", "stored")` (`:475,481,488,590`), and enforced `outcome_conflict` + `item_status_conflict` (`:432-436,532-543,626-627`).
  4. Keyed `url_state_good_lines` in `archive_url_state.py:40-47` and `model/sql/url-state.sql:5` on `USING (receipt_key, receipt_line, requested_url)` and removed `restored_status` from `capture_comparison.py:26,280-287`.
  5. Updated `APPROVED_MAPPING` in `test_captures_version.py:7` to `ccfcb90d216dd705de01b5d1b49dd5078c73600ece63e0b82d7c87ffde9eaf3b`.
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (98%), Green Team PASS (100%), Greybeard PASS (100%), Evolutionary Refactoring PASS (99%).
