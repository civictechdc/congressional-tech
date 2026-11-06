---
id: ct-1l1h
status: open
deps: []
links: [ct-syx8, ct-4jms, ct-98sm, ct-v967, cef-sqyq]
created: 2026-10-24T18:15:53Z
type: task
priority: 0
assignee: mikewolfd
parent: ct-77zb
---

# Lock the raw receipts, bodies and provenance in R2

Protect irreplaceable source evidence from overwrite or deletion. Apply the owner-approved indefinite locks to the three raw prefixes in the existing bucket at the cutover point in the [switch plan](../docs/plans/engine-first-switch.md).

## Current evidence

Current lock configuration is unverified: object metadata credentials do not establish bucket policy. On November 5, three exact-key HEAD reads matched the pre-cleanup sizes and ETags in the B0 identity record, with modification dates before its October 30 completion note. These counterexamples contradict a blanket completed rewrite for those keys; they establish neither the rest of the corpus nor receipt contents.

This ticket owns the remaining B0 disposition. Preserve `cef-sqyq`'s local tooling and qualification history, and reconcile its live-completion claim here. B0 covered both local paths and authorization/cookie headers. The November 2 and 4 owner exception permits historical paths; it does not by itself resolve any separate header obligation. Do not rewrite old raw merely to close the ticket.

Exact keys, original/cleaned/live sizes and ETags, and timestamps are retained under `verification.b0_head_samples` in [the read-only review](../.cache/archive-release/investigations/mvp-etl-root-causes-round3-20261105T194539Z/capture-lifecycle-root-causes.json).

## Acceptance Criteria

- Reconcile those exact B0 counterexamples, the existing cleanup/verification artifacts and the owner's historical-path decisions. Record the separate header disposition without inferring a current leak from metadata alone. Reuse suitable evidence before deciding whether any further read is needed.
- Obtain management-plane or dashboard readback of active indefinite rules for `receipts/`, `bodies/` and `provenance/` in `congressional-tech-raw`. Apply any missing owner-approved rule at cutover, preserving unrelated rules. A create-only writer or successful object HEAD is not lock readback.
- Reuse the switch plan's existing lock qualification evidence, rerun R2 check 4 after relevant infrastructure changes, and keep B9's weekly raw verification after locking. `ct-4jms` separately owns scheduled acquisition and first-run raw preservation.

[Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

## Notes

**2026-11-01T20:08:14Z**

Owner decision 2026-11-01: hold the locks until cut-over. Before locking receipts/, settle the B0 conflict: cef-sqyq records completion on 2026-10-30T14:32Z, while the later cef-96wc note (19:28Z) lists B0 as pending. Rescan receipts first, because B0 rewrites them.

**2026-11-05T17:11:15Z**

Acceptance transferred from ct-v967/ct-98sm: indefinite locks on receipts/, bodies/ and provenance/ in the same raw bucket, with live readback after application and relevant infrastructure changes. First reconcile conflicting B0 records read-only and retain the owner's historical-receipt/path exception; do not rewrite old raw merely to close this ticket. Preserve the documented B0 exception and B9 weekly raw verification after locks. ct-4jms owns first successful merged raw-writer run preservation and receipt-body existence. Existing reconciliation and legacy digest dispositions stay with ct-st8m/ct-63hg; ct-3szv's 33 NULL-legacy-SHA candidates are verification evidence rather than asserted corrupt current rows.

**2026-11-05T20:18:16Z**

Applied the accepted third-round scope update. The current description records the root cause, delivered work, remaining behavior and bounded checks; historical notes remain unchanged. No implementation or operational action was performed. [Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

**2026-11-05T21:22:04Z**

Read-only reconciliation matched the three exact saved live HEAD identities to the B0 scratch inventory and retained local originals by compressed size and MD5/ETag. The committee and document originals had 688 and 2,846 B0 header-pattern occurrences, respectively. Those are counts of scanner matches. Credential validity and current exposure remain unverified. The YouTube original had eight path matches and zero header matches. Preserve the November 2 and 4 historical-path exception for that sample, and keep the header disposition separate. The evidence concerns these three originals. Preserve the local B0 qualification and the documented before/after raw identity exception. [Exact reconciliation](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/capture-ops/b0-reconciliation.json)

Live acceptance remains open. The owner must resolve the separate header disposition before receipt lock cutover. No authorized management-plane token or dashboard readback was available for this lane. Obtain readback of the enabled indefinite rules for `receipts/`, `bodies/` and `provenance/` in `congressional-tech-raw`. At authorized cutover, follow the existing procedure for any missing approved rules, preserve unrelated rules, repeat readback after relevant infrastructure changes, and retain the B9 weekly raw verification result after locking. The hold covers historical receipt rewrites and production lock changes. [Cutover handoff](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/capture-ops/CUTOVER.md)

**2026-11-06T18:43:10Z**

Independent work is complete at preserved source commit dd891679a6a1ea517a68306634d9b69ee906b65b. Reused the exact B0 three-key reconciliation and completed writer qualifications, and corrected the blanket B0 rewrite instruction. Fresh authenticated management GET at 2026-11-06 18:24:28 UTC returned HTTP 200, success true, and rules: [] for congressional-tech-raw: all three required prefix locks are absent at that observation. The earlier 403/access blocker is superseded. Prepared and validated two-stage correction JSON bound to that complete readback; none was applied. No raw contents were reopened and no infrastructure changed. Evidence and proposals: .cache/archive-release/implementation/reviewed-non-news-20261106/ct-1l1h/HANDOFF.md.

Keep open: the account/privacy owner must settle separate header findings and applicable live B1/provenance prerequisites; ct-m104/cutover owner with the authorized account operator must apply approved locks after fresh full-rule readback, preserve unrelated rules, and retain post-lock readback/B9 verification. ct-4jms retains scheduled first-run raw custody acceptance. The reviewed commit and source freeze remain unchanged; the worktree is absent and its branch is retained.

Independent GPT-6.1 Sol/xhigh reviewer /root/ct_1l1h_independent_review read greybeard, etl-workflow, evolutionary-refactoring and semi-formal-code-review and returned APPROVE for exact commit dd891679a6a1ea517a68306634d9b69ee906b65b. No blocking scoped defect; static writer/retry/test traces and retained evidence identities passed review. The reviewer confirms the patch prepares acceptance and does not remove the live absence of locks. Review: /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-1l1h/REVIEW.md. Keep ticket open for the owner-controlled obligations above.

Independent review: APPROVE for the scoped work; remaining ticket acceptance is unchanged. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-1l1h/REVIEW.md).
