---
id: ct-kde5
status: closed
deps: []
links: [ct-hbxu, ct-hfrv]
created: 2026-10-18T19:44:02Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Make shared viewer markup and data adapters explicit

Production Astro extracts HTML by exact regex delimiters while shared UI contains public-worker and local-server branches. Establish a reusable explicit markup boundary and small adapter boundaries for API, evidence links and optional local naming comparison. Preserve both currently supported routes; do not remove historical/local support merely to raise a grade.

## Acceptance Criteria

- Built Pages view uses correct base path and actual worker; no production /api or /review-evidence HTTP fallback.
- Local research route retains supported API/evidence/comparison behavior; published view still avoids rerunning naming rules.
- Markup smoke checks preserve accessible controls and script/style ordering no longer depends on fragile delimiters.

<!-- grade-followup:start -->
## Grade review follow-up

Apply the existing acceptance criteria to the specific functions and checks in the coverage map.

[Function scope and checks: 6 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:456). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:31:27Z**

Explicit body/CSS artifacts and published/local adapters implemented; local HTTP/module integration and41Python viewer checks passed;144maintainedJS checks,29-page build and2actual emitted bootstrap scenarios passed under explicitNode22.21.1/npm11.19.1. Kept in_progress pending root Node22.22.2 supported-engine verification. Added publicmode UI and compressed/CORS review-admission fixtures; see browser.md for honest runtime boundary.

**2026-10-18T20:33:44Z**

Supported-runtime final proof complete: explicit Node22.22.2/npm11.19.1 engine-strict frozeninstall;146maintainedJS,41Pythonviewer,19explicit-worktree-package catalog/worker checks passed;29-pagebuild+2actualemittedbootstraps(pinneddeep link included) passed. Final code/lock/bundle identities saved evidence/browser-final.json. Root independently reviewed prior UI; ready final adapter review/integration.

**2026-10-18T21:07:54Z**

Final suite integration classifies the real localhost HTTP/module-serving check as loopback; it passes separately. The production-offline lane keeps its socket prohibition. This changes test enrollment, not application behavior.

## Audit 2026-10-24

- Verdict: SUPERSEDED (batch d8z3b).
- Grades: proposal 74 → 68, work 75 → 68.
- Problem: The ticket said to preserve the local route. A later ticket deliberately removed its UI.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/d8z3b/d8z3b-verdicts.md:19
- Covered by: WS11 (ct-2wsw).
- See docs/reviews/2026-10-24-ticket-audit/README.md
