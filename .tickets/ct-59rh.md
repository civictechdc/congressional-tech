---
id: ct-59rh
status: closed
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

## Review findings (implemented on branch r2-body-create-reconcile)

1. Scope: a matching HEAD after a 503 must not turn an ordinary receipt-name or
   provenance collision into `stored` (matching bytes cannot show which writer
   created the object; see packages/congress_api/tests/test_unreadable_import.py:29).
   Limit confirm-then-replay to content-addressed bodies (`bodies/sha256/<xx>/<sha256>`)
   and explicitly frozen receipts (`ReceiptWriter._apply_frozen` / `ReceiptWriter._settled`).
   Every other create keeps `origin/main` behaviour, and a replay 412 on any other key stays
   a `RawNameCollision`.
2. Only `404` or `NoSuchKey` counts as absent. If HEAD itself fails (5xx, throttling,
   transport) through the whole poll, raise the original error and do not replay.
3. Wait bound: keep the per-object poll (`SETTLE_SECONDS = (0, 2, 5, 15)`, 22s max per object)
   and add a per-writer-instance total reconciliation budget (`RECONCILE_BUDGET_SECONDS = 66`,
   66s max cumulative sleep per writer, three full 22s polls) shared across body and
   frozen-receipt creates so a run with many ambiguous writes fails fast. Both bounds are
   documented in docstrings and the PR 211 body.

Reuse the frozen-receipt poll (`reconcile_create`); no second helper. First-attempt 412 unchanged.

## Status

Done: all three review findings implemented in `body_store.py` and `receipt_writer.py`, with
planted tests across `test_body_store_contract.py`, `test_receipt_writer_contract.py`, and
`test_unreadable_import.py` verified to fail on `5422dcbd` (`12 failed, 123 passed`) and pass
after (`135 passed`; `257 passed` across 8 retention/capture/provenance files). PR 211 body updated.
Remaining: independent review, merge PR 211, and batch the definition change with the
recording-match PR under one cause record (follow-up `ct-5c98` removes capture storage from
the model definition hash).

## Definition change

This is a model definition change (body_store.py is hashed since PR 203). Batch
it with the recording-match PR under one cause record.

## Notes

**2026-11-18T22:23:06Z**

Implemented all three PR 211 review fixes: (1) restricted confirm-then-replay to content-addressed bodies (BODY keys) in R2Adapter.create and explicitly frozen receipts in ReceiptWriter._apply_frozen/_settled, keeping ordinary receipt and provenance creates un-reconciled with 412 collisions raising RawNameCollision; (2) restricted R2Adapter.head absence to 404/NoSuchKey and distinguished absent from failed HEAD in reconcile_create so persistent HEAD failures raise the original error without replaying; (3) added thread-safe ReconcileBudget (RECONCILE_BUDGET_SECONDS = 66s per writer alongside SETTLE_SECONDS = (0, 2, 5, 15) = 22s per object) shared across R2Adapter, BodyStore, and ReceiptWriter. Planted tests failed on 5422dcbd (12 failed, 123 passed) and pass after (135 passed across test_body_store_contract.py, test_receipt_writer_contract.py, test_unreadable_import.py).

**2026-11-21T21:03:00Z**

Merged PR #211 (`5bbe8cf7`) after independent read-only review approved all scope, 404-only absence, and wait-budget bounds. Verified `.github/scripts/definition-change.py` reports zero model definition changes (`ct-5c98` already decoupled capture storage), so unattended nightly publishes remain unaffected.
