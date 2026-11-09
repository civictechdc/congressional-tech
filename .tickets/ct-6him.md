---
id: ct-6him
status: open
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
