---
id: ct-59rh
status: open
deps: []
links: []
created: 2026-11-18T22:03:16Z
type: task
priority: 2
assignee: mikewolfd
---
# R2 ambiguous create-once writes (PR 211)


PR 211 (branch r2-body-create-reconcile, commit 5422dcbd) confirms an ambiguous
R2 create-once write (503 after the request) by HEAD, then replays. The
independent review returned CHANGES NEEDED with three findings.

## Review findings (all three still to be implemented)

1. Scope: a matching HEAD after a 503 must not turn an ordinary receipt-name or
   provenance collision into `stored` (matching bytes cannot show which writer
   created the object; see packages/congress_api/tests/test_unreadable_import.py:29).
   Limit confirm-then-replay to content-addressed bodies and explicitly frozen
   receipts (PR 189 path). A replay 412 on any other key stays a collision.
2. Only 404/NoSuchKey counts as absent. If HEAD itself fails (5xx, throttling,
   transport) for the whole poll, raise the original error; do not replay.
3. Wait bound: keep the per-object poll, add a per-writer-instance total
   reconciliation budget so a run with many ambiguous writes fails fast.
   State both bounds in the docstring and PR body.

Reuse the frozen-receipt poll; no second helper. First-attempt 412 unchanged.

## Status

Done: findings written up, nothing yet implemented; the agy fix run was stopped
at the session limit with no changes made. PR 211 head is still 5422dcbd.
Remaining: the three code changes, planted tests (503 then matching object on an
ordinary receipt/provenance create must NOT report stored; HEAD-error poll
raises the original error; budget stops further waits), show tests fail on
5422dcbd and pass after, update the PR body (Why/What/Checks plus the bounds).

## Definition change

This is a model definition change (body_store.py is hashed since PR 203). Batch
it with the recording-match PR under one cause record.
