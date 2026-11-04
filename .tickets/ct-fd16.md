---
id: ct-fd16
status: open
deps: []
links: [ct-itcg]
created: 2026-11-04T02:29:12Z
type: feature
priority: 2
assignee: mikewolfd
tags: [engine, lake, basin]
---
# Engine: replace a native table's contents as its next snapshot, then fold archive_r1b back into archive.*

Owner decision 2026-11-03: hosted jobs (publish-daily, backfill, maintenance, publish-model template) point at ct-archive-v2/archive_r1b.*, the tables live release e4538f00 was built from, because nothing can give the canonical archive.* tables (which hold v21) new contents. archive_import_job writes only into empty tables; append_rows adds only new keys (changed rows such as the ~51k corrected captures would keep v21 values); the engine's update command covers its internal datasets, not native catalog tables (whose operations are create, append, resolve, purge). The lead's 2026-11-02 direction on ct-itcg (canonical archive.<name>, v21 first snapshot, the rebuild next) assumed this step.

## Acceptance Criteria

The engine (spicy-stack docspec-rs) commits a native-table snapshot whose rows equal a pinned source exactly (EXCEPT ALL both ways), keeping prior snapshots for rollback, with any schema difference handled explicitly. archive.* is then advanced to the then-current archive_r1b snapshots, and the five job specs plus publish-model.json move back to archive.* in one commit, with Gate 1 passing against the live release.

