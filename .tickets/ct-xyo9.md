---
id: ct-xyo9
status: closed
deps: []
links: [ct-syp1, ct-wscb]
created: 2026-11-10T08:21:50Z
type: task
priority: 2
assignee: mikewolfd
tags: [gate, release]
---
# Release gate: leftovers from the second review of the gate rules

Second-pass review of claude/ct-gate-rules (31d53712), 2026-11-10: push as is, no blocker; these remain. Report: .cache/archive-release/investigations/gate-rules-20261110/review/REVIEW.md, 'Second pass'. (1) ct-syp1: two NEW cache files swapped between channels still verify; the cited-file check accepts any newly captured body (citing 52 unrelated new bodies passed), so it should require a body of the video-records family for that channel; nothing bounds how many citation-only rows change in one night; with automatic causes off and no record, made-up hashes pass. (2) ct-wscb: an address re-pointed to the sibling half of a correct split passes and no group moves. (3) ct-gc99: the cap of 250 counts documents only (one document with 5,000 addresses passed); cap keys and addresses per document or in total. (4) A candidate key that is both published and retired is never checked (a two-fault plant passed). (5) Three docstrings overclaim: swaps, 'a reviewed publish has this check', and captures 'the candidate does not control' (they are the candidate build's own pinned input; raw is not read). (6) No test covers the job-level retry wiring for receipt reads.

## Acceptance Criteria

Each numbered item is fixed with a failing-first test from the reviewer's plant, or declined with evidence recorded here; the docstrings state only what the code does.


## Notes

**2026-11-10T13:27:30Z**

2026-11-10: no work since filing. The gate rules it follows (ct-syp1, ct-gc99, ct-4qld, ct-wscb) are on main in e6c1865c and ran in the 12:15Z scheduled nightly without a refusal (release unchanged, so no comparison groups were formed).

**2026-11-11T14:35:33Z**

validated 2026-11-11, left open: none of the six items has been worked (git log --grep ct-xyo9 finds only the filing commit e6c1865c). Each still needs a failing-first test from the reviewer's plant or a recorded decline.

**2026-11-12T03:11:00Z**

Resolved all six second-pass review items via Red -> Green plant tests and measured evidence:
1. **ct-syp1 video cache citations & `S_ABSENT`:**
   - Added `new_video_citations` (`release_comparison.py`) and tightened `cited_files_are_new` (`release_gate.py`) to require every newly cited video/channel `record_sha` to have a `pipeline-data` (`mode='fetch'`, `complete`, `outcome IN ('stored','unchanged')`) YouTube cache JSON capture (`youtube/youtube_NN.json`, stopping `S_OTHERBODY`), and every moved channel pair `(old_sha, new_sha)` to share the same `youtube/youtube_NN.json` cache path (verified 119/119 channels across 52 cache files on `candidate-2-at-gate`, stopping `S_SWAPNEW`; tested in `test_cache_refresh_refuses_non_youtube_cache_body_and_swapped_channel_caches`).
   - Closed `S_ABSENT` in `require_release_gates`: when both `automatic` and `causes` are `None`, any `refetch_only` group refuses with `comparison: re-fetch group ... requires automatic capture verification or a cause record` (`test_refetch_only_groups_refuse_when_both_automatic_and_cause_record_are_absent`).
   - **Declined sub-100% row-count cap on citation-only rows with measured evidence:** on a real weekly refresh (`630164505301 -> 619db5f9e08e`), `save-pipeline-data` rewrites all 52 cache files at once, moving 119/119 `channels` rows (100%) and 67,373/67,668 `videos` rows (99.6%); any sub-100% cap would break every weekly refresh, while `cache_churn` joins on matched base keys so counts cannot exceed the base table size. Stated explicitly in `cache_churn` and `docs/releases/README.md`.
2. **ct-wscb split sibling address (`W1s`):**
   - **Declined with structural evidence + characterization test:** published `sources.parquet` and `urls.parquet` associate addresses and lookup keys with release-local `list_row`, carrying no per-address body hash (only `captures` knows which body was fetched at each URL, `rg_12_address_truth.py`). Because `moved()` projects a split base row through `pairs` to every sibling half while a candidate address sits on one half, `documents changed for a shared key` counts every address of a split row regardless of which half it reaches (`11` vs `11`), while `split rows` stops unattended publication and sends the split to human review. Documented in `moved`, `changed_addresses`, and `docs/releases/README.md`, and pinned in `test_split_document_address_sent_to_sibling_half_counts_in_shared_key_group`.
3. **ct-gc99 per-document and nightly caps on keys and addresses (`C1`, `C250`):**
   - Measured across all 442,109 archive documents (max 7 link keys, 38 source rows, 45 lookup rows per doc; p99.9 = 4, 6, 7) and 2026-11-10's 731 added documents (max 2, 2, 3 per doc; 744 link keys, 719 sources, 1,056 urls). Added `AUTOMATIC_LINK_KEYS_PER_DOCUMENT_CAP = 10`, `AUTOMATIC_ADDED_LINK_KEYS_CAP = 500`, `AUTOMATIC_ADDRESSES_PER_DOCUMENT_CAP = 50`, and `AUTOMATIC_ADDED_ADDRESSES_CAP = 1000` in `automatic_causes` before starting any engine job (`test_added_link_key_and_address_caps_refuse_before_any_engine_job`).
4. **Candidate key both published and retired (`R3`):**
   - Added `published_and_retired` (`candidate_links INTERSECT candidate_retired_links`) to `link_rule` and non-waivable refusal in `verdict` (`test_link_rule_refuses_a_key_that_is_both_published_and_retired`, `test_gate_refuses_a_candidate_key_both_published_and_retired`).
5. **Three overclaiming docstrings:**
   - Updated `refetched_files`, `cache_churn`, `cited_files_are_new`, and `url_state_proof` docstrings to state accurately how live vs new swaps are checked, how `require_release_gates` handles `refetch_only` without `automatic_causes`, and that `captures` is the candidate build's pinned lake input written by ingest (without reading raw receipts in `cited_files_are_new`).
6. **Job-level retry wiring test:**
   - Added `test_execute_wires_retrying_receipt_client_when_automatic_causes_is_enabled` in `test_archive_publish_job.py` verifying `archive_publish_job.execute` wraps `receipt_client` with `configure_read_retries` while keeping single-attempt writes on `client`.
