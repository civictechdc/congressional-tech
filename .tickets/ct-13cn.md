---
id: ct-13cn
status: open
deps: [ct-q968, ct-3180]
links: []
created: 2026-10-20T18:24:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Support native version comparisons for R2-backed data

Reuse DocSpec `compare`/`changes` (`POST /datasets/{dataset}/changes` and CLI `compare`/`changes` added for remote `source` groups in `docspec-rs` commit `b240765`) for a concrete diagnostic consumer in `congressional-tech` after isolated R2 provider qualification (`ct-3180`) and persistent host transport (`ct-q968`) complete. Preserve duplicate multiplicities, null semantics and exact pinned versions.

## Acceptance Criteria

- Expose `compare` and streaming `changes` on `NativeDatasets` (`packages/congress_api/src/congress_api/retention/docspec.py`) using the persistent loopback host (`POST /datasets/{dataset}/changes` and `ArrowResponse` stream framing) without staging temporary Arrow files.
- Wire one concrete diagnostic consumer and qualify against an independent multiset reference on both local and isolated R2 fixtures.
- Report reads, returned IPC bytes, and elapsed time; never treat metadata equality as semantic equality.

## Notes

**2026-10-20T18:35:21Z**

User explicitly authorized extending DocSpec-rs itself for R2 support on2026-10-20. Implement in isolated native worktrees, qualify locally before isolated provider tests, preserve production data and mappings. Backend refusal is a dependency to solve, not grounds for closing this ticket as deferred.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit note: native remote `source`-group comparison and change streaming landed on `docspec-rs` `main` (`b240765`). Once `ct-3180` completes isolated R2 provider qualification and `ct-q968` lands, wire the Python diagnostic consumer through `NativeDatasets` + `ArrowResponse`.
