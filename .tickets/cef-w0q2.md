---
id: cef-w0q2
status: closed
deps: []
links: []
created: 2026-10-27T18:57:22Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine-first, C5]
---
# C5: forward explicit remote connections through native SQL jobs

## Acceptance Criteria

NativeDatasets.run_job forwards approved remote configuration and only its named secrets to the same verified executable, preserving local behavior and completed-failure identity. No separate application joins or fallback.


## Notes

**2026-10-27T19:08:33Z**

Client remote-job forwarding completed0a99aeb5; all15 client-package fixtures pass. DS C5read/startup CODE and ARCH both APPROVE b9ea2ec plus this client binding. Explicit named environment forwarding only; no lifecycle or Python data movement added. Root runner still requires local-only runtime for production-offline. No live remote job run.
