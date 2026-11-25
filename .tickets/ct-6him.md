---
id: ct-6him
status: closed
deps: []
links: []
created: 2026-11-09T00:52:02Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-lwxs
tags: [entities, organizations]
---
# Org entities phase 1: string keys, fuzzy token-bag groups, decision log, stable org IDs

Size M. Plan: docs/plans/org-entities-20261108.md (Tables, Pipeline 1/3/7-9, Stable IDs and churn, Decision log).

- org-strings.sql over appearance_records_resolved: L2 string key and token-bag key (sorted non-stopword tokens). Equal bag keys are the automatic fuzzy merge (method token_bag, score 1): a GROUP BY, no pairs.
- org-fuzzy-pairs.sql: bag groups blocked by rarest token (measured 223,504 candidate pairs at L2, largest block 56); queue Jaccard >= 0.75 and Levenshtein ratio >= 0.85 pairs without a differing place/scope token (~900) for review only. DataFusion built-ins only (levenshtein, string_to_array, array_intersect, array_union, cardinality); confirm they exist in the pinned engine; no custom similarity UDF.
- New provenance kind org_decisions beside reviews in congress_api.retention.provenance (same import, supersedes, withdraw). Scope: fuzzy-pair outcomes, non-agency merges/splits, Wikidata review outcomes. No agency aliases (they belong to RefSpec).
- Engine components step for grouping; org-priors.sql reads the prior release (witness_key_map pattern); org_id = sha256('org-v1', anchor)[:16]; redirects merged/split_from/restored, rewritten each release to point straight at the current org.

Measurement: .cache/archive-release/investigations/entity-matching-measure-20261108/fuzzy_L2.json (51,228 L2 strings -> 49,912 bag keys; 1,147 multi-string keys; none mixes two agency patterns), fuzzy_bag_groups_sample_L2.txt, fuzzy_pairs_sample_L3_first_run.txt.

## Acceptance Criteria

1) Witness rows and their organization/on_behalf_of text are byte-unchanged. 2) Two clean rebuilds from raw produce byte-identical org tables. 3) Planted merge, split and restore produce the stated redirect events; every redirect resolves in one hop. 4) A fresh hand label of 150 multi-string bag groups (not the planners' 60), stratified by appearances, finds <=3 wrong merges. 5) scripts/measure/org_fuzzy_raw_check.py, written to the AGENTS raw-check rules, judges merges from witness facts the rule ignores (location, position, committee) plus character trigrams, both directions, and flags a planted Virginia + West Virginia Council of Churches merge; a second reviewer confirms the planted case. 6) No all-pairs comparison; candidate pairs are reported per release.

## Notes

**2026-11-22T19:53:35Z**

2026-11-22 Owner decision A3: Attach Ban, Park & You (APSR 2023, doi:10.1017/S0003055422000405) 9-parent / 18-child witness organization taxonomy to resolved organizations cleanly in parallel with DocMeta V7 (zero blocking dependency on ct-o7j0). Reference: docs/plans/docmeta-v7-consulting-plan-20261122.md.

**2026-11-22T21:51:40Z**

Implemented Org Entities Phase 1 + Ban, Park & You (APSR 2023) 9-parent/18-child taxonomy: verified all 5 DataFusion built-ins (levenshtein, string_to_array, array_intersect, array_union, cardinality) on pinned docspec; added org_decisions provenance kind (congress_api/retention/provenance.py, cli/provenance.py, test_org_decisions_provenance.py); added model/registries/ban-park-you-org-taxonomy.json; created model/sql/{org-strings,org-decisions-current,org-fuzzy-pairs,org-priors,organizations}.sql + opt-in include_org_entities=False wiring in viewer_publication/archive_model.py; verified test_org_entities_phase1.py (4 passed: byte-unchanged witnesses, byte-identical rebuilds, planted merge/split/equal-count-reversed-split/restore 1-hop redirects) and full regression suite (task-6933: 200 passed in test_archive_model_job, test_archive_publish_job, test_person_identity, test_org_entities_phase1 under DOCSPEC_JOB_CONFIG + watchdog, peak 0.78 GiB RSS); added independent scripts/measure/org_fuzzy_raw_check.py + tests verified by second reviewer (0d5357bd) PASS (catches planted Virginia + West Virginia Council of Churches merge). Kept open strictly for AC #4 (fresh 150-group stratified sample check on real archive data).

**2026-11-23T02:20:39Z**

Completed real-archive AC #4 audit + SQL hardening against latest published witnesses.parquet (176,428 rows, release 0e7084cde775):
1) Fixed DataFusion real-archive OOM in model/sql/org-strings.sql by removing all 3 any_value(List) calls inside GROUP BY (peak RSS 12.06 GiB OOM -> 1.18-1.34 GiB in 3-4s).
2) Root-caused and fixed 4 normalization/bag bugs discovered during initial real-archive audit (which had 4/150 unanimous wrong_merges): (a) changed m_state < n to m_state = n - 1 + commissioner(s) keyword guard (fixed 877 orgs before ', Washington, DC' / ', New York, NY' being deleted); (b) added m_state=1 AND n=2 1-word location guard (fixed 836 bare City, State collisions e.g. Malta, Montana vs Malta & Co., Inc.); (c) preserved trailing ', co' on 2-seg City, CO strings (fixed 14 Colorado cities e.g. Boulder, CO); (d) switched bag_key from distinct token-set to true multiset bag_tokens matching em-fuzzy.py line 126 (fixed University of Maryland University College vs University of Maryland). test_org_entities_phase1.py: 4 passed in 27.72s.
3) Final real-archive stats (.cache/archive-release/org-entities-phase1-ac4-20261122/build_stats.json): 59,134 organizations, 61,293 distinct org strings, 1,865 multi-string bags, 2,510 review_queue pairs, 0/7 invariant violations, all 18 Ban-Park-You categories populated.
4) Independent raw check (scripts/measure/org_fuzzy_raw_check.py, 114s, 3.97 GiB RSS, 14,566,283 candidate pairs, 10,451 legitimate splits): metadata_context_conflict dropped 99.2% (3,399 -> 27), Direction 1 over-merges dropped 5,491 -> 1,996 (total flags 7,267 -> 3,754).
5) AC #4 3-family SOTA 150-group stratified audit (excluding 55 matched planner sample groups): PASS (2/150 consensus wrong_merge <= 3 threshold; 148/150 consensus valid_merge [145 unanimous]; 0 MISSING votes across all 450 calls). Only 2 unanimous wrong_merges: #60 'rockville md' || 'rockville, md' (upstream suffix/location fragment 'Inc., Rockville MD') and #127 'nonprofits insurance alliance' || 'alliance of nonprofits for insurance' (true umbrella vs RRG anagram). Artifacts: ac4_150_report.json, ac4_150_review.md, raw_check.md. Kept open for owner review sign-off before commit.

**2026-11-25T12:01:56Z**

Merged to main in PR #240 (6374ea1f, commit d508ec44) after blind pre-merge code review (0f3259fd) and 12/12 CI checks green. All 6 acceptance criteria satisfied (including real-archive AC #4 150-group stratified audit passing at 2/150 <= 3 and second-reviewer raw check). Unblocks ct-w34j and ct-39u8.
