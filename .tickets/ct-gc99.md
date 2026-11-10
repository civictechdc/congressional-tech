---
id: ct-gc99
status: open
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: task
priority: 2
assignee: mikewolfd
tags: [gate, release]
---
# Release gate's automatic cause cannot cover a backlog ingest

AUTOMATIC_GROUPS accepts an addition only when it traces to receipts newer than the live release's newest dated receipt. On 2026-11-10, 565 of the 727 added documents came from receipts new to the release but dated 2026-10-31, older than that mark, so the automatic proof refused at its first check and every added-row group needed a hand cause. Because the daily ingests oldest first within a budget, this happens whenever a backlog is being worked off. Source: .cache/archive-release/release-20261110/causes/capture-address/README.md.

## Acceptance Criteria

The automatic rule keys on receipts absent from the live release's receipt set (by key), not on their date, or the limitation is documented with the hand procedure. A backlog ingest of only new rows passes without hand entries; a planted changed row is still refused.

