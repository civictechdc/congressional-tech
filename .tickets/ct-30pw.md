---
id: ct-30pw
status: closed
deps: []
links: []
created: 2026-10-19T22:31:31Z
type: task
priority: 1
assignee: mikewolfd
tags: [efficiency, publication]
---
# Reduce remote publication journal requests

Reduce remote journal round trips while preserving original write conditions, pre-write intent, concurrent attempt fencing, and recovery after uncertain commits. Keep the supported path simple.

## Acceptance Criteria

Matched local request/byte counts and payload parity; focused interruption, lost-acknowledgment and concurrency tests; independent review. No production writes or workflow runs.

## Notes

**2026-10-19T22:36:15Z**

Implementation frozen at 2672fe9480769ba7d0847534720b6185cb444153. One pending verified fact joins the next durable intent/completion/failure record; exact original conditions, nonce/digest chain, pre-mutation conditional intent, full payload readback and concurrent sequence fence remain. Exact-source baseline 74 tests; candidate 87 tests. Matched six-worker tiny fixture: GET833→724, PUT821→712, HEAD270 unchanged; full read bytes319614→300311, PUT bytes315587→296284; all269 payload files byte-identical and strict recovery comparison passes. Evidence docs/experiments/efficiency-round-two/remote.md and remote-evidence.json; primary raw receipts output/efficiency-round-two-20261019/remote. Independent review pending through integration owner; no remote writes/workflows.

**2026-10-19T22:38:08Z**

Independent review approved 5490e53 (runtime 2672fe9). Six-worker fixture removes 109 journal PUT/readback pairs; all payload and recovery values match. 74 baseline/87 final checks; combined 139 pass. Conditional intents and full payload readback remain. Evidence: docs/experiments/efficiency-round-two/remote.md.
