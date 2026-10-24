---
id: ct-qspb
status: closed
deps: []
links: []
created: 2026-10-18T19:25:05Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Use one canonical recovery body-key validator

accepted_rows() validates body-key shape but does not require the shard directory to match the digest prefix. filename_aliases.valid_body() already checks both. A malformed accepted row can reach a sidecar whose saved-copy mapping the browser rejects.

Source: apps/site/scripts/filename_recoveries.py:15-32; apps/site/scripts/filename_aliases.py:42-44.

## Acceptance Criteria

Reuse the canonical validator at acceptance. Reject a shape-valid wrong-shard key before durable mapping writes. Preserve supported kinds, bases, URL checks and current valid mappings; add a focused wrong-prefix case.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 1 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:573). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:10:35Z**

accepted_rows now reuses filename_aliases.valid_body, including digest-prefix shard check. Focused wrong-prefix test passes with existing URL/kind/basis/alias behavior.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch d8z3b).
- Grades: proposal 93 → 95, work 95 → 95.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
