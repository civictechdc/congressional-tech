---
id: ct-bt1q
status: closed
deps: [ct-copj]
links: [ct-q968, ct-egpe, ct-3faj]
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

## Notes

**2026-10-20T20:05:15Z**

Local review heads: native470fec3939c9d49f4afeb3c47bd3b79a60faa738 and app e95ff7697d85c28e1b9614cbff23ff522cdcde5c. Optional serve --shutdown-on-stdin-eof uses one process-owned reader -> existing graceful intake stop -> Engine.shutdown drain; Python owns a private stdin pipe, requires owned-stdin-eof capability, and closes the pipe on last release. Actual c44bf/f669 orphan runtime red reproduced; new actual owner SIGKILL idle/admitted cases pass, including paused drain and exact recovery after producer loss. Native full scripts/check pass (350library,318integration,15restore,2initialization); fresh app related159pass. Frozen local candidate SHA256718c95bcb7f8516f173c986127fe5b5a267a13fb0c179fca6e2c088ecdfe7b64. Manual serve and producer cleanup unchanged; extra inherited write ends delay EOF, stalled admitted work can prolong draining, and tiny caller-owned readiness metadata can remain after abrupt owner death. Evidence: output/docspec-reuse-20261020/owner-lifetime/receipt.md and logs. Leave in_progress for independent review; no production binary/config replacement.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit independently reviewed and approved native commit `470fec3` (now on `docspec-rs` `main` as `2308d23`, `src/engine/http.rs:173-238`, `src/main.rs:289-302`) and application commit `e95ff769` (`docspec_host.py:76-120,203-205`, `tests/test_docspec_owner_lifetime.py`). Grade: A−. Using a dedicated std thread + Tokio oneshot avoids Tokio's non-cancelable blocking stdin read on normal SIGINT while guaranteeing kernel pipe EOF on parent `SIGKILL`. Closed after independent review; binary freeze and integration remain under `ct-oxg6` and `ct-nc7l`.
