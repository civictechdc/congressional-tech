---
id: cef-ou23
status: closed
deps: []
links: []
created: 2026-10-28T01:49:40Z
type: bug
priority: 0
assignee: mikewolfd
---
# Persist D2 unreadable decisions through the shared raw importer

Owner B4 engine adoption: use provenance.import_unreadable with an explicit create-only BodyStore, and make stage-only decisions visibly pending. Refuse lake append before effects until pending decisions are durably imported. Delete all parser stages and replay raw provenance to prove exclusion, while missing reads remain pending and old parser versions do not settle new work.


## Notes

**2026-10-28T03:11:58Z**

D2 shared-import binding842fb451 and current-capture replay0084f465 pass24 focused native checks15.42s, including original receipts/bodies plus durable unreadable records after deleting all derived stages. Prior CODE and ARCH reviews approved. Missing storage remains pending and append refuses pending decisions before catalog effects.
