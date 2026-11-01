---
id: ct-kw9b
status: closed
deps: [ct-yymr]
links: [ct-30fp, ct-vpo2, ct-h1nd, ct-pocg, ct-yymr, ct-77zb, cef-96wc, ct-1mbc, ct-9gmr]
created: 2026-10-30T14:32:30Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, model, completeness, track1]
---
# T1.4: Add Phase-2 work-list completeness & lake schema pins in archive_model.py and profile-completeness.sql

Add Phase-2 work-list completeness & lake schema pins in packages/viewer_publication/src/viewer_publication/archive_model.py and model/sql/profile-completeness.sql:
- Include meeting_records and appearance_records in lake_versions when include_entities is enabled.
- Check their pinned parser version work lists in model/sql/profile-completeness.sql.

## Accepted review scope — 2026-10-30

Reopened for blind-review finding GB3 (PHASE-2 §4.7). The current model input
construction retains every meeting/appearance parser version. Entity completeness
checks count invalid/duplicate/unsettled rows already present rather than missing
expected candidates. An empty or partial table can therefore appear complete.
Own selected-version admission and model filtering; ct-yymr owns the daily
handoff, ct-h1nd owns source-scoped version generation, and ct-vpo2 owns schema
alignment and invariants. Reuse one maintained admission path for execution and
early reuse/skip; do not add an independent validator or another engine facility.

## Acceptance Criteria

- Receive and record meeting_records and appearance_records parser selections in the semantic profile, by source when source-scoped versions are used; reject missing or inconsistent selections.
- Filter native, Parquet and fixture inputs to selected source/version rows before current-record ordering, joins or payload interpretation. Old/new versions never compete by physical order.
- Derive expected candidates from the maintained producer definitions at the pinned capture snapshot; anti-join them against results or valid unreadable dispositions at the selected source/version.
- An empty input passes only for an empty expected set or fully accounted selected-version dispositions. Missing raw reads remain pending, and old-version failures do not settle a new version.
- Apply the same admission before execution and early reuse/skip. A cheap prior completion may be reused only when its exact dependencies and required evidence remain valid.
- Fixtures cover two versions of one input, a missing current reading, wrong source/version, partial backfill, empty/nonempty expected sets and unchanged reuse. Preserve previous selected release on refusal; record focused project-runner checks.


## Notes

**2026-10-30T21:20:20Z**

Reopened for the accepted blind review. Remaining version/filtering/completeness criteria are now explicit above; evidence is archive_model.py:_record_table_sql and archive_model_profile.py:completeness_checks. PHASE-2 §4.7 GB3 and DATA-MODEL §6/§7.1 are the governing rules. No implementation or publication occurred in this update.

**2026-11-01T04:25:21Z**

Verified and tested:
- meeting-records-resolved.sql, appearance-records-resolved.sql, archive_model.py, and archive_model_profile.py filter meeting_records_input and appearance_records_input to the pinned source-scoped parser_version and enforce entity_profile_completeness (settled in current version or active_unreadable).
- Verified with uv run pytest packages/viewer_publication/tests/test_phase2_model_entities.py packages/viewer_publication/tests/test_phase1_model_profile.py.

**2026-11-01T10:39:01Z**

Independent Validation Audit (2026-11-01, validator 99cfb6de):
- Verdict: FAIL (3/6 ACs met, 3 partial; 153/153 existing tests pass, but adversarial probes K1b/K1c/K1d proved 4 candidate-vs-completeness SQL divergences).
- Remaining work before closure:
  1. [Priority 1] In `packages/viewer_publication/src/viewer_publication/archive_model_profile.py:218-281` (`expected_mr` and `expected_ar`), align candidate selection 1-for-1 with `CANDIDATE_MEETING_RECORDS_SQL` and `CANDIDATE_APPEARANCE_RECORDS_SQL` in `packages/congress_api/src/congress_api/lake/_record_producer.py:444-554`:
     - Require `(c.family='house/Committees' OR lower(coalesce(c.url,c.requested_url,'')) LIKE '%docs.house.gov%')` on `house_xml` in both `expected_mr` and `expected_ar`.
     - Align `congress_gov` URL predicates (`%api.congress.gov%/committee-meeting%` and `%congress.gov/committee-meeting%`) between `_record_producer.py` and `archive_model_profile.py`.
     - Align `mods` URL/family predicates between `_record_producer.py` and `archive_model_profile.py`.
  2. Add unit tests in `packages/viewer_publication/tests/test_phase1_model_profile.py` covering non-House `committee-meeting` XML and Congress.gov URL shapes across both producer candidate SQL and `completeness_checks`, and commit working-tree changes.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 3 Engineer (ddaead05, 99% confidence) across Round 1 & Round 2:
  1. Extracted shared capture/inline classification SQL constants (`INLINE_CONGRESS_MEETINGS_SQL`, `GOOD_FETCH_CAPTURE_SQL`, `CONGRESS_GOV_CAPTURE_SQL`, `HOUSE_XML_CAPTURE_SQL`, `MODS_CAPTURE_SQL`, `SENATE_PAGE_CAPTURE_SQL`) in `_record_producer.py:444-504` and consumed them in `archive_model_profile.py:6-13,211-355`.
  2. Unified `unreadable` schema (`body_sha256` + `record_sha`) and anti-join predicates (`u.parser IN (parser_name, short_name, parser_name || "." || c.source)` and `lower(coalesce(u.record_sha, u.body_sha256)) = lower(c.record_sha)`), aligned `LEFT JOIN current_page_readings` (`r.status IN ("completed", "error", "size_limit")`), and added `inline_cg_expected` / `mr_inline_unsettled` / `ar_inline_unsettled` to completeness verification.
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (97%), Green Team PASS (100%), Greybeard PASS (98%), Evolutionary Refactoring PASS (99%).
