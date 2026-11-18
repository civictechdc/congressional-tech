---
id: ct-1mq9
status: closed
deps: []
links: [ct-z4i9, ct-yndj]
created: 2026-11-11T04:24:14Z
type: task
priority: 3
assignee: mikewolfd
tags: [lake, maintenance, perf]
---
# Bound readings-file regrowth after the completed November 12 compaction

## Implementation update — 17 November 2026

Closed after the operator path gained a 64 MiB default byte target through the existing readings batching implementation. Three focused native consumer/resume/custody tests passed; no separate scheduler or batch implementation was added.

Measured current readings storage is 74 data files / 33 snapshots versus 35 / 1 after November 12. The increase is mixed incremental/backfill activity, not a measured per-night rate. File count remains below the existing 256-file review threshold; manifest/planning measurements are unavailable. The evidence-backed decision is to retain manual maintenance and existing thresholds. No repeat compaction or history deletion occurred.

Evidence: `<main checkout>/.cache/archive-release/ticket-fixes-20261117/growth/decision.json`, `observation.json`, `README.md` and focused-test receipts. No required recurrence/batching work remains in this scoped ticket.

## Audit baseline — 17 November 2026

The first ct-yndj compaction completed on November 12: 1,910 -> 35 data files and 1,296 -> 1 snapshots, with 1,654,201 rows preserved and exact-value/model-output checks retained. Earlier notes here saying the move has not run are superseded. The new active table is `archive_r1b.readings_compact_20261112`.

The recurrence mechanism remains: each append checks existing keys and adds files. Historical remote measurements linked append time to file count; the old estimate of three files/night is not a current post-compaction measurement. `produce_html_metadata` in `lake/daily.py:859` still accepts only a row batch size; the nightly derived path already has a byte bound. Maintenance observations remain empty, and earlier engine reports lacked manifest/planning metrics.

## Acceptance Criteria

1. Reuse retained post-move run metadata to measure files added per nightly and distinguish ordinary incremental growth from backfills. Complete the original two-week observation window (November 12–26) before selecting the cadence, or explicitly record an evidence-backed decision to retain manual operation. No repeat compaction just to measure growth.
2. Give the operator HTML-metadata path a meaningful byte bound aligned with the maintained nightly path, or record a specific reason it is unnecessary. Preserve batching that avoids one commit per row; measure relevant append/file effects without claiming an unmeasured speedup.
3. Record the trigger/cadence and unavailable metrics honestly. Reuse existing maintenance and recovery facilities, preserve release-pinned history and keep the schedule manual until its stated adoption requirements are met. Do not invent a second maintenance scheduler.

## Evidence

Completed move: `<main checkout>/.cache/archive-release/maintenance/readings-move-20261112T0110Z/` and ct-yndj closeout. Current helper: `packages/congress_api/src/congress_api/lake/daily.py`; current observations/config: `model/jobs/maintenance.json`. Historical append-cost data remains valid only for its dated population.

## Audit evidence

17 November manual audit: `<main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md`. Historical notes below are retained; the current scope and criteria above supersede their dated unfinished-work summaries.

## Notes

**2026-11-11T14:31:18Z**

validated 2026-11-11, left open: depends on the first ct-yndj move, which has not run, and then two weeks of files-per-nightly before the owner picks a cadence; produce_html_metadata still takes a plain batch_size (lake/daily.py).

**2026-11-17T09:17:02Z**

Manual audit corrects the stale prerequisite: ct-yndj completed the first move on November 12 (1,910 -> 35 files; 1,296 -> 1 snapshots). Remaining work is measured post-move growth/cadence and the operator helper's byte bound. Historical three-files/night and cost estimates are dated evidence, not a new measurement. Schedule stays manual under existing requirements. Audit evidence: <main checkout>/.cache/archive-release/ticket-state-review-20261117/review.md.

**2026-11-17T10:28:53Z**

Implemented selected 80/20 scope via subagents. The current implementation update above records completed work, exact evidence and remaining acceptance. Full evidence is under <main checkout>/.cache/archive-release/ticket-fixes-20261117/. Historical notes are preserved. Byte-bound implementation and measured manual-maintenance decision complete; closed.

**2026-11-18T15:24:52Z**

2026-11-18: this ticket was closed on 2026-11-17 citing the byte bound on produce_html_metadata, but that commit (4c87b9f6) existed only on an unpushed local main. It is now pull request 202. Measured today from hosted pins: readings takes 2 commits a night (metadata 00039 on 11-17, 00041 on 11-18), about 40 since the 11-12 compaction, so under 10 s a night by this ticket's formula. There is still no automatic compaction and no file-count alarm; archive-jobs.yml maintenance is dispatch-only and model/jobs/maintenance.json has an empty lake_maintenance.
