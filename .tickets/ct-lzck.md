---
id: ct-lzck
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
# Close verifier failures and expose local uncertain writes

open_public raises terminal HTTPError responses without closing them. pipeline_status returns unbound local continuations before showing uncertain writes.

## Acceptance Criteria

Close every HTTPError response without changing retry statuses/delays. Show bounded local write uncertainty without accepting outputs or granting remote authority; malformed write records remain rejected.

## Notes

**2026-10-19T16:41:56Z**

Implemented terminal HTTPError closure and bounded local write summaries before attribution. Bound/unbound malformed records, count/key limits and unchanged retry/body-failure semantics covered; focused Python suite: 73 passed. Awaiting independent review; ticket remains in progress.

**2026-10-19T16:47:44Z**

Independent review approved e9b5483. Focused local failure, custody and selector-route tests passed; exact logs checked. Larger accepted-plan ownership stays open in ct-bpyj. Integrated offline verification follows in ct-us67.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch syem).
- Grades: proposal 86 → 86, work 88 → 88.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
