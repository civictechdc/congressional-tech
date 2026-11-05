---
id: ct-syem
status: closed
deps: []
links: [ss-yjut, ct-uov2, ct-d8cf]
created: 2026-10-22T17:33:29Z
type: epic
priority: 1
assignee: mikewolfd
tags: [audit, architecture, hygiene, dx, docspec]
---

# Verify shared date-helper behavior when a parser changes

Closed as satisfied on November 5. Existing caller tests cover the two requested timestamp behaviors, and retained passing lane results apply to the unchanged code. The earlier finding looked only at an import smoke test and missed these assertions. No new implementation or test run was needed for this closure.

## Acceptance Criteria

- [x] Record behavior for UTC conversion across a calendar-day boundary and refusal of timezone-less input through an affected caller.
- [x] Retain the existing auth evidence and completed audit history.

## Closure evidence

- `packages/youtube_api/tests/test_youtube_interpretation.py:39–53` converts `2024-12-31T23:00:00-05:00` to `2025-01-01 04:00 UTC` and keeps timezone-less input unknown through the real helper caller. `packages/congress_api/tests/test_congress_api_transcripts_refactor.py:8–21` also covers offsets, daylight-saving boundaries and timezone-less refusal.
- All three `production-offline` shards passed at `7f9ebddd2cb632f97bc0214ffd44beaf72b0a5a6`: 11,497 tests passed in total. Retained results: `.cache/archive-release/handoffs/cursor-resume-20261105/qualification-7f9ebddd2cb6/combined-results.json`. The lane includes the caller tests; none of these cases is skipped or expected to fail. The relevant packages, tests, runner and suite configuration have no changes from that revision to `c3ee2eec`. This is reuse of whole-lane evidence, not a separately rerun test.
- Auth argument and credential-precedence assertions remain in `test_shared_command_setup.py:158–179`. Keep `ct-imdo`'s policy to check changed parser behavior with the next relevant edit. News Lake remains owned by `ct-d8cf`; it does not keep this completed audit open.

[Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

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

**2026-11-05T17:11:15Z**

Scope reconciliation 2026-11-05: keep open for the remaining dates-helper behavioral evidence. Auth argument and CLI/env/files precedence tests exist in test_shared_command_setup.py:158–179, so the old blanket no-auth-tests finding is superseded. The date smoke at :32–43 only imports the module; UTC conversion across a day boundary and timezone-less-input refusal remain unproven as direct behavior. ct-imdo records deferral to the next relevant parser edit. Keep this explicit residual here until it has that verification or an owner disposition; do not reopen all completed audit children. ct-0bce's remaining backend work now belongs to ct-d8cf.

**2026-11-05T20:18:16Z**

Closed as satisfied: actual caller assertions and retained all-shard production-offline results establish both date criteria on unchanged code. No tests rerun. Preserve ct-imdo policy and ct-d8cf ownership. [Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).
