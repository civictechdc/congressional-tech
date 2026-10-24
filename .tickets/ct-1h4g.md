---
id: ct-1h4g
status: closed
deps: []
links: []
created: 2026-10-20T16:51:40Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-a1aa
tags: [news-lake, storage, control]
---
# Harden writer fencing, release availability gating, and abandon_cycle rollback

Three control-plane safety gaps exist in storage/:
1. storage/releases.py:142-146 (read_release) checks if control.availability(release_id) == 'retired' instead of != 'available'. If publish_release crashes after coordinator.append_release (line 122) and before control.mark_available (line 129), availability is None, yet read_release serves the unreleased in-flight release.
2. storage/coordinator.py:210-261 (abandon_cycle) picks its baseline via _latest_available_release(), which orders by (recorded_at, id) rather than publication order and returns None if all prior releases were retired (causing abandon_cycle to delete all rows in all 12 tables). abandon_cycle also leaves orphaned staged_checkpoints rows in SQLite, and if a crash occurred after release_append and before set_cycle_state('released'), abandon_cycle leaves an orphaned release row in news.releases. In addition, publish_release rebuilds build_release(...) on retry instead of pinning the candidate snapshot list in the journal once committed.
3. storage/control.py and storage/coordinator.py check require_epoch(self.epoch) only at method entry (TOCTOU): a stalled writer fenced mid-commit continues mutating SQLite and committing remaining Iceberg tables.

## Design

1. In read_release, require control.availability(release_id) == 'available' (after verifying the release record exists so unknown_release and retired_release remain distinct from unreleased_release).
2. Track release publication sequence in ControlStore and record the baseline release_id (or pinned snapshots) in the cycle journal; in abandon_cycle, refuse to wipe tables if prior releases exist but are retired unless restoring to the last published snapshot, delete staged_checkpoints for the abandoned cycle, and forbid abandoning a cycle whose release record has already been appended to news.releases. Persist the built release record in the journal once candidate commits finish so retries never drift snapshot IDs.
3. Pass epoch into ControlStore mutators (enforcing epoch inside each SQLite transaction) and re-check require_epoch before each table commit in Coordinator._commit_table.

## Acceptance Criteria

- Calling read_release on a cycle that crashed after release_append and before cursor_advance/mark_available raises ReleaseError('unreleased_release') until recover() finishes.
- Retiring release A and then abandoning a failed cycle B restores the tables to release A's pinned snapshots rather than wiping the warehouse to empty, and removes cycle B's staged_checkpoints.
- If a second Coordinator claims the writer fence while the first Coordinator is mid-batch or mid-publish, the fenced Coordinator raises FencedError before the next table commit or SQLite state transition. Add a concurrent-acquisition fencing test.


## Notes

**2026-10-20T17:30:45Z**

Fencing is enforced inside BEGIN IMMEDIATE control-store transactions and re-checked before each table commit; read_release requires available status; publication sequence drives abandon baselines; abandon refuses appended releases and all-retired wipes, discards staged checkpoints, and restores atomically; release records are journaled. Recovery/release tests pass. Residual cross-system fence race documented in README.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch kl2a1aa).
- Grades: proposal 84 → 84, work 80 → 80.
- Problem: AC2 was narrowed: "retire A, abandon B" raises `no_available_baseline` instead of restoring A, and the test asserts that refusal.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:51
- Covered by: WS8 (ct-d8cf), which ports the fencing tests and re-checks the epoch on every commit.
- See docs/reviews/2026-10-24-ticket-audit/README.md
