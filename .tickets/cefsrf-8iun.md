---
id: cefsrf-8iun
status: closed
deps: []
links: []
created: 2026-10-28T01:25:13Z
type: task
priority: 1
assignee: site
---
# B5 approved local Linux runtime and site publication qualification fixes

Owner retroactive review: install the approved credential-free Linux archive in CI, enroll existing reader/browser checks, and refuse pointer writes for owner-gated target receipts. E4 is paused; this isolated site-owned branch allows critical fixes to merge independently.

## Acceptance Criteria

Tests fail before B5/gate/enrollment fixes and pass after; malicious archives fail before install/export, project doctor precedes offline tests, owner-gated receipts make zero pointer PUTs, and existing CI invokes presentation/tools/saved/heap checks.


## Notes

**2026-10-28T01:46:48Z**

Closed implementation after41 focused Python checks,172 npm checks, built hand-release desktop/phone/404/saved-content/two-tab worker runs, CODE APPROVE and ARCH APPROVE forfd799d1f..642b5b3a. Tests demonstrated pre-fix refusal failures. Actual approved Linux archive and DOCSPEC_LOCAL_RUNTIME_URL/SHA256 repository variables remain owner supplied; no Linux engine execution, live workflow, credentials or network write performed. Engine publisher adoption remains its integration dependency. Original worktree/branch used; extra unused scratch worktree has no commits.
