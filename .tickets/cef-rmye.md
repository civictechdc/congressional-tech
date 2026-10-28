---
id: cef-rmye
status: in_progress
deps: []
links: []
created: 2026-10-28T08:14:24Z
type: task
priority: 1
assignee: mikewolfd
---
# Bind daily lake production to the guarded publisher

Compose the maintained D1/D2/D3 producer with the guarded publisher. Publish only completed fresh three-table pins and the complete receipt set; retain all opaque provenance metadata, consume exactly qualified model record files, and include acknowledged unreadable imports. Pending/backfill results must not reach model or publication effects. Reuse native jobs, raw cache transport and publisher startup/probes; no injectable producer policy or second data path.

