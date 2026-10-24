---
id: ct-vp92
status: closed
deps: []
links: []
created: 2026-10-18T19:21:16Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Stage review assets atomically

filename_reviews.py extracts into the final asset directory before verifying it. stage-document-reviews.py treats an existing directory as complete and only verifies it, so interrupted extraction can leave future builds stuck until manual cleanup.

Source: apps/site/scripts/filename_reviews.py:81-96; apps/site/scripts/stage-document-reviews.py:11-12.

## Acceptance Criteria

Extract and verify in an owned temporary directory, then atomically publish it. Inject interrupted extraction and invalid archive contents; the next build recovers, and an existing valid directory remains intact.

<!-- grade-followup:start -->
## Grade review follow-up

Include stale descriptor versus corrupt cache handling and warm-build verification in atomic evidence installation.

- Interrupted/invalid staging never replaces a valid tree and can retry without manual cleanup.
- Changed descriptor installs only a fully verified replacement; a reused tree is still pinned to verified bytes.

[Function scope and checks: 2 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:631). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:10:35Z**

Implemented sibling temporary extraction, full verification before replacement, rollback on install failure, warm-cache verification and repair of stale/corrupt caches. Focused tests inject extraction interruption and retry; 29 review/recovery tests passed.

**2026-10-18T20:12:04Z**

Review correction: portable directory replacement uses two renames, so installation now holds a writer lock and retains the prior tree at a deterministic sibling across the gap. Next stage restores it after process death. Added install-rename failure, modeled process-death gap, and changed-descriptor replacement tests; all 7 asset tests pass. Each installed tree is fully verified; the swap has a recoverable brief absence rather than claiming one atomic replacement of a nonempty directory.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch d8z3b).
- Grades: proposal 90 → 84, work 90 → 84.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
