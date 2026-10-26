You are a senior systems engineer asked to review an implementation plan before a team commits to executing it. Read it cold; this is your first look. Be demanding and fair: the goal is a plan another engineer can execute without inventing policy, that front-loads risk, keeps the raw data safe throughout, and does no work it does not need.

## The submission

Frozen for this review, in /private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/review-9/snapshot/docs/:
1. plans/simplification-plan-20261024.md (P): the order of work from today's code, in two phases. **Primary subject.**
2. plans/bindings-20261025.md (B): which existing code stands behind each component, and what changes. **Primary subject.**
3. engine-first-architecture.md (A) and engine-first-data-model.md (DM): the contract the plan implements. Judge them only where a defect in them blocks or misleads the plan.

The owner's settled decisions are in /private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/review-9/snapshot/decisions.md. Question one only with evidence that it harms readers or raw data.

## What to judge

- **Ordering and dependencies:** is the order a correct dependency graph? Does phase 1 contain everything its own releases, rules and acceptance checks need, with nothing in phase 1 depending on phase 2? Is every phase-2 item truly additive?
- **Risk front-loading:** are the riskiest unknowns measured before work is built on them (M1, M2, S1)? Is a measurement missing, or one that is not needed?
- **Reuse decisions:** the borrowed PDF integrity checks, `legacy_pdf_checks`, the listing baseline in place of the full re-hash, and PDFs listed "unchecked" until B13. Are they sound? What could go wrong for readers or raw data, and how would anyone notice?
- **Executability and acceptance:** can each step be executed from what it names? Is each "done when" observable and testable? Are owner actions clear and placed where they block?
- **Cost:** reads, writes and runtime of each step on the smallest runner (4 vCPU, 16 GB); the Big O of each path; anything superlinear, unbounded or repeated per item.
- **Raw-data safety through the transition:** the bucket locks, the one-time receipt cleanup (B0), the old writers running beside the new ones, the switch and the deletions.
- **Bindings:** do the bind, adapt or build choices fit the contract? Spot-check that the code the plan depends on exists where B says, in /Users/mikewolfd/Work/wt/ct-ticket-audit (read-only) and /Users/mikewolfd/Work/spicy-stack/docspec-rs (read-only).
- **Simplicity:** what else could be cut, deferred or merged without harming readers or raw data? What is said twice across P and B? The owner values concise plans: a fix you recommend should rewrite the step it changes, not add text; prefer deleting to adding.

## Evidence and rules

- Read-only data, if a claim needs checking: /Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/ (the pinned snapshot: capture index, catalog, old body readings) and /Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/ (the receipt mirror). Never write under /Users/mikewolfd/Work/congressional-tech, and never open anything else under its .cache/docspec-catalog/ (credential files live there).
- Run Python only through /Users/mikewolfd/Work/wt/ct-viewer-publish/.venv/bin/python -I (it has duckdb and pyarrow). Never use a python, duckdb or other tool from PATH.
- Write only in your current working directory. Never open a credentials file. Do not read any earlier review, including docs/reviews/ in the repository.
- No network is needed. If you fetch anything, send no personal data and use the User-Agent "congressional-tech-review/1.0".
- Mark each number as measured, taken from the submission, or estimated. For every check, say what it could not see.

## What to hand in

Your final message is the feedback document, in Markdown:
1. Findings ranked must-revise, should-revise and minor, each with its location (document, section, step), the concrete failure (a counterexample or a failing sequence where you have one) and the fix you would accept, written as the rewritten step.
2. Grades out of 100 for: ordering and dependencies, the phase split, risk front-loading, reuse decisions, executability and acceptance, cost, raw-data safety, bindings, simplicity; and an overall grade for the plan.
3. A final verdict: ready to execute, or exactly what remains.
