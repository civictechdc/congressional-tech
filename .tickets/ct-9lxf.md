---
id: ct-9lxf
status: closed
deps: []
links: [ct-tk10, ct-umtm, ct-ud0b, ct-fskn]
created: 2026-11-02T16:23:34Z
type: chore
priority: 3
assignee: mikewolfd
tags: [disk, etl]
---

# Keep local disk space available for archive and recovery work

Keep active archive work and completed recovery results usable without accumulating unnecessary copies or abandoned spill. The `pipeline-data` fetch exclusion is delivered. The November 3 supervised Git cleanup exceeded its memory limit; it did not establish reclaimed space. The November 5 read-only audit observed 39 GiB available and 23.90 GiB in Git packs. These are dated measurements, not proof that the disk is currently exhausted or that those packs are reclaimable.

Compatibility proofs can now read qualified immutable mirrors in place with `--mirror-inventory`. The proof checks original keys, stored sizes, body identity and stable targets. Other inputs use the default private-copy path. The proof removes its disposable lock-attestation tree after use. The scoped `dev.py clean --proof-work` dry run identifies abandoned attestation scratch while protecting active work and completed checkpoints. Nightly disk admission and any orphaned native spill remain with the nightly wrapper owner.

## Acceptance Criteria

- The nightly admits a run on the measured peak plus 15 GiB of headroom.
- It refuses only when the engine, limits or lockfiles change.

## Notes

**2026-11-02T17:17:02Z**

Owner decision 2026-11-02: stop fetching pipeline-data locally (done: fetch refspec ^refs/heads/pipeline-data, remote-tracking ref removed); gc after the release when agents are idle; keep the NARA files.

**2026-11-02T17:17:59Z**

2026-11-02 owner: the NARA files were being used to recover documents. .cache/document-bulk-recovery-20261014T1552Z (nara/: 10 valid veterans.house.gov transcript recoveries, 175 bodies, a run intentionally stopped on proxy failures with 'preserve results') and .cache/nara-filename-estimate-20261015 (15 GB recovery workspace: Wayback continuation, residuals, docs.house.gov follow-ups, verified-local-recoveries.json) are recovery source material: never prune; added to the agent brief.

**2026-11-02T18:59:51Z**

2026-11-02: output/corpus-retry-20261015 (32 GiB) is recovery work (recovered hearings, reports and XML packages, govinfo-bulk-qualified downloads, publication checkpoints 16 and 19 at 9 GB, recovery ledgers). Protected like the other recovery workspaces; review with the owner in the post-release cleanup. .cache/document-recovery-finish-20261013T1136Z (10.6 GiB) and .cache/document-eot-expanded-20261013 are protected too. For this release the model run uses a 15 GiB guard disk floor instead of deleting anything (80 GiB free against a 53.4 GB capture_dup spill, until the engine spill fix lands).

**2026-11-05T20:18:16Z**

Applied the accepted third-round scope update. The current description records the root cause, delivered work, remaining behavior and bounded checks; historical notes remain unchanged. No implementation or operational action was performed. [Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

**2026-11-05T21:20:58Z**

Local main merge `dd9a6f82` includes `2884a9f0`. The maintained CLI compared 225 custody-checked read-only symlink targets from the retained 2,000-body sniff sample, covering 749 capture rows. Both arms produced byte-identical proof reports, sample keys, inventories, readings and unreadable decisions, with zero comparison differences. Direct reuse avoided 7,515,657 logical bytes and 8,044,544 allocated bytes of private payload copies on this cohort. The other 1,775 writable bodies were outside the direct-mode comparison. The 93 focused tests passed across three lane files. They covered wrong same-size bytes, a swapped symlink target, an active child lock and scoped fixture cleanup that preserved the completed checkpoint.

Keep this ticket open. The nightly owner still needs to measure peak additional disk across the complete operation, reserve headroom before launch and verify that only orphaned native spill can retire after process exit while the completed checkpoint remains resumable. Post-release Git maintenance still needs a quiet window, a measured memory and disk budget, and actual before-and-after allocation evidence. The protected recovery roots and the fetch exclusion remain in effect. [Resources handoff](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/resources/STATUS.md) · [Nightly owner proposal](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/resources/nightly-spill-proposal.md)

**2026-11-06T17:28:08Z**

Isolated implementation on codex/ct-9lxf-disk-lifecycle, based on 742dbe70 (not merged or deployed). The maintained nightly setup and common publish/backfill wrapper now require an explicit whole-operation disk budget for the selected revision. They check additional peak plus at least 15 GiB headroom on every configured writing filesystem, with separate fresh/retry allowances. Missing or insufficient budgets refuse before setup/producer launch and before candidate retirement. The existing watchdog disk floor remains a separate runtime guard; this admission does not reserve bytes against unrelated writers.

After the owned process group exits, the nightly lock covers retirement of only native children explicitly declared by job metadata. Unknown layouts, aliases and retained input/output/checkpoint references keep the data and record a diagnostic. dev.py clean --nightly-spill adds a locked dry run for the active nightly candidate. Prior backfill output moves intact into durable previous-backfill storage instead of being git-cleaned. No shared cleanup was performed.

Focused verification: all ten native interruption/retry scenarios passed (0.59 GiB peak RSS under the watchdog), including preserved result/manifest identity and exactly one model build on a matching retry. The final broader focused run passed 97 checks across five lane files; the final disk-only run passed 21. These are partial checks, not a full lane. One unchanged capture-workflow fixture fails because its test environment omits REVIEWED_CUTOFF_URLS; retained separately in focused-disk-workflow.log. Pinned retained Poppler 26.06.0 supplied the test PATH. No byte-hashed parser, model definition, runtime pin or lock changed; advisory reading-version fixtures matched within their existing scope.

Keep open: final integrated DDK/runtime code still needs qualified complete setup, fresh publication, compatible retry and backfill allocation measurements. Failed shared-volume nightly drawdowns and the model-only 3.3 GiB measurement do not establish those budgets. No production budget was invented. Quiet-window Git maintenance remains with the existing global cleanup owner; its November 3 run exceeded 8 GiB RSS and established no reclaimed allocation. Fetch exclusion and all protected recovery material remain intact. See docs/archive-disk-lifetimes.md and the durable implementation/reviewed-non-news-20261106/ct-9lxf handoff.

**2026-11-06T18:43:10Z**

Independent four-skill review of 22de0665 found that Python temporary files could be written on an unbudgeted filesystem when RUNNER_TEMP differs. Additive commit abd90dff includes the actual Python temporary root in admission and tests split-filesystem refusal; 23 focused cases passed, including one native retry consumer (partial lane). The original commit is preserved, and the same reviewer is checking the exact follow-up. Exact integration notice/patch: .cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-9lxf/INTEGRATOR-NOTICE.md and FOLLOWUP.patch.

Keep open pending the final review and root integration of abd90dff, then ct-m104/DDK final layout verification and complete-operation measured budgets. Existing global cleanup owner retains quiet-window Git maintenance. No live delivery, shared cleanup, competing build or publication is claimed.

Independent review is in progress. No final review approval or completed release acceptance is claimed.

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at 20c55d20. Disk admission now includes Python temporary files when they use a different filesystem from RUNNER_TEMP. The review also checked documented reuse of retained measurements after non-resource source changes: both revisions and unchanged workload/runtime/storage guarantees must be recorded. Exact-revision and capacity refusal remain enforced; 23 focused checks passed.

This reviewed follow-up is not yet included in local main. Remaining: Qualified final-layout operation budgets and release-owner resource checks. Measured Git maintenance remains with the existing cleanup owner. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-9lxf/REVIEW.md).

