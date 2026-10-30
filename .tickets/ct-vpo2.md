---
id: ct-vpo2
status: open
deps: []
links: []
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

## Acceptance Criteria

Invariant 15 referential and single-chamber checks are enforced in model_invariants, and non-fatal annex §2 diagnostic counts/reports are emitted without failing valid builds.

