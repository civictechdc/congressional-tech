---
id: ct-hbxu
status: closed
deps: []
links: [ct-dpks, ct-kde5]
created: 2026-10-18T19:28:38Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Use locked dependencies and declared runtimes for Pages

Pages uses unlocked pip installs and npm install with several version ranges; package-lock.json is globally ignored. Python 3.12 and Node 22 select release lines rather than exact patches. A clean build can therefore resolve a different graph.

Source: .github/workflows/deploy-pages.yml:45-76; apps/site/package.json; .gitignore:373.

## Acceptance Criteria

Use the maintained Python lock/setup policy and a committed site lock with a frozen install. Declare the tested runtimes and run the maintained filename-reader checks before build. Clean installs must reproduce dependency identities; stale locks must fail without rewriting them. Preserve the adjacent Explorer and review-staging checks.

<!-- grade-followup:start -->
## Grade review follow-up

Add built filename-page smoke coverage and explicit verified Explorer/review inputs to reproducible setup; preserve shared-site assets and their verification.

- Frozen installs reproduce identities without changing lockfiles; declared runtime is used by maintained reader checks.
- A built page runs the real bootstrap under the Pages base path.
- Document the shared Explorer copy/migration prerequisite; change deployment independence only against an explicit product requirement, not to evade validation.

[Function scope and checks: 3 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:373). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:15:32Z**

Implemented site lock/frozen install, exact Node/npm and shared locked Python setup; maintained reader suite and actual built bootstrap smoke run in CI. Two clean installs preserved lock; deliberately stale lock refused unchanged. 29-page build with verified local review archive and built bootstrap passed; 6 workflow/budget checks passed. Independent review fixed module deployment triggers. Local Explorer data prerequisite is absent and still fails verification; no deployment claim. Evidence: docs/experiments/publication-remediation/pages.md.

**2026-10-18T20:42:25Z**

Final integration found publication tests depended on another test modifying sys.path. pytest.ini now declares scripts and apps/site/scripts explicitly; the continuation-state file passes independently without an ambient PYTHONPATH.

**2026-10-18T21:48:15Z**

Reopened after hosted Pages run 39169129664 failed before deployment: npm10.9.7 self-upgrade to11.19.1 removed promise-retry while the running old Arborist lazily required it during reify finish. Logs preserved under primary output/publication-remediation-20261018/rollout/pages-failure-39169129664.*. Repair isolated npm runtime installation and make validation exercise the same setup. No workflow retry or resource change.

**2026-10-18T21:55:09Z**

Repair implemented in f18288e with docs clarification2432891 and independently approved. Isolated old npm copy reproduces the hosted failure; fresh-prefix pinned npm installation, frozen install, unchanged lockfiles and stale-lock refusal pass. 48 workflow checks and 152 reader tests pass. Shared Node setup now used by Pages and PR validation. Keeping this ticket in progress until the normal changed-code Pages run confirms hosted setup and deployment.

**2026-10-18T22:05:34Z**

Hosted Pages run 39169960167 on c326ce24 succeeded: frozen Node setup, 152 filename-reader/build-smoke checks and deployment completed 2026-10-18T21:58:45Z. https://github.com/civictechdc/congressional-tech/actions/runs/39169960167 . This is hosted Pages evidence; separate viewer-publication preparation remains unqualified until its own checks complete.
**2026-10-18T22:19:32Z**

Reopened for a separate hosted dispatch race: Explorer run39169129652 finished from dbfe and dispatched the current Pages workflow with the older code_revision. Run39170982908 failed because that checkout lacks the current setup-node-project action. Existing successful c326 deployment remains live. Gate dispatches before checkout so site code and workflow revision agree; retain mismatched inputs/reason. No retry or resource change.

**2026-10-18T22:25:28Z**

Revision guard independently reviewed in547a5ca and squash merged PR116 as2a065cd. All49 Pages dependency/raw-workflow checks pass; exact mismatched-revision receipt executes without checkout. Normal hosted run39171844028 on2a065cd then built and deployed successfully; mismatch-only job correctly skipped on the main push. No stale dispatch was manually retried. Earlier failure and successful deployment evidence retained in primary rollout/pages-{failure-39170982908,success-39171844028}.*.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch d8z3a).
- Grades: proposal 87 → 87, work 83 → 83.
- Problem: `.gitignore:373` still ignores `/package-lock.json`. The site lock is force-tracked, and a root `package-lock.json` sits untracked on disk.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/d8z3a/d8z3a-verdicts.md:90
- Covered by: plan section 4 (keep the Pages lock files; give the npm pin one owner when Pages is next touched).
- See docs/reviews/2026-10-24-ticket-audit/README.md
