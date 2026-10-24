---
id: ct-tenb
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
# Confine restored publication phase files to their attempt

Restored non-inventory phases hash saved paths without the confinement check used for new phases. A matching external symlink can escape owned storage.

## Acceptance Criteria

Reject file and parent symlink escapes before hashing or accepting restored outputs. Preserve matching owned files, issued inventory reuse and existing digest checks.

## Notes

**2026-10-19T16:43:22Z**

Restored non-inventory phase files now repeat file-symlink/resolved-root confinement before hashing. Matching owned files and digest refusal remain covered; file/parent symlink escapes refuse before hashing or checkpoint changes. State/continuation/attempt regression suite: 60 passed. Awaiting independent review; ticket remains in progress.

**2026-10-19T16:47:44Z**

Independent review approved e9b5483. Focused local failure, custody and selector-route tests passed; exact logs checked. Larger accepted-plan ownership stays open in ct-bpyj. Integrated offline verification follows in ct-us67.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch syem).
- Grades: proposal 83 → 83, work 87 → 87.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
