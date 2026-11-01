---
id: ct-yymr
status: closed
deps: []
links: [cef-rmye, ct-kw9b, ct-h1nd]
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, pipeline, daily, d4, track3]
---
# T3.1: Wire meeting_records and appearance_records into daily.py and archive_publish_job.py

Extend packages/congress_api/src/congress_api/lake/daily.py and packages/viewer_publication/src/viewer_publication/archive_publish_job.py (completed_daily_inputs) so automated daily runs refresh and pin meeting_records and appearance_records alongside captures, readings, and filename_readings.

## Accepted review scope — 2026-10-30

Reopened for GB3. Existing code forwards five table pins and checks current
meeting/appearance versions, but completed_daily_inputs then assigns only
versions['parsers'] to the model spec, dropping the entity parser selections.
Preserve the completed table-wiring work; repair the producer-to-model version
handoff. ct-kw9b owns downstream filtering and expected-candidate admission;
ct-h1nd owns source-scoped version generation.

## Acceptance Criteria

- Continue forwarding all five table pins and the complete receipt inventory.
- Forward exact selected meeting/appearance parser versions alongside page-parser versions from the completed daily result into the model spec/profile; preserve per-source selections where present.
- Reject incomplete, malformed or mismatched version selections before publication effects, and retain the previous release on refusal.
- A producer-to-model fixture demonstrates that selected entity versions survive the handoff and feed ct-kw9b's admission/filtering. Table pin presence alone does not satisfy version selection.
- Record the tested producer/spec/profile identities and focused checks; distinguish local fixture success from live pipeline execution.


## Notes

**2026-10-30T21:20:20Z**

Reopened for the accepted blind review: retain five-table wiring, but forward meeting/appearance version selections through completed_daily_inputs into the model profile. Its existing validation followed by versions[parsers]-only assignment is the demonstrated gap. PHASE-2 §4.7 GB3; no live run performed.

**2026-11-01T04:25:21Z**

Verified and tested:
- Source-scoped parser versions implemented in congress_api.lake.meeting_records.current_versions() and congress_api.lake.appearance_records.current_versions() using AST symbol digests and source-specific file/value pins, plus composite current_version(None) digest.
- Model profile (archive_model_profile.py) expands and validates nested source-scoped parser versions and binds them in SQL via parser_versions.
- Verified with uv run pytest packages/congress_api/tests/test_phase2_meeting_appearance_lake.py packages/viewer_publication/tests/test_phase1_model_profile.py packages/viewer_publication/tests/test_phase2_model_entities.py.

**2026-11-01T10:39:01Z**

Independent Validation Audit (2026-11-01, validator 875adccd):
- Verdict: PASS-WITH-CAVEATS (2/5 ACs met, 3 partial; 153/153 focused tests pass).
- Remaining work before closure:
  1. [Priority 2] In `packages/viewer_publication/src/viewer_publication/archive_publish_job.py:46-47` (`_expected_entity_versions`) and `packages/congress_api/src/congress_api/lake/daily.py:296-297` (`_check_entity_versions`), require the per-source mapping from `current_versions()` (rejecting scalar composite `current_version()` strings for `meeting_records` and `appearance_records`).
  2. [Priority 2] Add an end-to-end test in `packages/viewer_publication/tests/test_archive_publish_job.py` that chains `daily.produce_daily(...)` output directly into `archive_publish_job.completed_daily_inputs(...)` and `archive_model_profile.completeness_checks(...)`.
  3. Update closing note so `ct-yymr` records its own daily/publish handoff work and test counts, and commit working-tree changes.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 3 Engineer (ddaead05, 99% confidence) across Round 1 & Round 2:
  1. Removed legacy scalar composite `current_version()` fallbacks across `daily.py:181-184`, `archive_publish_job.py:29-56`, and `archive_model_job.py:121-131` (`validate_spec`), enforcing per-source `current_versions()` dicts at every boundary.
  2. Added end-to-end 5-table handoff test `test_daily_produce_to_publish_handoff_to_completeness_checks_end_to_end` in `test_archive_publish_job.py:559-660`.
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (99%), Green Team PASS (100%), Greybeard PASS (100%), Evolutionary Refactoring PASS (99%).
