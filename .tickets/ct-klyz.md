---
id: ct-klyz
status: open
deps: [ct-4jms]
links: [cef-96wc]
created: 2026-10-30T14:32:31Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, ops, b14, cutover, track5]
---
# T5.1 (B14): Run B14 meeting fetchers live once and remove legacy weekly meeting job from update-data.yml

Per docs/plans/phase-2-annex-20261028.md §4.1: execute the B14 meeting fetchers live once, then remove the legacy weekly meeting inventory job from .github/workflows/update-data.yml and drop capture's weekly inventory seeds.

## Acceptance Criteria

B14 meeting fetchers have completed a live run, the weekly meeting inventory job is removed from update-data.yml, and weekly inventory seeds are dropped.


## Notes

**2026-11-01T20:08:14Z**

Reopened 2026-11-01: update-data.yml still runs congress-meetings on its weekly schedule (ran 2026-11-01T04:36Z). Owner decision: keep it until new capture is enabled, because it is the only meeting capture still running. Remove it after ct-4jms passes.

**2026-11-04T12:46:09Z**

Owner decision 2026-11-04: remove the legacy weekly meeting job from update-data.yml now, without waiting for B14's first live run or capture enablement.
