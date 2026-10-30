---
id: ct-syem
status: open
deps: []
links: [ss-yjut, ct-uov2]
created: 2026-10-22T17:33:29Z
type: epic
priority: 1
assignee: mikewolfd
tags: [audit, architecture, hygiene, dx, docspec]
---
# CS300 Capstone Audit: congressional-tech deadcode, bloat, duplication, DX, comments & code smells

Parent epic tracking findings from the 13-subagent CS300 Capstone Code Quality Audit across `congressional-tech` (**Overall Repo Grade: C+, 75.4 / 100**).

## CS300 Subsystem Grades & Child Tickets

| Subsystem | Auditor Role | Grade | Child Tickets |
| :--- | :--- | :---: | :--- |
| **`packages/docspec_client` & Cross-Repo DocSpec Boundary** | DocSpec Client & Boundary Auditor | **C- (71/100)** | `ct-0n0y` (P0 bug), `ct-4fcl` |
| **`packages/congress_api`, `packages/congress_shared` & `packages/source-fetch`** | Congress API & Shared Auditor | **C+ (78/100)** | `ct-imdo` (P1 bug), `ct-fsbf` |
| **`packages/corpus_recovery`, `packages/viewer_publication` & `packages/news_lake`** | Corpus, Viewer & News Lake Auditor | **C+ (78/100)** | `ct-0bce`, `ct-wxhg` |
| **`packages/committee_meeting`, `packages/house-naming` & `packages/youtube_api`** | Committee, Naming & YouTube Auditor | **C+ (78/100)** | `ct-ne06`, `ct-tcs4`, `ct-elhm` |
| **`apps/site`, `apps/committee_youtube`, `apps/inflation_gsheets` & `infra/`** | Apps, Frontend & Infra Auditor | **C+ (78/100)** | `ct-3bfx` (P0 bug), `ct-4g55` |
| **Root `scripts/`, Root `tests/`, Workspace Config & Repo Hygiene** | Scripts, Root Tests & DX Auditor | **C- (71/100)** | `ct-unv0` (P0 bug), `ct-sbdp` |
| **Quantitative AST & Static Metrics (`congressional-tech` Slice)** | Quantitative AST & Metrics Auditor | **C (73/100)** | `ct-bzl9` |

## Acceptance Criteria

1. All P0/P1 runtime, cache-poisoning, and test-runner bugs (`ct-0n0y`, `ct-unv0`, `ct-3bfx`, `ct-imdo`) are fixed and verified by automated tests.
2. All P1/P2 architectural decomposition, circular-import removal, dead-code purging, DRY consolidation, un-minification, and repo hygiene tickets (`ct-4fcl`, `ct-fsbf`, `ct-0bce`, `ct-wxhg`, `ct-ne06`, `ct-tcs4`, `ct-elhm`, `ct-4g55`, `ct-sbdp`, `ct-bzl9`) are resolved and verified by `.venv/bin/python scripts/dev.py check`.

## Audit 2026-10-24

- Verdict: PARTIAL (batch syem).
- Grades: proposal 68 → 68, work 60 → 60.
- Problem: AC1 ("P0/P1 fixed and verified by automated tests"): ct-imdo's fixes have no tests (no test references `congress_shared.dates` or auth argv handling).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/syem/syem-verdicts.md:94
- Status: Reopened, because its children ct-0bce and ct-4fcl are reopened; it closes when they do. Its gate (`scripts/dev.py check`) runs no tests; WS12 (ct-uov2) makes the gate `scripts/dev.py test` on the merged revision. The shims it left go with WS10 (ct-r6xw).
- See docs/reviews/2026-10-24-ticket-audit/README.md

## Notes

**2026-10-30T17:48:00Z**

ct-4fcl, ct-r6xw, and ct-uov2 are completed and closed (and docspec.py/docspec_host.py shims deleted in 176cd4a1). Kept open per WS12 Rule 1 solely for the parked news_lake child ct-0bce (deferred per user decision A4).
