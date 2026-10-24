---
id: ct-xmo8
status: closed
deps: [ct-2d3k]
links: []
created: 2026-10-19T16:35:49Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-d3un
tags: [overlap-rescore]
---
# Keep browser retries on the accepted catalog

An ordinary reader starts with no explicit snapshot; after worker failure it can resolve a newer mutable pointer while the page retains old metadata.

## Acceptance Criteria

Pin the first accepted catalog for later requests and worker recreation. Preserve explicit selections and cancellation. Local tests cover pointer advance, failure, retry and conflicting responses.

## Notes

**2026-10-19T16:44:44Z**

Implemented first accepted valid catalog pin inside the request client. Ordinary retries keep that catalog after worker recreation; explicit snapshots remain fixed, conflicting replies reject, and aborted/stale replies cannot pin. New regressions fail on the original client (3 failures) and pass after correction. Local 104 reader/UI checks, 29-page build with retained verified review assets, and 2 emitted-bootstrap cases passed under Node 22.22.2. Logs: primary output/package-overlap-rescore-20261019/browser-package-*. Ticket remains in progress pending independent review.

**2026-10-19T16:49:05Z**

Independent review approved 0a9d0d5. Passed 104 JS, 88 body-key/evidence, 25 CSV/GPO checks, frozen Node/npm install, 29-page build and 2 emitted-bootstrap scenarios. Integrated offline verification follows in ct-us67.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch syem).
- Grades: proposal 90 → 90, work 91 → 91.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
