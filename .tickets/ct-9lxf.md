---
id: ct-9lxf
status: open
deps: []
links: [ct-tk10, ct-umtm, ct-ud0b]
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

- Preserve the fetch exclusion. Before retrying owner-requested post-release Git maintenance, use a quiet window with measured memory and additional disk capacity for the operation. Record completion and actual footprint changes; do not infer savings from total pack size or repeat the failed unbounded attempt.
- Try the exact proof sample against the custody-checked mirror in place and show identical results with no sample payload copies. Use a clone or hardlink only if an actual private-layout requirement remains and custody, immutability and volume checks permit it.
- Give each job wrapper a known disposable spill root and retirement rule after its process exits. Reserve measured peak additional disk plus headroom before expensive work. The watchdog's post-start disk floor is not that reservation.
- Extend the existing clean dry run only for known-owned completed or abandoned disposable scratch. Coordinate with `ct-ud0b` so cleanup preserves completed candidates and the artifacts their checkpoints reference. Verify that an interrupted retry retains expensive completed work while unused spill can retire.
- Protect active jobs, the immutable mirror, archive-release inputs, runtimes, source history, rollback material, and the NARA and October recovery workspaces listed below. Older inventory figures are review leads, not deletion permission; preserve the owner's exceptions.

[Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

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
