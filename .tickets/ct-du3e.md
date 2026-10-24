---
id: ct-du3e
status: closed
deps: [ct-2d3k]
links: []
created: 2026-10-19T16:38:43Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-d3un
tags: [overlap-rescore]
---
# Keep proposed catalog selectors distinct until verified commit

The local recovery Store saves candidate selector bytes under the selected source path before conditional upload succeeds. A refusal leaves misleading local evidence.

## Acceptance Criteria

Retain a separately named proposal before the write. Preserve prior selected bytes on refusal or uncertainty, and install the new selected receipt only after verified success. Keep original conditions and no automatic retry.

## Notes

**2026-10-19T16:43:22Z**

Local Store retains proposed/indexes/catalog.json before the original conditional write and installs source/indexes/catalog.json only after verified storage success. Actual guarded Store tests cover condition refusal, uncommitted uncertainty, committed readback failure, success and lost-ack reconciliation; one PUT each, selected bytes unchanged through readback, proposal retained. Dispatcher/guard/mapping suite: 39 passed plus 5 subtests. Awaiting independent review; ticket remains in progress.

**2026-10-19T16:47:44Z**

Independent review approved e9b5483. Focused local failure, custody and selector-route tests passed; exact logs checked. Larger accepted-plan ownership stays open in ct-bpyj. Integrated offline verification follows in ct-us67.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch syem).
- Grades: proposal 84 → 84, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
