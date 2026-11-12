---
id: ct-ucwm
status: open
deps: []
links: [ct-w564, ct-arlk, ct-eav2]
created: 2026-11-10T13:27:30Z
type: task
priority: 2
assignee: mikewolfd
tags: [nightly, disk, ops]
---
# Replace the carried-forward disk budgets with measured figures

On 2026-11-10 a push that moved uv.lock made the scheduled nightly refuse at setup disk admission (budget revision differed). The three budgets in .cache/archive-release/disk-budgets.json (setup, publish-fresh, publish-resume) were carried forward by hand from 46d61ae7 to 8c3a2633 with a note saying so; the earlier copy is release-20261110/disk-budgets.json.before-20261110T1115Z. Measured since, on a fresh full build through the launch agent (run 20261110T121530.896579Z): free disk 129.1 to 128.3 GiB minimum during publish, peak 11.20 GiB RSS, 9.88 GiB physical. The engine re-pin will move a guarded path (model/docspec-runtime-pin.json) and must re-qualify the budgets in the same step.

## Acceptance Criteria

Each budget's measurement text states a measured figure with its run folder, not 'carried forward'. The release procedure says which pushes need re-qualification (engine pin, local limits, .github/archive-jobs.json, uv.lock, apps/site/package-lock.json) and how.


## Notes

**2026-11-10T18:01:04Z**

2026-11-10 18:01Z also needed for the release after this one: the hearing-records (MODS) parser change needs the appearance table regenerated in the lake once at its final parser version (35,020 records) through the backfill job, and no disk budget names the 'backfill' operation today. Add a measured budget for it before that activation (congress-1's plan: MODS reviewed, then Member appearances stacked on it, one offline all-in build, one cause record, the activation, then the driver run).

**2026-11-10T20:39:29Z**

2026-11-10 not resolved by release 77673bfb8fcf. The release runs at d3ed7ca5 still admitted against budget revision 8c3a2633, whose publish-fresh text still says 'carried forward'. The fresh run (nightly/20261110T195322.097664Z) gives figures to use: publish step 1,658.6 s, peak 9.74 GiB RSS (publish-watchdog.json). Its disk-admission files hold free space at admission only, not the drawdown, so that number still has to come from a measured run.

**2026-11-11T11:56:39Z**

2026-11-11 (session congress-1): disk budgets added to .cache/archive-release/disk-budgets.json (outside git; backup disk-budgets.json.before-20261111T1011Z) for the record-only backfill replay ('backfill') and the import ('import'), each 1 GiB plus 15 GiB headroom, from measured runs of the MODS appearance activation (record-only replay of 35,020 MODS rows over 327,659 reused: 205-470 s, peak 1.58-1.70 GiB RSS, 33.6-33.9 MiB own folders; local import rehearsal 11-14 s, 1.44-1.45 GiB, 42 MiB); evidence .cache/archive-release/investigations/mods-backfill-activation-20261111/ (ba-findings.md, ba-runbook.md, run-m17/). run-archive-job.py backfill --check-disk still refuses, now on roots rather than a missing budget, because its default daily mode is unmeasured; deliberately left refusing. Related: ct-eav2 (check the target schema before any write or fetch), ct-auhc (engine add-column operation).

**2026-11-11T14:33:14Z**

validated 2026-11-11, left open: .cache/archive-release/disk-budgets.json (read today, modified 07:20) still has publish-fresh, publish-resume and setup at revision 8c3a2633 with texts that say carried forward or ESTIMATE; only the two new entries (import, backfill-record-only at ab391575) state measured runs. No doc in docs/ says which pushes need re-qualification. Remains: measured figures for the three budgets from a nightly run folder (the 20261111T103005Z nightly is a candidate: publish peak 10.78 GiB RSS, 1,158 s) and the procedure text. The pin move will re-stamp them (its step 7 is prepared: refactor/pin-move/STEP7-disk-budgets.txt).

**2026-11-12T01:12:28Z**

Updated .cache/archive-release/disk-budgets.json (backup disk-budgets.json.before-20261112T010656Z) at revision 11595d599bc13fe86c1bc21ded439dd8dc796c96 (engine ae12bbd4) replacing all 'carried forward' and 'ESTIMATE' text on publish-fresh, publish-resume, and setup with measured figures and run folders: publish-fresh measured 78.80 -> 72.80 GiB (6.00 GiB max drawdown, 1,302 s, peak 9.77 GiB RSS) in nightly/20261112T002603.002845Z (timeline sha256 147db296...) and 62.2 -> 57.9 GiB (4.3 GiB) in refactor/pin-move/candidate-build-2; publish-resume measured 76.50 -> 76.50 GiB (< 0.1 GiB drawdown, 187 s, peak 4.64 GiB RSS) in nightly/20261112T005217.004021Z (timeline sha256 2e1c8b24...); setup measured 1.29 GiB total populated worktree dirs (.claude/worktrees/nightly du -sk: .venv 711,112 KiB, explorer_mcp/.venv 247,040 KiB, node_modules 306,040 KiB, dist 2,352 KiB, spicy-regs 85,940 KiB) and 0.014 GiB net admission-to-publish drawdown on 20261112T005217.004021Z. Also named all five literal RESOURCE_PATHS in docs/archive-disk-lifetimes.md. Remaining before closing: confirm import on ae12bbd during W22 (ct-yndj) and backfill-record-only on next replay.
