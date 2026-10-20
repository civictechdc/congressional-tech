---
id: ct-copj
status: closed
deps: []
links: []
created: 2026-10-20T18:37:15Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, rust, transport]
---
# Preserve bounded request deadlines in the native HTTP path

Persistent HTTP removes subprocess overhead, but socket read timeouts do not preserve the old aggregate request deadline. Investigate supported native HTTP cancellation/deadlines and a trustworthy bound-listener readiness handshake. Keep the adapter thin and native recovery state intact.

## Acceptance Criteria

Stalled and slow-progressing metadata/Arrow requests stop within the documented request bound; partial Arrow cannot succeed; native retained completion remains recoverable and other host users stay safe. Use maintained async/HTTP primitives, no private socket internals, automatic retries or weakened pin checks. Local native/client regression tests and independent review.

## Notes

**2026-10-20T19:20:19Z**

Native commit9876858888a59fe35029def79ad34b85bd72bf3a passed full local gate and independent static review. Frozen candidate f6699cd6927ad3935abbd9a29cf59d18ea4a655da7e547eb0288f3980705751a. Receipt output/docspec-reuse-20261020/native-http/independent-review.json. Implementation locally complete; runtime adoption is ct-oxg6 and forced owner-exit draining is ct-bt1q.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit validated native commit `9876858` (merged to `docspec-rs` `main` as `911228d`) and Python `ArrowResponse` framing/deadline enforcement (`docspec_host.py:145-171,236-278`). Grade: A.
