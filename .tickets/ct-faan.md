---
id: ct-faan
status: closed
deps: []
links: []
created: 2026-11-10T19:07:52Z
type: task
priority: 2
assignee: mikewolfd
---
# Release gate: prove a changed link from published correction records, not a hand list

Follow-up to the named-corrections change. The release would publish a small corrections table built from the permanent rejection records (provenance/recoveries), and the link rule would accept a changed answer only where that table shows a rejection of the live file for that address. Then no hand list is needed, later corrections pass on their own, and the site can show that a link was corrected and when. Owner chose the named list for the 2026-11-10 release and this as the later, stronger form.


## Notes

**2026-11-11T14:35:33Z**

validated 2026-11-11, left open: not started; the named-corrections list (ct-4nax) is what ships. No published corrections table exists in release 77673bfb8fcf (its archive-release files have none).

**2026-11-12T06:35:00Z**

Implemented and verified:
- Added `model/sql/corrections.sql` exporting permanent rejection records (`remaining_recovery_decisions WHERE kind='rejected'`) as `corrections.parquet` (`original_url`, `rejected_body`, `decision_id`, `decided_at`, `recovered_url`, `identity_note`), declared in `model/registries/release-schema.json` and `docs/release-relationships.md`.
- Wired `release_comparison.proven_corrections` and `release_gate` to prove changed `link_key`, `lookup_key` (including serialization alias), and `address` answers directly from `candidate/corrections.parquet` + `candidate/recoveries.parquet` without requiring a hand `corrections` list in the cause record (while retaining `named_corrections` compatibility).
- Verified with end-to-end `build_release` export tests (`test_phase1_release.py`) and 5 planted defect refusals (`test_published_corrections_proof_refuses_planted_defects` in `test_release_gate.py`).
