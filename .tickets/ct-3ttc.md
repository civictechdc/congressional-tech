---
id: ct-3ttc
status: closed
deps: [ct-0odd]
links: [ct-0odd, ct-aia9, ct-ec91, ct-te1p, ct-gi01, ct-8kl2, ct-2yl5, ct-bwac, ct-84xa]
created: 2026-10-22T04:03:02Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-8kl2
tags: [committee_explorer, ci, docspec, retention, parquet]
---
# Enable --docspec-workspace and WeeklyRetentionTables in publish-explorer.yml and update-data.yml CI workflows

Wire the newly built ExplorerDocSpecWorkspace (--docspec-workspace) and WeeklyRetentionTables (DOCSPEC_RETENTION_WORKSPACE) into .github/workflows/publish-explorer.yml and .github/workflows/update-data.yml so CI runs incremental docspec-rs views and ExportPins end-to-end.

## Design

1. In .github/workflows/publish-explorer.yml, install the qualified linux-amd64 docspec binary via .github/scripts/setup-native-runtime.py (or DOCSPEC_BINARY) and pass --docspec-workspace to 'python -m committee_explorer.export'.
2. Persist export-pins.json alongside publication.json in committee-explorer state.
3. In .github/workflows/update-data.yml, configure DOCSPEC_RETENTION_WORKSPACE so weekly House, Senate, captions/inventory, meetings, GPO, YouTube, transcripts, and rejected_pages retention steps update incremental docspec-rs tables alongside or instead of .json.gz snapshots.

## Acceptance Criteria

1. publish-explorer.yml executes within the 2 GiB MemoryMax scope, refreshes explorer_meeting_observations, explorer_meeting_summaries, and explorer_committee_rollups, and writes verified export-pins.json.
2. update-data.yml updates the 9 weekly retention datasets cleanly via WeeklyRetentionTables.

