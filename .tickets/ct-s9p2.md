---
id: ct-s9p2
status: closed
deps: []
links: [ct-f7p8, ct-h23e, ct-6rnk]
created: 2026-10-22T13:16:00Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-8kl2
tags: [committee_explorer, issue_history, ids, memory, provenance]
---
# Deduplicate superseded prior-snapshot source_record citations on recurring DataIssues and prune issue-history / ids.json snapshot bloat

Holistic diagnostic of `pipeline-data` revealed that `AdapterContext.source` keys `source_record` UUIDs on `provider|input_id|native_key|digest(payload)` (where `input_id` is the whole-file digest), and `Assembly.finish()` (`assemble.py:963-984`) unconditionally unioned `old.provenance.citations` with `now.provenance.citations` and walked `_references(old)` even when `now` already carried a current observation for the exact same `(provider, identifier.scheme, identifier.value)`. Over 5 weekly runs, this accumulated 417,497 duplicate snapshot `source_record` rows (70.1% of the 595,951 rows / 1.69 GB in `issue-history`) and placed two 24.45 MB copies of the same Senate PDF (`d2dc516a` and `d36c2790`) into the same 8,192-row batch of `sources-5.parquet`.

## Design

1. In `apps/committee_youtube/src/committee_explorer/assemble.py` (`_SpilledSources` and `Assembly.finish`), index current `(provider, identifier.scheme, identifier.value) -> source_id` during source ingestion, and in `IssueHistory` (`history.py`) provide a lightweight `source_identities(ids)` helper that extracts `(provider, identifier.scheme, identifier.value)` only for candidate prior-snapshot IDs on recurring issues (`key in self.records`).
2. When merging a recurring `DataIssue` (`key in self.records`) in `Assembly.finish()`, drop any citation from `old.provenance.citations` whose `(provider, identifier.scheme, identifier.value)` is already represented in `now.provenance.citations` or `self.sources` (preserving citations to genuinely distinct `(provider, identifier)` observations), and walk `_references(self.records[key])` rather than `_references(old)` so superseded `old.subject` / `old.provenance.citations` source IDs are not added to `retained`.
3. Add a boy-scout state pruning pass in `history.py` / `ids.py` so unreferenced prior-snapshot `source_record` rows in `issue-history` and unreferenced `source_record` keys in `ids.json` are pruned cleanly during export.

## Acceptance Criteria

1. Recurring `DataIssue`s replace superseded same-`(provider, identifier)` snapshot citations with the current observation while preserving distinct `(provider, identifier)` observations (`test_explorer_history.py` passes 100%).
2. Exporting `pipeline-data` prunes the ~417k duplicate snapshot `source_record` rows from `issue-history` and `sources-*.parquet` (leaving only 1 copy of the Senate PDF row instead of 3).

## Notes

**2026-10-22T15:38:56Z**

Verified _dedup_citations + IssueHistory.source_identity pruning: recurring DataIssues drop superseded prior-snapshot source_record citations, shrinking retained historical sources on full pipeline-data from 425,368 to 82,261 (651,623 -> 308,516 total source observations, 6 -> 3 sources-*.parquet shards).

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch kl2a1aa).
- Grades: proposal 87 → 87, work 83 → 83.
- Problem: It fixes the symptom. The cause named in the ticket (the `source_record` UUID is keyed on the whole-file `input_id`) is left, so every weekly run still mints new UUIDs and the dedup must run forever.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:36
- Not covered by a plan workstream; the root cause (the `source_record` UUID keyed on the whole-file `input_id`) remains.
- See docs/reviews/2026-10-24-ticket-audit/README.md
