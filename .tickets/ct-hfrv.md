---
id: ct-hfrv
status: closed
deps: []
links: [ct-l3s4, ct-p6ns, ct-kde5, ct-15wc]
created: 2026-10-18T19:21:16Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Make viewer requests recover after worker failure

After the catalog has loaded, filename-bootstrap.mjs rejects pending calls on worker.onerror but keeps accepting new calls on the same worker. Search/detail retries can remain pending indefinitely. Initial-load UI retry already reloads the page.

Source: apps/site/src/components/filename-bootstrap.mjs:21-28; docs/youtube-coverage/research/filename-viewer.mjs:633.

## Acceptance Criteria

Simulate worker failure after initialization. Pending and later requests settle with a clear error or use a restarted worker; retry succeeds without an indefinite spinner. Retain the existing startup reload behavior.

<!-- grade-followup:start -->
## Grade review follow-up

Extend the existing terminal/restart fix to request/postMessage exception cleanup, real bootstrap/worker integration and startup/deep-link/history readiness. Keep initial-load Reload behavior.

- Every registered request settles once and removes pending/listener state after result, error, cancellation or a throwing postMessage.
- Startup and post-info failure, successful retry/restart, late canceled result, actual worker routes and a pending-info popstate are covered.

[Function scope and checks: 10 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:383). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:12:01Z**

Request cleanup/restart, actual worker routes and latest pending-info history implemented with focused tests. Awaiting root-owned built Pages bootstrap smoke before closing the full follow-up acceptance.

**2026-10-18T20:15:32Z**

Root independently ran the emitted Pages bootstrap/UI smoke after the merged first batch: real bundle under /congressional-tech/, pinned local review archive, 29-page build passed. This completes the built-bootstrap follow-up alongside the focused actual-worker/client/history tests.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch d8z3a).
- Grades: proposal 90 → 90, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
