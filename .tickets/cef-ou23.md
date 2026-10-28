---
id: cef-ou23
status: in_progress
deps: []
links: []
created: 2026-10-28T01:49:40Z
type: bug
priority: 0
assignee: mikewolfd
---
# Persist D2 unreadable decisions through the shared raw importer

Owner B4 engine adoption: use provenance.import_unreadable with an explicit create-only BodyStore, and make stage-only decisions visibly pending. Refuse lake append before effects until pending decisions are durably imported. Delete all parser stages and replay raw provenance to prove exclusion, while missing reads remain pending and old parser versions do not settle new work.