**2026-11-06T20:26:32Z**

Integrated the approved temporary-filesystem fix abd90dff and measurement-reuse documentation 20c55d20 into main, complete at 82a52289. Resource admission includes Python's actual temporary filesystem. Retained measurements may be reused only with a recorded explanation of unchanged workload, runtime and storage guarantees; exact-revision and capacity checks still apply. The final documentation delta was independently approved.

Keep open for qualified complete-operation budgets at the final layout and release-owner resource checks. Quiet-window Git maintenance remains with the existing cleanup owner. No shared recovery data was deleted. Evidence: .cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-9lxf/SUPPLEMENTAL-REVIEW-20c55d20.md.

**2026-11-07T23:00:34Z**

November 7 disk-admission acceptance credits the merged guards, Python temporary-filesystem coverage, 23 focused checks, and the actual interrupted-publication retry that successfully published `5d24699ad9fa`. Retained checkpoint and result hashes still match. The checkpoint's sampled shared-volume drawdown was 4.0 GiB; the publication resume held at 72.2 GiB free at 0.1 GiB sampling resolution. These measurements cover those commands, not every scheduled operation. The cleanup dry run found no active nightly spill; final release and recovery artifacts remain retained.

Keep `ct-9lxf` open for the release/nightly owner to qualify and supply per-filesystem allocation and headroom for setup, fresh publication, compatible retry and backfill. Current publish/backfill admission correctly refuses the missing default budget and names `python_temp`. Reuse existing measurements only when they cover the whole selected operation and layout. The existing cleanup owner may retire the separately identified 7.7 MiB of test fixtures in its coordinated window; optional Git maintenance remains separately owned. [Release evidence](../.cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-9lxf/RELEASE-EVIDENCE.json) · [Maintained checks](../.cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-9lxf/maintained-checks.json).

**2026-11-08T17:28:23Z**

2026-11-08: a disk budget no longer breaks on every push (claude/sweep-c): admission accepts a budget for any descendant of its measured revision that leaves the engine pin, local limits, job bindings, uv.lock and site lockfile unchanged (RESOURCE_PATHS in scripts/archive_disk.py; test_archive_disk.py 23 passed, partial). Proposed budgets: publish-fresh 10 GiB (from the 7.9 GiB drawdown of the 630164505301 build at 3ebe6872), publish-resume 8 GiB, setup 4 GiB estimate, all with 15 GiB headroom, in the sweep-c worktree at .cache/sweep-c/proposed-disk-budgets.json; the admission check admits publish-fresh at 50.2 GB free. Backfill stays unbudgeted and refuses. The owner approves and installs the file. Repository maintenance and the other cleanup criteria remain open.

**2026-11-08T17:42:58Z**

2026-11-08: acceptance criteria simplified by owner decision (proposed by the ticket sweep); the earlier criteria are in git history.

**2026-11-09T15:55:45Z**

2026-11-09 owner decision: closed. Disk is managed per job (watchdog low-disk stop, scoped caps) rather than by a standing ticket; 31 GiB free today.
