---
id: ct-o24q
status: closed
deps: []
links: [ct-ylaw, ct-zkzt, ct-qqk2]
created: 2026-10-18T19:25:05Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Select full rebuilds from all release inputs

prepare() selects recovery-only work when the raw manifest and PUBLISHER_VERSION match. A builder, policy, or review-identity change can then update recovery_inputs to the new revision while retaining old browse and review outputs. Full Git revision also invalidates unchanged polls after unrelated commits.

Source: scripts/viewer_publication_attempt.py:43-69; apps/site/scripts/publish-viewer-r2.py:80; .github/workflows/publish-filename-viewer.yml.

## Acceptance Criteria

Persist one explicit full-release input identity. Changed builder, runtime, policy or review inputs require full preparation; accepted-mapping-only changes require recovery preparation; unrelated documentation changes remain no-op. Include required workflow paths. A resumed artifact must still match its original input identity. Test all branches, including local dirty inputs or an explicit clean-tree precondition.

<!-- grade-followup:start -->
## Grade review follow-up

implementation_identity, dependency_fingerprint, recovery_inputs, refresh_recoveries, content_identity and prepare/run mode selection.

- Use a documented relevant source/runtime identity, handle dirty local transitive edits explicitly, and compute it once per stable invocation. Preserve absent/empty/same-count mapping differences; builder/review/runtime changes choose full, accepted-only changes recovery, unrelated docs no-op.

[Function scope and checks: 8 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:526). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:11:48Z**

Implemented explicit full_release_inputs across selection/preparation, dirty transitive source bytes, review and runtime pins, docs-independent identity, required workflow paths. Verified 57 focused tests plus 2 subtests; runtime/build/publisher changes choose full and resumed artifact rejects runtime drift. Conservative congress_api closure documented.

**2026-10-18T20:15:08Z**

Integration review added review-publication descriptor itself to full release source closure and workflow triggers; descriptor-only dirty mutation changes identity. Combined matrix82 tests plus2 subtests passed.

## Audit 2026-10-24

- Verdict: PARTIAL (landed, then regressed) (batch d8z3b).
- Grades: proposal 90 → 80, work 72 → 72.
- Problem: Builder changes no longer force full preparation, which breaks the core AC.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/d8z3b/d8z3b-verdicts.md:22
- Status: Closed as superseded by the simplification plan (WS6, ct-qqk2): WS6 deletes `release_identity.py` and the preflight "unchanged" decision; content-addressed releases replace the hand-listed identity.
- See docs/reviews/2026-10-24-ticket-audit/README.md
