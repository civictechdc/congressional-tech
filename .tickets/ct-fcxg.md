---
id: ct-fcxg
status: closed
deps: []
links: [ct-1mbc]
created: 2026-10-18T19:26:50Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Report publication verification in one read-only command

pipeline_status reports the raw run and accepted phases but deliberately leaves downstream publication and public readback unchecked. Operators currently assemble run IDs, manifest pins, review counts and live-loader proof manually.

Source: scripts/pipeline_status.py:164-197; output/session-continuation-20261018/continuation.json.

## Acceptance Criteria

Add an explicit read-only verification mode that links raw output, viewer selection, Pages/runtime compatibility and live review loading by exact identities. Emit a durable receipt separating passed, pending and failed checks. Use bounded verified catalog reads for category differences; report withdrawn reasons. Never publish, retry, reinstate reviews or call a run complete from metadata alone.

<!-- grade-followup:start -->
## Grade review follow-up

Include local recovery phase state and pipeline_status.continuation; distinguish remote reconciliation from artifact acceptance.

- Report exact incomplete phase and reconciliation steps without performing mutation or treating local accepted outputs as live publication.

[Function scope and checks: 2 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:318). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:34:55Z**

Added pipeline_status --verify-publication with durable passed/pending/failed receipt, exact run-output raw-selector pin vs current/saved raw freshness, maintained public review/recovery loader, verified binding withdrawals, Pages asset hashes and optional actual deployed Chromium worker API identity checks. Category deltas fully hash supported <=32MiB document table then project document_id+3classification columns in256row batches; larger tables pending before download. Status distinguishes next local phase/uncertain writes/recorded verification from remote reconciliation.24Python+4Node fixture tests passed; no production completion claim or mutation.

**2026-10-18T20:36:11Z**

Independent review fix: decoded gzip and CORS-hidden encoding no longer compare actual decoded length to encoded Content-Length; bounded wrapper normalizes headers for maintained loaders after full byte counting. Declared-limit and non-success refusals cancel body before reading.24Python+6Node tests passed incl encoded/CORS regression and cancellation. Holding in_progress for root review before final closure.

**2026-10-18T20:36:40Z**

Independent review fixed compressed HTTP response length handling and response cancellation. Final patch reviewed with 24 Python and six Node controlled checks passing; receipt keeps unavailable or oversized live checks pending.
