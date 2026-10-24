---
id: ct-r33r
status: closed
deps: [ct-3lz2]
links: []
created: 2026-10-20T16:51:25Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-a1aa
tags: [news-lake, contract, validation]
---
# Enforce C2, C6, and C7 invariants in validate_shape and check_corpus

Several normative rules in 02-core-spec.md are bypassed during shape or corpus validation:
1. check_corpus (contract/semantics.py) and publish_release (storage/releases.py:105) never call apply_decisions(records), allowing releases with cyclic same_as merges, different_from contradictions, authoritative-ID collisions, or invalid retractions to pass C7 validation and publish.
2. validate_shape (contract/records.py:52-62) does not check math.isfinite on float values (unlike docs/checks/validate.py:41-48); NaN and Infinity are only caught in parse_jsonl, so in-memory dicts with float('nan') or float('inf') pass validate_shape, check_corpus, and Coordinator.commit into Parquet (and later fail replay dedup with append_collision because NaN != NaN).
3. check_corpus does not enforce C7 input-reference acyclicity (02-core-spec.md §4: 'Input references are acyclic') or verify that version records with extracted text come from succeeded, non-metadata_only captures (C4/C5).
4. check_corpus does not reject duplicate connector_key entries in release.checkpoints or unredacted userinfo credentials (user:pass@) in URLs and checkpoint_refs (C2).

## Design

1. In contract/records.py (_reject_nulls or a combined recursive walk in validate_shape), reject any float where not math.isfinite(value) with ContractError('non_finite_number').
2. In contract/semantics.py (check_corpus), invoke apply_decisions(records) to enforce all C6 decision-graph invariants on the candidate corpus.
3. In check_corpus, verify that the run -> input_ref -> output dependency graph is acyclic, that version records come from succeeded captures (and versions with text do not reference metadata_only captures), that release.checkpoints has at most one entry per connector_key, and that URL / checkpoint_ref fields contain no unredacted userinfo credentials.

## Acceptance Criteria

- validate_shape rejects float('nan'), float('inf'), and float('-inf') in any numeric field with rule='non_finite_number'; restore the non-finite numeric score case in test_contract_records.py.
- check_corpus and publish_release reject corpora with decision cycles, contradictory decisions, authoritative-ID conflicts, and invalid retractions.
- check_corpus rejects cyclic run/version input references, versions extracted from failed/not_modified captures, versions with text extracted from metadata_only captures, duplicate connector_keys in release.checkpoints, and URLs/checkpoints containing userinfo credentials.


## Notes

**2026-10-20T17:11:37Z**

Implemented validate_shape(record, allowed_extra=()) with non-finite rejection and chained-reference-safe extra stripping; check_corpus now enforces C6 decision graphs, C7 run-input acyclicity, capture/version compatibility, unique release checkpoint connector keys, and C2 credential redaction. Added validated_ids and allow_extra_by_kind parameters for storage integration. Contract tests: 73 passed.

**2026-10-20T17:30:45Z**

validate_shape now rejects non-finite floats and accepts only named evolved-schema extras. check_corpus enforces the C6 decision graph, C7 run-input acyclicity, capture/version access compatibility, unique checkpoint connector keys, and C2 credential redaction; validated_ids and allow_extra_by_kind support storage integration. Contract tests: 73 passed.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch kl2a1aa).
- Grades: proposal 91 → 91, work 86 → 86.
- Problem: The C2/C6/C7 check was narrowed: a metadata-only version from a failed capture is still accepted.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:54
- Area owner: WS8 (ct-d8cf); not a named step.
- See docs/reviews/2026-10-24-ticket-audit/README.md
