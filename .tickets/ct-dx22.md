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

