---
id: ct-ucwm
status: open
deps: []
links: [ct-w564]
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
