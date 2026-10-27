---
id: cef-et5q
status: in_progress
deps: []
links: []
created: 2026-10-27T22:04:37Z
type: task
priority: 2
assignee: mikewolfd
---
# Prepare catalog maintenance configuration up to the M1 owner gate

D5: one Basin catalog policy for128MBcompaction,30dayexpiration,5retained snapshots. Dry run opens no credential or transport; thin injected metadata API adapter validates service credential status, writes once only when changed and verifies effective config. Test only fake clients. Live enablement remains owner/M1-gated; no table compactor or raw writes.

