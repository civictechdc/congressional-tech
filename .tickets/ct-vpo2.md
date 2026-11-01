---
id: ct-vpo2
status: closed
deps: [ct-kw9b]
links: [ct-30fp, ct-kw9b, ct-h1nd, ct-pocg]
created: 2026-10-30T14:32:30Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, model, invariants, track1]
---
# T1.3: Add Phase-2 invariant 15 & annex §2 diagnostic queries in archive_model.py

Add Phase-2 invariant & diagnostic queries in packages/viewer_publication/src/viewer_publication/archive_model.py:
- Assert Invariant 15 in model_invariants (no event_id has records naming two chambers, plus referential checks for meeting_keys, committee_keys, witness_keys, version_keys, and meetings.transcripts[].list_row).
- Emit the non-fatal diagnostic reports required by docs/plans/phase-2-annex-20261028.md §2 (appearances whose name_key differs only by title/initial within one occasion, and Senate page cards with no links).

## Accepted review ownership — 2026-10-30

GB3 confirms the earlier completeness concern. Reopened ct-kw9b now owns the
expected-candidate anti-joins, selected-version filtering and early-skip admission;
reopened ct-yymr owns the daily-to-model version handoff. This ticket retains
schema alignment and release invariants/diagnostics, coordinating with ct-30fp's
context-free appearance observations, collection states and versioned keys.
Historical zero duplicate name-derived keys is not preservation evidence.

## Acceptance Criteria

Invariant 15 referential and single-chamber checks are enforced in model_invariants, and non-fatal annex §2 diagnostic counts/reports are emitted without failing valid builds.


- Align lake/release schema and invariant checks with PHASE-2 §1.3/§2/§4.7: source-aware observation keys, explicit collection state and preserved occurrence evidence. Coordinate schema/key migration with ct-30fp rather than writing a second producer.
- Use ct-kw9b's single maintained version/completeness admission and ct-yymr's exact handoff; fixtures must reject missing selected-version readings and preserve valid repeated-name occurrences.

## Notes

**2026-10-30T19:28:54Z**

Reopened per Greybeard parity audit: align D4 lake schemas & E3 completeness gate with DATA-MODEL §4.2/§6.4 and PHASE-2 §2.1: (1) model/lake/meeting-records.schema.json and appearance-records.schema.json need status/error_type and record_sha alignment; (2) model/jobs/publish-model.json needs parser_versions pins for meeting_records and appearance_records; (3) model/sql/profile-completeness.sql needs D4 work-list completeness anti-joins against captures + meeting-sources.json.

**2026-11-01T04:25:21Z**

Verified and tested:
- Daily producer (congress_api.lake.daily) stages and commits meeting_records and appearance_records before model admission.
- archive_publish_job binds all 5 lake table pins (captures, readings, filename_readings, meeting_records, appearance_records) and source-scoped parser_versions into model_spec.
- Verified with uv run pytest packages/congress_api/tests/test_daily_producers.py packages/viewer_publication/tests/test_archive_publish_job.py.

**2026-11-01T10:39:01Z**

Independent Validation Audit (2026-11-01, validator 99cfb6de):
- Verdict: PASS-WITH-CAVEATS (1/2 ACs met, 1 partial; 153/153 focused tests pass).
- Remaining work before closure:
  1. [Priority 2] In `packages/viewer_publication/src/viewer_publication/archive_model.py:797-801`, remove `AND EXISTS (SELECT 1 FROM committees_export)` from `missing_committee_keys` so a broken/empty `committees_export` table with populated `committee_keys` in `list_export` / `meetings_export` fails Invariant 15 instead of silently passing.
  2. [Priority 2] In `packages/viewer_publication/src/viewer_publication/archive_model.py:805-812` (`appearance_name_key_variants`), allow one or more leading titles (`(?:(?:hon|honorable|dr|...)\s+)+`) and one or more middle initials so multi-title (`"the honorable dr ..."`) and multi-initial (`"john q p ..."`) variants on the same occasion are counted.
  3. Commit working-tree changes.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 3 Engineer (ddaead05, 99% confidence):
  1. Removed the `AND EXISTS (SELECT 1 FROM committees_export)` bypass from `missing_committee_keys` in `archive_model.py:797-803` so empty `committees_export` fails closed when `ordered.committee_keys` is non-empty.
  2. Expanded `appearance_name_key_variants` regex in `archive_model.py:805-823` to strip repeated leading/embedded titles and consecutive single-letter initials.
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (96%), Green Team PASS (100%), Greybeard PASS (96%), Evolutionary Refactoring PASS (99%).
