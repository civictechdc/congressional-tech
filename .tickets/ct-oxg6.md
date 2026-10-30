---
id: ct-oxg6
status: open
deps: [ct-3faj, ct-q968, ct-3li2, ct-cpio, ct-bt1q]
links: [ct-ugqq, ct-cpio, ct-xl0y, ct-3li2, ct-xq1y, ct-5fkx, ct-tw3r, ct-l9g0]
created: 2026-10-20T18:47:06Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, qualification]
---
# Pin and qualify one upgraded DocSpec runtime for application callers

Freeze one reviewed native source revision and immutable binary for congressional-tech. Verify the core host and exact-version source profile; record optional feature and local/R2 support separately so unavailable extensions do not masquerade as adoption.

## Acceptance Criteria

- Before freezing, verify the chosen source contains the ct-3li2 nested-export safety fix and ct-cpio caller-budget/writer cleanup with exact-head evidence. These are mandatory safety prerequisites, not optional capability checks.
- Record source commit, lock/build features, platform, binary digest and runtime configuration identity; no mutable target/debug default.
- Exercise readiness, deadlines, owned-host shutdown, uncertain producer retention, exact source pins and nested/unsigned round trips through the maintained app adapter.
- Record a capability matrix for schema/backfill, evidence, related refresh, compare/changes, export, generations and maintenance on the intended backend; native route presence or old tests alone are insufficient.
- Preserve the existing production workspace, credentials, pending operation and selectors. Qualification uses an isolated runtime and does not restart migration.

## Notes

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit updated `deps` to include `ct-bt1q`, `ct-3faj`, `ct-3li2`, `ct-cpio`, and `ct-xl0y`. Now that `docspec-rs` branches are unified on `main` (`298053b`), fixing `ct-3li2` and `ct-cpio` on `main` will allow freezing one authoritative candidate binary instead of the separate per-worktree binaries (`f6699cd6`, `718c95bc`, `20a9fd82`).


**2026-10-20T22:19:30Z**

2026-10-20 fresh application adoption review at app 34c1ee7 / engine 9661026. Scope is congressional-tech using an upgraded engine, not reimplementing native lifecycle. Actual local/R2 capability must pass before use; unsupported upstream work remains linked evidence, not a completion claim. See docs/plans/docspec-application-adoption-20261020.md.

**2026-10-20T22:21:55Z**

Independent application-plan review required preserving ct-3li2 and ct-cpio as mandatory freeze prerequisites. Restored both dependency edges; chosen-binary evidence must prove the fixes even while upstream commits and ticket statuses advance.

**2026-10-20T23:32:30Z**

Evolutionary-refactoring audit at `main` (`8221566d` / `6cd80b0e`): restored `ct-bt1q` in `deps` to match acceptance criteria requiring owned-host EOF draining verification alongside `ct-3faj`, `ct-q968`, `ct-3li2`, and `ct-cpio`. Verified `QUALIFIED_DOCSPEC_RUNTIME` in `packages/congress_api/src/congress_api/retention/docspec.py:34-40` pins `docspec-rs` `22a804e19b8c8e376e28cf9612d4f8ae3b7b4726` (`darwin_arm64_binary_sha256` = `bd17918e9512e87d923e39ce7512c59550d420946fdc33fb5046b0d3bbc4ce3c`).

## Audit 2026-10-24

- Verdict: PARTIAL (batch mi03b).
- Grades: proposal 90 → 92, work 76 → 78.
- Problem: AC4's capability matrix is a source review that "ran no tests" (`docs/plans/docspec-application-adoption-20261020.md`).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03b/mi03b-verdicts.md:25
- Status: Reopened. Unmet: AC2, no mutable binary default (`binary.py` still searches `target/debug` then PATH, `client.py` falls back silently, news_lake uses `shutil.which`). Owner: WS3 step 6 (ct-tw3r), one digest-checked resolver. AC4's capability matrix is not carried.
- See docs/reviews/2026-10-24-ticket-audit/README.md
