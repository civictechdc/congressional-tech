---
id: ct-dx22
status: open
deps: []
links: [ct-qg8e]
created: 2026-11-02T00:36:42Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, phase2]
---
# Witnesses attach to the wrong hearing on events with several packages

single_package_meetings (appearance-records-resolved.sql:107-111) checks that a package has one event, not that an event has one package. On 17 events with two or three linked packages, raw MODS titles show v21 chose worse on 3 (100202, 101167, 335827) and tied on 6. Traced to 959c23ee; 86 events are exposed. Evidence: docs/measurements/release-diff-c94bfedc-448651e7-20261101.md.

## Acceptance Criteria

Every event's selected package is justified by a raw record, or no package-sourced witnesses attach; a test covers an event with two packages.


## Notes

**2026-11-02T12:28:27Z**

Round 1b 2026-11-02 (lead): Two-way package-to-meeting rule moves 392 rows on 93 events to package-only; House witness lists get their event from their own document links (187); MODS event-ID links (285 pairs) included. impl-f.

**2026-11-02T13:22:51Z**

2026-11-02 impl-f (r1b-f, 12 commits): package links must hold both ways; MODS eventId counts as a package-to-meeting link (errata prints like 321961 were dropped by the one-package filter); package witness changes mostly ambiguous because MODS states no eventId, 31 unread. Witness keys: 3,921 lost, 3,253 gained (gate 1 cause; release-note-only per ct-ktfe).
