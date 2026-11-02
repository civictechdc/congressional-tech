---
id: ct-egg6
status: open
deps: []
links: [ct-xls0]
created: 2026-11-02T00:58:34Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [parser, senate, phase2]
---
# Admit root-slug Senate hearing links at senate_page.py's next re-version

34 Senate listing rows have root-slug links that miss HEARING_LINK (a1705b6f). A fallback fetching them was removed after review: of 33 targets, 5 pages exist, 21 return 404 and 7 return 403, and one 403 failed the host run. The 5 live pages are Appropriations hearings. senate_page.py is byte-hashed, so batch this with the next version move.

## Acceptance Criteria

The 5 live pages become meetings with correct dates, the rest have a recorded reason, and a failed fetch cannot fail the whole run.


## Notes

**2026-11-02T04:01:45Z**

Code on worktree-agent-ae42a8cf7a429ba24 @ 180a49b1. Review verdict: merge. 5 live pages match raw rows and bodies. Gap filed as ct-xls0.
