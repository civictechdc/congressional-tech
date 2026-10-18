---
id: ct-pd8n
status: closed
deps: []
links: [ct-1mbc]
created: 2026-10-18T19:25:05Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Preserve upload and reconciliation failure diagnostics

When PUT fails and the reconciliation GET also fails, the second exception can hide the original request failure. That obscures whether an upload may have succeeded.

Source: scripts/guarded_recovery_publication_client.py:125-145.

## Acceptance Criteria

Keep both failures in the raised diagnostic using explicit exception chaining or a structured error. Preserve object/attempt identity without credentials, fail closed, and do not resend automatically. Cover a PUT failure followed by a GET failure.

<!-- grade-followup:start -->
## Grade review follow-up

GuardedPublicationClient.put_object dual failure.

- Retain original PUT plus reconciliation error with key/attempt context and no credentials. Assert no repeated PUT, no verified receipt and unchanged strict definite-conflict handling.

[Function scope and checks: 1 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:565). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:11:48Z**

Structured dual failure preserves original PUT and reconciliation exception objects, credential-free type/context diagnostic, explicit chained original cause. Tests assert one PUT, intent only, no proof and no verified event.
