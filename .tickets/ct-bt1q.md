---
id: ct-bt1q
status: open
deps: [ct-copj]
links: []
created: 2026-10-20T19:13:35Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, rust, recovery]
---
# Drain an owned DocSpec host when its Python owner exits abruptly

A persistent serve child can survive Python SIGKILL because finalizers cannot run. Add optional stdin-EOF shutdown for explicitly owned hosts and reuse normal HTTP stop and Engine.shutdown draining. Preserve producer files and admitted work; no parent polling or automatic recovery cleanup.

## Acceptance Criteria

Actual child-owner kill closes the inherited pipe, stops new intake and allows admitted work to drain or retain its acknowledged recovery state. Ordinary manually operated serve behavior remains unchanged. Local process tests and independent review; no production runtime replacement.

