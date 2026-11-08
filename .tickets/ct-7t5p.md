---
id: ct-7t5p
status: open
deps: []
links: [ct-deg8, ct-wsu7]
created: 2026-11-08T13:44:49Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [docspec, datafusion]
---
# Land the DataFusion 55 type pins with the engine upgrade

Branch df55-types (backed up to GitHub at 30ba6655) holds the casts DataFusion 55 needs so published column types stay the same: capture_scheduler's NULL next_attempt_at branch named as Timestamp(us, UTC); url-state.sql requested_url and last_outcome cast to Utf8 (the 55.2 engine refused 122 offline-lane tests without them, apache/datafusion#27023); and source-annotations-final.sql's document_kind branch cast to List(Utf8), because DF55 keeps the filename table's element field id. Main still pins engine b0342a7 (DataFusion 53.1), so nothing is broken today. When the engine moves to 55: rebase (url-state.sql changed on main in bc0a146c), prove byte identity on b0342a7, run the offline lane on 55. The document_kind cast was saved from an uncommitted edit and has not been run on either engine. Related history: ct-wsu7, ct-deg8.

