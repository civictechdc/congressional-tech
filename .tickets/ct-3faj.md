---
id: ct-3faj
status: open
deps: [ct-copj]
links: []
created: 2026-10-20T18:50:27Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, recovery]
---
# Retain producer inputs after an indeterminate native request

An HTTP timeout can return while the native owner is still admitting producer Parquet. Deleting the temporary file at caller exit can break that admitted work. Retain unknown-outcome inputs and expose their location and byte cost until native state proves safe release.

## Acceptance Criteria

Tests cover timeout before and after admission, retained source after host exit, exact retry identity, and successful/refused cleanup. No retry, success cache, guessed admission, secret logging, or automatic deletion of unknown inputs.

