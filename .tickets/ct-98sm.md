---
id: ct-98sm
status: open
deps: []
links: [ct-v967, ct-csyg, ct-gi01, ct-6rnk]
created: 2026-10-24T18:15:53Z
type: epic
priority: 1
assignee: mikewolfd
tags: [audit-20261024, simplification]
---
# Simplify after the Oct 24 ticket audit

Goal: capture raw sources safely, rebuild everything else from them, and delete what that makes unnecessary. Sources: `docs/plans/simplification-plan-20261024.md` and `docs/reviews/2026-10-24-ticket-audit/README.md`. Raw-data checks and owner actions live in the separate epic "Raw data safeguards (Oct 24 audit)"; docspec-rs cuts (WS9 and the WS1 engine half) live in spicy-stack (IDs added in a note).

Owner decisions (binding):
1. The engine keeps durable per-phase commits and resume after a crash.
2. news_lake keeps the DocSpec backend; the PyIceberg oracle goes.
3. Publishing moves to a finished export-pins route; the journal and resume route goes.
4. Raw protection is an R2 bucket lock on `receipts/`, `bodies/` and `provenance/`; one bucket.
5. The `r2.dev` address stays open, so the custom-domain WAF is not an exposure boundary.
6. Engine-first: congressional-tech always uses the docspec-rs engine, with little or no custom code that overlaps engine capabilities. A missing primitive is added to docspec-rs generically (an ss-* ticket), never here. Audit tickets that keep overlapping code are reopened and marked "revisit under engine-first rule".
7. Wrong `stored_sha256` rows are repaired in place, not by regenerating the index.
8. The exclusion-list hook is deleted entirely.
9. Recovery imports refuse uncommitted code and record the git commit plus the `uv.lock` digest.

Rules for every child: one conceptual move per PR, with tests that pin the behavior landing before code moves; behavior changes in their own PRs. Run checks only through `.venv/bin/python scripts/dev.py test <lane>` (congressional-tech) or `scripts/check` (docspec-rs), never a tool from PATH, and say so in every agent or reviewer brief. Work in a separate worktree and venv (the primary checkout backs live recovery jobs). Report before and after `wc -l` in every PR that deletes code. Run the plan's R-check (section 1).

Reopened audit tickets keep their original parents, which are reopened too; each is linked to the child here that owns its remaining criteria.

## Acceptance Criteria

- Step 0 and every WS child below are closed.
- R-check 1 and 2 pass after the last merge.


## Notes

**2026-10-24T18:21:03Z**

Paired docspec-rs epic in spicy-stack: ss-oxg1. Its children: WS1 engine half ss-pdv0; WS9 steps 1-11 ss-k9as, ss-e2os, ss-p0tm, ss-g27q, ss-8lqi, ss-mz3e, ss-hlk9, ss-jv5t, ss-9qbt, ss-ghe7, ss-1q2o; optional ss-44p1. Raw-data safeguards: ct-v967.

**2026-10-30T17:48:00Z**

All Archive/Explorer/Engine-First workstreams (WS1-WS7, WS9-WS12) and F5 18-group legacy deletions (ct-5kto, -58,500+ net lines removed across G01-G18; zero PYTEST_CURRENT_TEST sites enforced in 3014737a; docspec/docspec_host shims deleted in 176cd4a1) are completed and closed. Kept open per WS12 Rule 1 solely for the parked news_lake workstream (WS8 / ct-d8cf, deferred per user decision A4) and live R2 bucket-lock application (ct-1l1h / ct-v967).
