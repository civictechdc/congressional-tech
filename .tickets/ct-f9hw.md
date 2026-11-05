---
id: ct-f9hw
status: closed
deps: []
links: []
created: 2026-11-02T11:10:10Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [raw, privacy, receipts, phase2]
---
# Refuse local paths when a frozen receipt resumes

Frozen capture and recovery-import retries now verify the checkpoint and apply the same local-path check as fresh writes before upload or lost-acknowledgment reconciliation. The capture projection retains relative paths only. The owner’s November 2 and 4 exception keeps published historical receipts as written.

## Acceptance Criteria

- Prove that resuming a pre-guard receipt with an absolute `recovery_evidence.acquisition.body_path` refuses before creating a public receipt. An already-qualified safe retry remains idempotent.
- Keep the existing fresh-writer guard, relative-path capture projection and documentation. Old published receipts remain as written under the owner’s November 2 and 4 decisions.

## Notes

**2026-11-02T13:54:36Z**

Owner decision 2026-11-02: leave existing receipts as written. Exposure is the username (already public as the GitHub login) and folder layout (/Users/mikewolfd/Work/..., /Users/mikewolfd/hearing-text/...); no secrets found. Writers now refuse absolute paths (impl-e1, r1b-e1). Origins: assemble_raw_archive.py (0ea63070, 2026-09-30, about 636k lines), the old receipt builder (deleted in b46cbf58) for October download runs, and corpus-recovery runs up to 2026-10-16; none after 10-16. Close when r1b-e1 merges.

**2026-11-04T12:46:09Z**

Owner decision 2026-11-04: keep older receipts as written; data model §5.2 and invariant 3 are reworded to bind new receipt lines only.

**2026-11-05T17:11:15Z**

Closure review 2026-11-05: keep open for a reachable frozen-receipt resume gap. Fresh ReceiptWriter.write paths use the guard, capture projection drops local paths, and pipeline-data constructs URL-only records. The maintained recovery-import CLI can resume a pre-guard frozen checkpoint: ReceiptWriter.write:89–96 bypasses the guard and _apply_frozen:218–235 verifies checkpoint/body identity then uploads without the path rule. Earlier reconcile._write_import could carry recovered_filename into acquisition.body_path. No actual leaking checkpoint is established. Before closure, prove a frozen retry containing an absolute acquisition.body_path refuses before creating a public receipt, while safe retry remains idempotent. Existing published receipts retain the historical exception. Evidence: retention/receipt_writer.py, corpus_recovery/reconcile.py:281–343, test_pipeline_raw.py:197–207.

**2026-11-05T21:20:33Z**

Closed on source merge `0d2c8420` (`95738db4`). The planted absolute `recovery_evidence.acquisition.body_path` reached the upload path on the base in both checkpoint forms. The focused tests now prove refusal before any adapter call. The safe lost-acknowledgment cases preserve the original key and compressed bytes for both the pinned and gzip-only forms. The maintained recovery importer also passed its partial-failure retry check. Blind GPT-6.1 Sol/xhigh review accepted the guard. The expanded run passed 221 checks across eight selected files in the 491-file production-offline lane. The owner’s historical receipt exception remains in effect. [Base reproduction](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/receipts/privacy-before.log) · [Focused run](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/receipts/final-tests.log) · [Review handoff](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/receipts/STATUS.md)
