---
id: ct-yndj
status: open
deps: []
links: [ct-fskn]
created: 2026-11-10T01:18:33Z
type: task
priority: 2
assignee: mikewolfd
tags: [hosted, archive, maintenance]
---
# Catalog maintenance has never run: readings holds about 1,907 files and 1,294 snapshots

Follow-up to ct-fskn. The weekly hosted maintenance schedule is off because the job was refused on every run (no disk budget names 'maintenance'; refused locally too). So compaction and snapshot expiry have not run: the 2026-11-10 architect review counted readings at 1,907 files and 1,294 snapshots against a 256-file threshold (not re-derived here). To bind the job: a committed hosted budget that names maintenance (measured), fetch-depth: 0 for the ancestry check, and current table names in model/jobs/maintenance.json (the review says it lists two superseded tables and omits three; verify). Run it only outside a release window: it moves catalog heads.

## Acceptance Criteria

One maintenance run finishes green (hosted dispatch or local) with before and after file and snapshot counts per table recorded here, and the schedule is restored in archive-jobs.yml or the reason it stays manual is recorded.

