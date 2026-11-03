---
id: ct-d0o0
status: closed
deps: []
links: [ct-77zb, cef-nkzp, ct-h1nd, ct-sh4j, cefr-7sar, ct-kac4, ct-v8y0, ct-mrgt, cef-96wc, ct-n2cy, ct-tk10, ct-qg8e]
created: 2026-11-01T17:43:18Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [testing, datafusion, captures, committees, phase2]
---
# Add offline gates for the fb408404 receipt lines, committee code mapping and three model query plans

Catch the failures found during publish_v21 in production-offline. Reshaped after independent review: "every distinct envelope shape" has no fixed answer (3, 729 or 12,188 depending on the definition, and the 729 had not saturated), and a static SQL guard flagged 27 of 31 statements while the old failing queries passed alone.

## Design

1. Fixture of the receipt lines fb408404 actually concerns, with per-line expected rows derived from raw facts rather than guard parity, because the guard cannot see wrong in-domain values.
2. A checked-in script reports fixture paths against a mapper path list, so coverage gaps are visible.
3. EXPLAIN assertions that the candidate join sits below the aggregate on the three named steps, through run_job.
4. Check committee mapping against committee-codes.json only. The release has 51 hl/ht codes and 20+ stems outside _HOUSE_SELECT_CODES, so testing against it fails at HEAD. Keep missing_committee_keys as the real gate.

## Acceptance Criteria

- Runs within 30s on the pinned runtime.
- Reverting the fb408404 behavior, removing a mapped code, or removing a candidate join fails the gate.
- The original memory failure needs a full job; this gate does not claim to detect shared-pool pressure.


## Notes

**2026-11-02T04:01:45Z**

Code on worktree-agent-a5550c04138214670 @ b3c4aa3c. Review verdict: merge and close once merged. Follow-up: ct-mrgt.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
